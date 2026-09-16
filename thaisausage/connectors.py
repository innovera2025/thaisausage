import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlencode
from urllib.request import Request, build_opener, HTTPRedirectHandler

from .contracts import ContractError


class RemoteError(Exception):
    def __init__(self, status=None, detail=None):
        self.status = status
        # The upstream explanation is kept for the operator; it never changes control flow.
        self.detail = detail
        super().__init__("Upstream request failed")


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request_json(method, base_url, path, headers, timeout, payload=None):
    parts = urlsplit(base_url)
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
        raise ContractError("Connector base_url must be HTTPS without credentials, query or fragment")
    if not isinstance(path, str) or not path.startswith("/") or path.startswith("//"):
        raise ContractError("Connector path must start with a single /")
    url = base_url.rstrip("/") + path
    body = None if payload is None else json.dumps(payload, allow_nan=False).encode("utf-8")
    req = Request(url, data=body, method=method, headers={
        "Accept": "application/json", "Content-Type": "application/json", **headers})
    try:
        with build_opener(NoRedirect).open(req, timeout=timeout) as response:
            content = response.read(4 * 1024 * 1024 + 1)
            if len(content) > 4 * 1024 * 1024:
                raise RemoteError(response.status)
            return json.loads(content)
    except HTTPError as error:
        try:
            detail = error.read(2048).decode("utf-8", "replace").strip() or None
        except Exception:
            detail = None
        raise RemoteError(error.code, detail) from None
    except (URLError, OSError, ValueError):
        raise RemoteError() from None


def lookup(value, path):
    if not path:
        return value
    for key in path.split("."):
        if not isinstance(value, dict) or key not in value:
            return None
        value = value[key]
    return value


def mapped(source, field_map):
    result = {}
    for target, source_path in field_map.items():
        current = result
        keys = target.split(".")
        for key in keys[:-1]:
            current = current.setdefault(key, {})
        current[keys[-1]] = lookup(source, source_path)
    return result


class ERPConnector:
    """Read a configured ERP REST endpoint; vendor pagination belongs in a subclass."""
    def __init__(self, config):
        self.config = config

    def fetch_orders(self, query):
        config = self.config
        if not config.get("base_url"):
            raise ContractError("Configure erp.base_url before pulling ERP orders")
        token = os.environ.get(config["token_env"])
        if not token:
            raise ContractError("Set the ERP token environment variable")
        path = config["orders_path"]
        if query:
            path += ("&" if "?" in path else "?") + urlencode(query)
        result = request_json("GET", config["base_url"], path,
                              {config["auth_header"]: config["auth_prefix"] + token},
                              config["timeout_seconds"])
        orders = lookup(result, config["orders_list_path"])
        if not isinstance(orders, list):
            raise ContractError("ERP response does not match orders_list_path")
        return [self.map_order(order) for order in orders]

    def map_order(self, order):
        if not isinstance(order, dict):
            raise ContractError("ERP order must be an object")
        result = mapped(order, self.config["field_map"])
        items = lookup(order, self.config["items_path"])
        if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
            raise ContractError("ERP items must be an array of objects")
        result["items"] = [mapped(item, self.config["item_field_map"]) for item in items]
        return result


class VRPConnector:
    def __init__(self, config):
        self.config = config

    def send(self, payload):
        token = os.environ.get(self.config["token_env"])
        if not token:
            raise ContractError("Set the VRP token environment variable")
        return request_json("POST", self.config["base_url"], "/v1/orders/import",
                            {"X-Token": token}, self.config["timeout_seconds"], payload)
