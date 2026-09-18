import copy
import json
import os
import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from thaisausage.__main__ import run_sweep_cycle
from thaisausage.api import create_server
from thaisausage.config import load_dotenv
from thaisausage.do_writer import DOWriter
from thaisausage.connectors import ERPConnector, RemoteError, VRPConnector
from thaisausage.contracts import ContractError, validate_orders
from thaisausage.service import Conflict, IntegrationService, safe_identifier


ROOT = Path(__file__).resolve().parents[1]


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.database = str(Path(self.temp.name) / "test.sqlite3")
        self.payload = json.loads((ROOT / "examples/erp-order.json").read_text())
        self.config = json.loads((ROOT / "config/example.json").read_text())
        self.vrp = Mock()
        self.vrp.send.return_value = {"success": True}
        self.erp = Mock()
        self.service = IntegrationService(self.database, False, self.vrp, self.erp)

    def test_dotenv_loads_without_overriding_environment(self):
        env_path = Path(self.temp.name) / ".env"
        env_path.write_text("# comment\nDOTENV_NEW='new value'\nDOTENV_EXISTING=file\n", encoding="utf-8")
        with patch.dict(os.environ, {"DOTENV_EXISTING": "environment"}, clear=False):
            load_dotenv(str(env_path))
            self.assertEqual(os.environ["DOTENV_NEW"], "new value")
            self.assertEqual(os.environ["DOTENV_EXISTING"], "environment")

    def test_dry_run_then_live_does_not_consume_request(self):
        dry = IntegrationService(self.database, True, self.vrp, self.erp)
        self.assertEqual(dry.submit(self.payload)["state"], "validated")
        self.vrp.send.assert_not_called()
        self.assertIsNone(dry.get(self.payload["request_id"]))
        self.assertEqual(self.service.submit(self.payload)["state"], "sent")

    def test_persistent_idempotency_after_restart(self):
        self.service.submit(self.payload)
        restarted = IntegrationService(self.database, False, self.vrp, self.erp)
        self.assertTrue(restarted.submit(self.payload)["replayed"])
        self.vrp.send.assert_called_once()
        with sqlite3.connect(self.database) as db:
            self.assertEqual(db.execute("SELECT state FROM submissions").fetchall(), [("sent",)])

    def test_changed_payload_conflicts(self):
        self.service.submit(self.payload)
        self.payload["orders"][0]["items"][0]["quantity"] = 3
        with self.assertRaises(Conflict):
            self.service.submit(self.payload)
        self.vrp.send.assert_called_once()

    def test_same_order_different_request_conflicts(self):
        self.service.submit(self.payload)
        self.payload["request_id"] = "another-id"
        with self.assertRaises(Conflict):
            self.service.submit(self.payload)

    def test_concurrent_duplicate_sends_once(self):
        with ThreadPoolExecutor(max_workers=5) as pool:
            results = list(pool.map(lambda _: self.service.submit(self.payload), range(5)))
        self.assertEqual(len(results), 5)
        self.vrp.send.assert_called_once()

    def test_timeout_and_unconfirmed_response_require_review(self):
        self.vrp.send.side_effect = RemoteError()
        self.assertEqual(self.service.submit(self.payload)["state"], "needs_review")
        self.assertTrue(self.service.submit(self.payload)["replayed"])
        self.vrp.send.assert_called_once()
        self.payload["request_id"] = "next-id"
        self.payload["orders"][0]["order_no"] = "next-order"
        self.vrp.send.side_effect = None
        self.vrp.send.return_value = {"success": False}
        self.assertEqual(self.service.submit(self.payload)["state"], "needs_review")

    def test_validation_rejects_bad_values_before_outbound(self):
        for field, value in (("quantity", 0), ("quantity", True), ("unit_price", -1), ("quantity", float("nan"))):
            payload = copy.deepcopy(self.payload)
            payload["orders"][0]["items"][0][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ContractError):
                self.service.submit(payload)
        self.vrp.send.assert_not_called()

    def test_free_item_stays_separate(self):
        item = copy.deepcopy(self.payload["orders"][0]["items"][0])
        item.update(line_no=2, unit_price=0)
        self.payload["orders"][0]["items"].append(item)
        self.assertEqual(len(validate_orders(self.payload)["orders"][0]["items"]), 2)

    def test_vendor_optional_fields_and_address_fallback(self):
        order = self.payload["orders"][0]
        order["payment_in_day"] = None
        order["delivery_date"] = ""
        del order["customer"]["name"]
        del order["delivery_point_code"]
        del order["items"][0]["line_no"]
        validate_orders(self.payload)
        order["delivery_point_code"] = "POINT-1"
        del order["shipping_address"]
        validate_orders(self.payload)

    def test_vendor_request_id_restrictions(self):
        for value in ("x" * 121, "id with space", "เลขที่", "id/path"):
            with self.subTest(value=value), self.assertRaises(ContractError):
                validate_orders({**self.payload, "request_id": value})

    def test_atomic_claim_rollback_on_order_conflict(self):
        self.service.submit(self.payload)
        fresh = copy.deepcopy(self.payload["orders"][0])
        fresh["order_no"] = "FRESH-SO"
        with self.assertRaises(Conflict):
            self.service.submit({"request_id": "CONFLICT-BATCH", "orders": [fresh, self.payload["orders"][0]]})
        with sqlite3.connect(self.database) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM order_claims WHERE order_no='FRESH-SO'").fetchone()[0], 0)
        self.assertIsNone(self.service.get("CONFLICT-BATCH"))

    def test_vrp_references_persist(self):
        self.vrp.send.return_value = {"success": True, "batch_uuid": "batch-1",
                                      "results": [{"order_no": "SO-DEMO-0001", "running_code": "VRP-1"}]}
        self.service.submit(self.payload)
        result = self.service.get(self.payload["request_id"])
        self.assertEqual(result["vrp"]["batch_uuid"], "batch-1")
        self.assertEqual(result["vrp"]["orders"][0]["running_code"], "VRP-1")

    def test_erp_hook_is_durable_trigger_and_idempotent(self):
        hook = {"event_id": "ERP-EVENT-1", "event_type": "sales_order.ready",
                "source_id": "main-erp", "company_id": "THAI", "order_no": "SO-1"}
        self.assertEqual(self.service.record_erp_hook(hook)["sweep"], "queued")
        self.assertTrue(self.service.record_erp_hook(hook)["replayed"])
        self.vrp.send.assert_not_called()
        with sqlite3.connect(self.database) as db:
            self.assertEqual(db.execute("SELECT state,order_no FROM erp_hooks").fetchone(), ("received", "SO-1"))

    def test_erp_hook_rejects_unknown_event(self):
        with self.assertRaises(ContractError):
            self.service.record_erp_hook({"event_id": "E-1", "event_type": "invoice.paid", "source_id": "erp"})

    def test_erp_hook_rejects_unsafe_event_id(self):
        with self.assertRaises(ContractError):
            self.service.record_erp_hook({"event_id": "E/1", "event_type": "sales_order.ready", "source_id": "erp"})

    def test_erp_hook_changed_payload_conflicts(self):
        hook = {"event_id": "E-CONFLICT", "event_type": "sales_order.ready",
                "source_id": "erp", "order_no": "SO-1"}
        self.service.record_erp_hook(hook)
        with self.assertRaises(Conflict):
            self.service.record_erp_hook({**hook, "order_no": "SO-2"})

    def test_dry_run_sweep_keeps_hook_received_for_live_replay(self):
        dry = IntegrationService(self.database, True, self.vrp, self.erp)
        dry.record_erp_hook({"event_id": "E-DRY", "event_type": "sales_order.ready",
                             "source_id": "erp", "order_no": "SO-1"})
        sqlserver = Mock()
        sqlserver.fetch_orders.return_value = self.payload["orders"]
        self.assertEqual(dry.sweep_hooks(sqlserver)[0]["state"], "received")
        with sqlite3.connect(self.database) as db:
            self.assertEqual(db.execute("SELECT state,reason FROM erp_hooks WHERE event_id='E-DRY'").fetchone(),
                             ("received", "dry_run_preview"))

    def test_do_is_staged_without_erp_write(self):
        result = self.service.receive_do({"receipt_id": "DO-1", "do_no": "DO-1", "status": "delivered"})
        self.assertEqual(result, {"receipt_id": "DO-1", "receipt_key": "erp:DO-1", "source": "erp",
                                  "state": "staged", "erp_write": False})
        replay = self.service.receive_do({"receipt_id": "DO-1", "do_no": "DO-1", "status": "delivered"})
        self.assertTrue(replay["replayed"])
        self.assertIs(replay["erp_write"], False)  # Every accepted DO answer states the ERP boundary.
        with sqlite3.connect(self.database) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM do_receipts").fetchone()[0], 1)

    def test_hook_sweep_reads_then_uses_single_submission_pipeline(self):
        self.service.record_erp_hook({"event_id": "E-SWEEP", "event_type": "sales_order.ready",
                                      "source_id": "main-erp", "order_no": "SO-1"})
        sqlserver = Mock()
        sqlserver.fetch_orders.return_value = self.payload["orders"]
        result = self.service.sweep_hooks(sqlserver)
        self.assertEqual(result[0]["state"], "sent")
        sqlserver.fetch_orders.assert_called_once_with("SO-1")
        self.vrp.send.assert_called_once()
        with sqlite3.connect(self.database) as db:
            self.assertEqual(db.execute("SELECT state FROM erp_hooks WHERE event_id='E-SWEEP'").fetchone()[0], "sent")

    def test_scheduled_approved_sweep_previews_without_consuming_order(self):
        sqlserver = Mock()
        sqlserver.fetch_approved_orders.return_value = self.payload["orders"]
        dry = IntegrationService(self.database, True, self.vrp, self.erp)
        result = dry.sweep_approved_orders(sqlserver)
        self.assertEqual(result, [{"order_no": "SO-DEMO-0001", "state": "preview", "reason": "dry_run_preview"}])
        self.vrp.send.assert_not_called()

    def test_scheduler_reads_nothing_while_sync_is_disabled(self):
        sqlserver = Mock()
        config = {"sync": {"enabled": False, "interval_seconds": 60}}
        self.assertIsNone(run_sweep_cycle(config, self.service, sqlserver))
        sqlserver.fetch_approved_orders.assert_not_called()
        config["sync"]["enabled"] = True
        sqlserver.fetch_approved_orders.return_value = []
        self.assertEqual(run_sweep_cycle(config, self.service, sqlserver), [])
        sqlserver.fetch_approved_orders.assert_called_once_with()

    def test_scheduled_approved_sweep_isolates_one_unusable_order(self):
        sqlserver = Mock()
        broken = copy.deepcopy(self.payload["orders"][0])
        broken.update(order_no="SO-BROKEN", order_date="not-a-date")
        sqlserver.fetch_approved_orders.return_value = [broken, self.payload["orders"][0]]
        result = self.service.sweep_approved_orders(sqlserver)
        self.assertEqual(result[0], {"order_no": "SO-BROKEN", "state": "review", "reason": "ContractError"})
        self.assertEqual(result[1]["state"], "sent")  # The healthy SO still reaches eVRP.
        self.vrp.send.assert_called_once()

    def test_scheduled_approved_sweep_reviews_row_without_order_no(self):
        sqlserver = Mock()
        sqlserver.fetch_approved_orders.return_value = [{"customer": {"code": "C-1"}}]
        result = self.service.sweep_approved_orders(sqlserver)
        self.assertEqual(result, [{"order_no": None, "state": "review", "reason": "order_no_missing"}])
        self.vrp.send.assert_not_called()

    def test_scheduled_approved_sweep_skips_claimed_order_in_live_mode(self):
        sqlserver = Mock()
        sqlserver.fetch_approved_orders.return_value = self.payload["orders"]
        self.service.submit(self.payload)
        result = self.service.sweep_approved_orders(sqlserver)
        self.assertEqual(result[0]["reason"], "already_sent")
        self.vrp.send.assert_called_once()

    def test_erp_mapping_nested_fields(self):
        config = self.config["erp"]
        config.update(field_map={"order_no": "so.number", "customer.code": "buyer.id"},
                      items_path="lines", item_field_map={"item_code": "sku"})
        result = ERPConnector(config).map_order({"so": {"number": "SO-1"},
                                                "buyer": {"id": "C-1"}, "lines": [{"sku": "I-1"}]})
        self.assertEqual(result, {"order_no": "SO-1", "customer": {"code": "C-1"},
                                  "items": [{"item_code": "I-1"}]})

    def test_connector_headers_and_pull_query(self):
        config = self.config["erp"]
        config["base_url"] = "https://erp.example.test"
        with patch.dict(os.environ, ERP_TOKEN="fake-erp", VRP_TOKEN="fake-vrp"):
            with patch("thaisausage.connectors.request_json", return_value={"data": {"orders": self.payload["orders"]}}) as request:
                orders = ERPConnector(config).fetch_orders({"page": 2})
                self.assertEqual(orders[0]["order_no"], self.payload["orders"][0]["order_no"])
                self.assertEqual(request.call_args.args[2], "/api/orders?page=2")
                self.assertEqual(request.call_args.args[3], {"Authorization": "Bearer fake-erp"})
            with patch("thaisausage.connectors.request_json", return_value={"success": True}) as request:
                VRPConnector(self.config["vrp"]).send(self.payload)
                self.assertEqual(request.call_args.args[2], "/v1/orders/import")
                self.assertEqual(request.call_args.args[3], {"X-Token": "fake-vrp"})

    def test_http_push_pull_auth_validation_and_status(self):
        self.config.update(host="127.0.0.1", port=0)
        with patch.dict(os.environ, THAISAUSAGE_API_KEY="test-key"):
            server = create_server(self.config, self.service)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        def cleanup():
            server.shutdown()
            server.server_close()
            thread.join()
        self.addCleanup(cleanup)
        base = "http://127.0.0.1:%s" % server.server_port

        def call(path, payload=None, authorized=True):
            headers = {"Content-Type": "application/json"}
            if authorized:
                headers["Authorization"] = "Bearer test-key"
            req = Request(base + path, data=None if payload is None else json.dumps(payload).encode(), headers=headers)
            try:
                response = urlopen(req, timeout=3)
            except HTTPError as error:
                response = error
            with response:
                body = response.read()
                try:
                    return response.status, json.loads(body)
                except json.JSONDecodeError:
                    return response.status, body.decode()

        self.assertEqual(call("/health", authorized=False)[0], 200)
        self.assertEqual(call("/openapi.json", authorized=False)[1]["openapi"], "3.0.3")
        self.assertEqual(call("/docs", authorized=False)[0], 200)
        self.assertEqual(call("/api/v1/erp/orders", self.payload, False)[0], 401)
        self.assertEqual(call("/api/v1/erp/orders", {"orders": []})[0], 422)
        self.assertEqual(call("/api/v1/erp/orders", self.payload)[1]["state"], "sent")
        self.assertEqual(call("/api/v1/submissions/ERP-DEMO-0001")[1]["state"], "sent")
        self.erp.fetch_orders.return_value = copy.deepcopy(self.payload["orders"])
        self.erp.fetch_orders.return_value[0]["order_no"] = "PULLED-SO"
        self.assertEqual(call("/api/v1/erp/pull", {"request_id": "PULL-1", "query": {"page": 1}})[1]["state"], "sent")
        self.erp.fetch_orders.assert_called_once_with({"page": 1})
        self.erp.fetch_orders.return_value = []
        self.assertEqual(call("/api/v1/erp/pull", {"request_id": "PULL-EMPTY"})[1]["state"], "empty")

    def test_vrp_do_callback_is_staged_and_does_not_write_erp(self):
        self.config.update(host="127.0.0.1", port=0)
        with patch.dict(os.environ, THAISAUSAGE_API_KEY="test-key"):
            server = create_server(self.config, self.service)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.shutdown)
        self.addCleanup(server.server_close)
        base = "http://127.0.0.1:%s" % server.server_port

        def call(payload, authorized=True, raw=None):
            headers = {"Content-Type": "application/json"}
            if authorized:
                headers["Authorization"] = "Bearer test-key"
            request = Request(base + "/api/v1/vrp/do-received",
                              data=raw if raw is not None else json.dumps(payload).encode(), headers=headers)
            try:
                response = urlopen(request, timeout=3)
            except HTTPError as error:
                response = error
            with response:
                return response.status, json.loads(response.read())

        payload = {"receipt_id": "VRP-DO-1", "do_no": "DO-1", "status": "completed"}
        self.assertEqual(call(payload, authorized=False)[0], 401)
        status, result = call(payload)
        self.assertEqual(status, 202)
        self.assertEqual(result["state"], "staged")
        self.assertEqual(result["source"], "eVRP")
        self.assertFalse(result["erp_write"])

        status, replay = call(payload)  # eVRP retries are safe.
        self.assertEqual(status, 202)
        self.assertTrue(replay["replayed"])
        self.assertFalse(replay["erp_write"])

        changed = {**payload, "status": "cancelled"}
        self.assertEqual(call(changed)[0], 409)
        self.assertEqual(call(None, raw=b'{"receipt_id": ')[0], 422)  # Invalid JSON.
        self.assertEqual(call({"status": "completed"})[0], 422)  # No receipt_id and no do_no.

        self.erp.assert_not_called()
        self.vrp.send.assert_not_called()  # A staged DO is never pushed back to eVRP.
        with sqlite3.connect(self.database) as db:
            self.assertEqual(db.execute("SELECT COUNT(*),MAX(source),MAX(receipt_key) FROM do_receipts").fetchone(),
                             (1, "eVRP", "eVRP:VRP-DO-1"))

    def test_vrp_do_callback_writes_when_writer_is_configured(self):
        self.config.update(host="127.0.0.1", port=0, dry_run=False)
        writer = Mock()
        writer.write.return_value = {"transaction_no": "TX-1", "header_rows": 1, "detail_rows": 1,
                                     "committed": True}
        with patch.dict(os.environ, THAISAUSAGE_API_KEY="test-key"):
            server = create_server(self.config, self.service, do_writer=writer)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.shutdown)
        self.addCleanup(server.server_close)
        payload = {"receipt_id": "VRP-DO-WRITE", "do_no": "DO-WRITE", "transaction_no": "TX-1",
                   "header": {"do_no": "DO-WRITE"}, "details": [{"item_code": "ITEM-1"}]}
        request = Request("http://127.0.0.1:%s/api/v1/vrp/do-received" % server.server_port,
                          data=json.dumps(payload).encode(),
                          headers={"Content-Type": "application/json", "Authorization": "Bearer test-key"})
        with urlopen(request, timeout=3) as response:
            result = json.loads(response.read())
        self.assertIs(result["erp_write"], True)  # Boolean, so a caller cannot misread a state string.
        self.assertEqual(result["do_write"]["state"], "inserted")
        self.assertEqual(result["do_write"]["header_rows"], 1)
        writer.write.assert_called_once_with(payload, "TX-1")


