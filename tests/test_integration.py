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

from thaisausage.api import create_server
from thaisausage.config import load_dotenv
from thaisausage.connectors import ERPConnector, RemoteError, VRPConnector
from thaisausage.contracts import ContractError, validate_orders
from thaisausage.service import Conflict, IntegrationService


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
        self.assertEqual(result, {"receipt_id": "DO-1", "state": "staged", "erp_write": False})
        replay = self.service.receive_do({"receipt_id": "DO-1", "do_no": "DO-1", "status": "delivered"})
        self.assertTrue(replay["replayed"])
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

    def test_scheduled_approved_sweep_skips_claimed_order_in_live_mode(self):
        sqlserver = Mock()
        sqlserver.fetch_approved_orders.return_value = self.payload["orders"]
        self.service.submit(self.payload)
        result = self.service.sweep_approved_orders(sqlserver)
        self.assertEqual(result[0]["reason"], "already_claimed")
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


if __name__ == "__main__":
    unittest.main()
