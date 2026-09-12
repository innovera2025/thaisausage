import hmac
import json
import os
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlsplit

from .connectors import RemoteError
from .contracts import ContractError, require, text
from .service import Conflict


def create_server(config, service):
    key = os.environ[config["api_key_env"]]
    openapi_path = Path(__file__).resolve().parent.parent / "docs" / "openapi.json"

    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(35)

        def log_message(self, format, *args):
            pass  # Do not log order/customer data or authorization headers.

        def reply(self, status, data):
            content = json.dumps(data, ensure_ascii=False, allow_nan=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(content)

        def authenticated(self):
            supplied = self.headers.get("Authorization", "")
            if not hmac.compare_digest(supplied.encode(), ("Bearer " + key).encode()):
                self.reply(401, {"error": "unauthorized"})
                return False
            return True

        def body(self):
            require(not self.headers.get("Transfer-Encoding"), "Transfer-Encoding is unsupported")
            require(self.headers.get_content_type() == "application/json", "Content-Type must be application/json")
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                raise ContractError("Content-Length must be an integer")
            require(0 < length <= 1024 * 1024, "body must be 1..1048576 bytes (local limit)")
            try:
                def reject_constant(value):
                    raise ValueError(value)
                payload = json.loads(self.rfile.read(length), parse_constant=reject_constant)
            except (ValueError, UnicodeError):
                raise ContractError("Invalid JSON")
            require(isinstance(payload, dict), "body must be an object")
            return payload

        def do_GET(self):
            path = urlsplit(self.path).path
            if path == "/health":
                return self.reply(200, {"status": "ok", "dry_run": config["dry_run"]})
            if path == "/openapi.json":
                try:
                    self.reply(200, json.loads(openapi_path.read_text(encoding="utf-8")))
                except (OSError, ValueError):
                    self.reply(500, {"error": "openapi_unavailable"})
                return
            if path == "/docs":
                html = b"<!doctype html><html><head><title>Thaisausage API</title><link rel=\"stylesheet\" href=\"https://unpkg.com/swagger-ui-dist@5/swagger-ui.css\"></head><body><div id=\"swagger-ui\"></div><script src=\"https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js\"></script><script>SwaggerUIBundle({url:'/openapi.json',dom_id:'#swagger-ui'})</script></body></html>"
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(html)))
                self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self' https://unpkg.com; style-src 'self' 'unsafe-inline' https://unpkg.com; img-src 'self' data: https://unpkg.com; connect-src 'self'")
                self.end_headers()
                self.wfile.write(html)
                return
            if not self.authenticated():
                return
            if path.startswith("/api/v1/submissions/"):
                result = service.get(unquote(path[len("/api/v1/submissions/"):]))
                return self.reply(200 if result else 404, result or {"error": "not_found"})
            self.reply(404, {"error": "not_found"})

        def do_POST(self):
            if not self.authenticated():
                return
            try:
                path = urlsplit(self.path).path
                if path not in ("/api/v1/erp/orders", "/api/v1/erp/pull", "/api/v1/erp/hooks/order-ready", "/api/v1/erp/do-received"):
                    return self.reply(404, {"error": "not_found"})
                payload = self.body()
                if path == "/api/v1/erp/hooks/order-ready":
                    result = service.record_erp_hook(payload)
                    return self.reply(202, result)
                if path == "/api/v1/erp/do-received":
                    result = service.receive_do(payload)
                    return self.reply(202, result)
                if path == "/api/v1/erp/pull":
                    require(text(payload.get("request_id")), "request_id is required")
                    query = payload.get("query", {})
                    require(isinstance(query, dict) and all(
                        isinstance(k, str) and type(v) in (str, int, float, bool)
                        for k, v in query.items()), "query must contain scalar values")
                    payload = {"request_id": payload["request_id"], "orders": service.erp.fetch_orders(query)}
                    if not payload["orders"]:
                        return self.reply(200, {"request_id": payload["request_id"], "state": "empty", "dry_run": config["dry_run"]})
                result = service.submit(payload)
                status = 202 if result["state"] in ("sending", "needs_review") else 200
                self.reply(status, result)
            except Conflict as error:
                self.reply(409, {"error": str(error)})
            except ContractError as error:
                self.reply(422, {"error": str(error)})
            except RemoteError:
                self.reply(502, {"error": "erp_request_failed"})
            except Exception:
                self.reply(500, {"error": "internal_error"})

    return ThreadingHTTPServer((config["host"], config["port"]), Handler)