class ScheduledSweepRegressionTests(unittest.TestCase):
    """Regression tests for the scheduled SO flow findings."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.database = str(Path(self.temp.name) / "sweep.sqlite3")
        self.payload = json.loads((ROOT / "examples/erp-order.json").read_text())
        self.vrp = Mock()
        self.vrp.send.return_value = {"success": True}
        self.service = IntegrationService(self.database, False, self.vrp, Mock())

    def test_order_with_unusable_detail_is_reviewed_not_sent(self):
        sqlserver = Mock()
        broken = copy.deepcopy(self.payload["orders"][0])
        broken.update(order_no="SO-NO-ITEM", rejected_reason="detail_item_code_missing")
        sqlserver.fetch_approved_orders.return_value = [broken, self.payload["orders"][0]]
        results = self.service.sweep_approved_orders(sqlserver)
        self.assertEqual(results[0], {"order_no": "SO-NO-ITEM", "state": "review",
                                      "reason": "detail_item_code_missing"})
        self.assertEqual(results[1]["state"], "sent")
        self.vrp.send.assert_called_once()

    def test_unresolved_previous_attempt_is_reported_not_skipped(self):
        self.vrp.send.side_effect = RemoteError()
        sqlserver = Mock()
        sqlserver.fetch_approved_orders.return_value = [self.payload["orders"][0]]
        first = self.service.sweep_approved_orders(sqlserver)
        self.assertEqual(first[0]["state"], "needs_review")
        second = self.service.sweep_approved_orders(sqlserver)
        self.assertEqual(second[0], {"order_no": "SO-DEMO-0001", "state": "needs_review",
                                     "reason": "prior_attempt_needs_review"})
        self.vrp.send.assert_called_once()  # An unknown outcome is never retried automatically.

    def test_sent_order_is_reported_as_already_sent(self):
        sqlserver = Mock()
        sqlserver.fetch_approved_orders.return_value = [self.payload["orders"][0]]
        self.service.sweep_approved_orders(sqlserver)
        again = self.service.sweep_approved_orders(sqlserver)
        self.assertEqual(again[0]["reason"], "already_sent")
        self.vrp.send.assert_called_once()

    def test_unreadable_batch_returns_a_known_state_instead_of_raising(self):
        sqlserver = Mock()
        sqlserver.fetch_approved_orders.side_effect = ContractError("SQL result is missing the configured order_key")
        results = self.service.sweep_approved_orders(sqlserver)
        self.assertEqual(results, [{"order_no": None, "state": "review", "reason": "ContractError"}])
        self.vrp.send.assert_not_called()

    def test_cycle_log_carries_counts_only(self):
        sqlserver = Mock()
        sqlserver.fetch_approved_orders.return_value = [self.payload["orders"][0]]
        config = {"sync": {"enabled": True, "interval_seconds": 60}}
        with self.assertLogs("thaisausage.__main__", level="INFO") as logs:
            run_sweep_cycle(config, self.service, sqlserver)
        self.assertEqual(len(logs.output), 1)
        for secret in ("SO-DEMO-0001", "ลูกค้า", "ITEM", "address"):
            self.assertNotIn(secret, logs.output[0])
        self.assertIn("orders=1", logs.output[0])

    def test_identifiers_that_are_not_plain_are_never_logged(self):
        sqlserver = Mock()
        leaky = copy.deepcopy(self.payload["orders"][0])
        leaky["order_no"] = {"customer": "ลูกค้าทดสอบ", "phone": "0812345678"}
        sqlserver.fetch_approved_orders.return_value = [leaky]
        with self.assertLogs("thaisausage.service", level="WARNING") as logs:
            results = self.service.sweep_approved_orders(sqlserver)
        self.assertEqual(results[0]["reason"], "order_no_missing")
        self.assertNotIn("0812345678", "".join(logs.output))
        self.assertEqual(safe_identifier(leaky["order_no"]), "<redacted>")
        self.assertEqual(safe_identifier("SO-1"), "SO-1")


class DoCallbackConcurrencyTests(unittest.TestCase):
    """The eVRP callback must stay idempotent when deliveries overlap."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.database = str(Path(self.temp.name) / "do.sqlite3")
        self.service = IntegrationService(self.database, False, Mock(), Mock())
        self.payload = {"receipt_id": "VRP-DO-9", "do_no": "DO-9", "status": "completed"}

    def test_two_simultaneous_callbacks_stage_once_and_replay_once(self):
        start = threading.Barrier(2)

        def deliver(_):
            start.wait(timeout=5)
            return self.service.receive_do(dict(self.payload), "eVRP")

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(deliver, range(2)))
        self.assertEqual({result["state"] for result in results}, {"staged"})
        self.assertEqual(sum(1 for result in results if result.get("replayed")), 1)
        with sqlite3.connect(self.database) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM do_receipts").fetchone()[0], 1)

    def test_same_receipt_from_erp_and_evrp_stays_separate(self):
        erp = self.service.receive_do(dict(self.payload), "erp")
        vrp = self.service.receive_do({**self.payload, "status": "delivered"}, "eVRP")
        self.assertEqual(erp["receipt_key"], "erp:VRP-DO-9")
        self.assertEqual(vrp["receipt_key"], "eVRP:VRP-DO-9")
        with sqlite3.connect(self.database) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM do_receipts").fetchone()[0], 2)

    def test_changed_payload_from_the_same_source_still_conflicts(self):
        self.service.receive_do(dict(self.payload), "eVRP")
        with self.assertRaises(Conflict):
            self.service.receive_do({**self.payload, "status": "cancelled"}, "eVRP")


class DoCallbackWriterBoundaryTests(unittest.TestCase):
    """A staged DO always answers 202; the writer outcome is reported, never raised."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.database = str(Path(self.temp.name) / "callback.sqlite3")
        self.config = json.loads((ROOT / "config/example.json").read_text())
        self.config.update(host="127.0.0.1", port=0, dry_run=False, database=self.database)
        self.service = IntegrationService(self.database, False, Mock(), Mock())

    def serve(self, writer):
        with patch.dict(os.environ, THAISAUSAGE_API_KEY="test-key"):
            server = create_server(self.config, self.service, do_writer=writer)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return "http://127.0.0.1:%s/api/v1/vrp/do-received" % server.server_port

    def post(self, url, payload):
        request = Request(url, data=json.dumps(payload).encode(),
                          headers={"Content-Type": "application/json", "Authorization": "Bearer test-key"})
        try:
            response = urlopen(request, timeout=3)
        except HTTPError as error:
            response = error
        with response:
            return response.status, json.loads(response.read())

    def staged_rows(self):
        with sqlite3.connect(self.database) as db:
            return db.execute("SELECT receipt_key,state FROM do_receipts ORDER BY receipt_key").fetchall()

    def test_disabled_writer_keeps_erp_write_false(self):
        url = self.serve(DOWriter(self.config["do_write"]))  # enabled=false, exactly as deployed
        status, result = self.post(url, {"receipt_id": "D1", "do_no": "DO-1", "transaction_no": "TR-1",
                                         "header": {"do_no": "DO-1"}, "details": [{"item_code": "I-1"}]})
        self.assertEqual(status, 202)
        self.assertIs(result["erp_write"], False)
        self.assertEqual(result["do_write"], {"state": "disabled", "reason": "do_write_disabled",
                                              "transaction_no": "TR-1"})

    def test_callback_without_transaction_no_is_still_accepted(self):
        url = self.serve(DOWriter({**self.config["do_write"], "enabled": True}))
        status, result = self.post(url, {"receipt_id": "D2", "do_no": "DO-2", "status": "completed"})
        self.assertEqual(status, 202)  # eVRP sends no transaction_no today; that is not an error.
        self.assertIs(result["erp_write"], False)
        self.assertEqual(result["do_write"], {"state": "skipped", "reason": "transaction_no_missing"})
        self.assertEqual(self.staged_rows(), [("eVRP:D2", "staged")])

    def test_writer_rejection_does_not_fail_the_callback(self):
        url = self.serve(DOWriter({**self.config["do_write"], "enabled": True}))  # mapping still empty
        status, result = self.post(url, {"receipt_id": "D3", "do_no": "DO-3", "transaction_no": "TR-3",
                                         "header": {"do_no": "DO-3"}, "details": [{"item_code": "I-1"}]})
        self.assertEqual(status, 202)
        self.assertIs(result["erp_write"], False)
        self.assertEqual(result["do_write"]["state"], "rejected")
        self.assertEqual(self.staged_rows(), [("eVRP:D3", "staged")])

    def test_duplicate_transaction_no_is_reported_not_raised(self):
        writer = Mock()
        writer.write.return_value = {"transaction_no": "TR-9", "header_rows": 1, "detail_rows": 1,
                                     "committed": True}
        url = self.serve(writer)
        first = {"receipt_id": "D4", "do_no": "DO-4", "transaction_no": "TR-9",
                 "header": {"do_no": "DO-4"}, "details": [{"item_code": "I-1"}]}
        second = {**first, "receipt_id": "D5", "do_no": "DO-5"}
        self.assertIs(self.post(url, first)[1]["erp_write"], True)
        status, result = self.post(url, second)
        self.assertEqual(status, 202)  # The duplicate is an operator item, not an HTTP failure.
        self.assertIs(result["erp_write"], False)
        self.assertEqual(result["do_write"]["state"], "conflict")
        self.assertEqual(writer.write.call_count, 1)

    def test_erp_path_never_calls_the_writer(self):
        writer = Mock()
        url = self.serve(writer).replace("/api/v1/vrp/", "/api/v1/erp/")
        status, result = self.post(url, {"receipt_id": "D6", "do_no": "DO-6", "transaction_no": "TR-6"})
        self.assertEqual(status, 202)
        self.assertIs(result["erp_write"], False)
        self.assertNotIn("do_write", result)
        writer.write.assert_not_called()


class UpstreamErrorDetailTests(unittest.TestCase):
    """A refusal from eVRP must be readable afterwards without sending anything again."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.database = str(Path(self.temp.name) / "upstream.sqlite3")
        self.payload = json.loads((ROOT / "examples/erp-order.json").read_text())
        self.vrp = Mock()
        self.service = IntegrationService(self.database, False, self.vrp, Mock())

    def test_rejected_submission_records_the_upstream_message(self):
        self.vrp.send.side_effect = RemoteError(422, '{"message":"pickup_hub_code not found"}')
        result = self.service.submit(self.payload)
        self.assertEqual(result["reason"], "upstream_http_422")
        self.assertIn("pickup_hub_code", result["upstream_error"])
        stored = self.service.get(self.payload["request_id"])
        self.assertIn("pickup_hub_code", stored["upstream_error"])

    def test_long_upstream_message_is_truncated(self):
        self.vrp.send.side_effect = RemoteError(400, "x" * 4000)
        self.assertEqual(len(self.service.submit(self.payload)["upstream_error"]), 2000)

    def test_missing_detail_leaves_no_field(self):
        self.vrp.send.side_effect = RemoteError(500)
        self.assertNotIn("upstream_error", self.service.submit(self.payload))


class ConnectorErrorBodyTests(unittest.TestCase):
    def test_http_error_body_reaches_the_caller(self):
        from thaisausage.connectors import request_json
        body = b'{"success":false,"message":"pickup_hub_code h99 not found"}'
        error = HTTPError("https://vrp.example/api/v1/orders/import", 422, "Unprocessable", {}, None)
        error.read = lambda size=None: body
        with patch("thaisausage.connectors.build_opener") as opener:
            opener.return_value.open.side_effect = error
            with self.assertRaises(RemoteError) as caught:
                request_json("POST", "https://vrp.example", "/v1/orders/import", {}, 5, {"a": 1})
        self.assertEqual(caught.exception.status, 422)
        self.assertIn("h99 not found", caught.exception.detail)


class ScheduleRequestIdentityTests(unittest.TestCase):
    """eVRP remembers a request_id even after refusing it, so corrected data needs a new one."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.database = str(Path(self.temp.name) / "identity.sqlite3")
        self.payload = json.loads((ROOT / "examples/erp-order.json").read_text())
        self.vrp = Mock()
        self.vrp.send.return_value = {"success": True}
        self.service = IntegrationService(self.database, False, self.vrp, Mock())

    def sent_request_id(self, order):
        sqlserver = Mock()
        sqlserver.fetch_approved_orders.return_value = [order]
        self.service.sweep_approved_orders(sqlserver)
        return self.vrp.send.call_args.args[0]["request_id"]

    def test_identical_order_keeps_one_identity(self):
        first = self.sent_request_id(copy.deepcopy(self.payload["orders"][0]))
        with sqlite3.connect(self.database) as db:  # clear the claim as an operator would
            db.execute("DELETE FROM order_claims")
            db.execute("DELETE FROM submissions")
        second = self.sent_request_id(copy.deepcopy(self.payload["orders"][0]))
        self.assertEqual(first, second)

    def test_corrected_order_gets_a_new_identity(self):
        first = self.sent_request_id(copy.deepcopy(self.payload["orders"][0]))
        with sqlite3.connect(self.database) as db:
            db.execute("DELETE FROM order_claims")
            db.execute("DELETE FROM submissions")
        corrected = copy.deepcopy(self.payload["orders"][0])
        corrected["pickup_hub_code"] = "h01"  # the fix that caused REQUEST_ID_CONFLICT
        second = self.sent_request_id(corrected)
        self.assertNotEqual(first, second)
        self.assertTrue(second.startswith("SCHEDULE-"))
        self.assertLessEqual(len(second), 120)

    def test_identity_uses_only_characters_the_contract_allows(self):
        import re as regex
        value = self.sent_request_id(copy.deepcopy(self.payload["orders"][0]))
        self.assertRegex(value, regex.compile(r"^[A-Za-z0-9._:-]{1,120}$"))


class DestinationContractTests(unittest.TestCase):
    """Fields the destination requires are caught here, not by a rejected batch at eVRP."""

    def setUp(self):
        self.payload = json.loads((ROOT / "examples/erp-order.json").read_text())

    def test_item_without_description_is_rejected_locally(self):
        for value in (None, "", "   "):
            payload = copy.deepcopy(self.payload)
            if value is None:
                del payload["orders"][0]["items"][0]["description"]
            else:
                payload["orders"][0]["items"][0]["description"] = value
            with self.subTest(value=repr(value)), self.assertRaises(ContractError):
                validate_orders(payload)

    def test_payment_in_day_zero_means_cod_and_none_means_not_cod(self):
        payload = copy.deepcopy(self.payload)
        payload["orders"][0]["payment_in_day"] = 0
        self.assertEqual(validate_orders(payload)["orders"][0]["payment_in_day"], 0)
        payload["orders"][0]["payment_in_day"] = None
        self.assertIsNone(validate_orders(payload)["orders"][0]["payment_in_day"])
        payload["orders"][0]["payment_in_day"] = ""
        with self.assertRaises(ContractError):  # an empty string must never reach eVRP as COD
            validate_orders(payload)


if __name__ == "__main__":
    unittest.main()
