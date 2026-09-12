import math
import re
from datetime import date


class ContractError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise ContractError(message)


def text(value):
    return isinstance(value, str) and bool(value.strip())


def number(value):
    return type(value) in (int, float) and math.isfinite(value)


def valid_date(value):
    try:
        return isinstance(value, str) and date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def validate_orders(payload):
    require(isinstance(payload, dict), "body must be an object")
    require(text(payload.get("request_id")), "request_id is required")
    require(re.fullmatch(r"[A-Za-z0-9._:-]{1,120}", payload["request_id"]) is not None,
            "request_id must be 1..120 characters: A-Z a-z 0-9 . _ : -")
    orders = payload.get("orders")
    require(isinstance(orders, list) and 0 < len(orders) <= 100,
            "orders must contain 1..100 orders (local limit)")
    seen = set()
    for index, order in enumerate(orders):
        prefix = "orders[%d]" % index
        require(isinstance(order, dict), prefix + " must be an object")
        for key in ("order_no", "pickup_hub_code"):
            require(text(order.get(key)), prefix + "." + key + " is required")
        require(len(order["order_no"]) <= 100, "order_no must be <= 100 characters")
        require(text(order.get("delivery_point_code")) or text(order.get("shipping_address")),
                "delivery_point_code or shipping_address is required")
        require(order["order_no"] not in seen, "duplicate order_no in batch")
        seen.add(order["order_no"])
        require(valid_date(order.get("order_date")), prefix + ".order_date must be YYYY-MM-DD")
        require(order.get("delivery_date") in (None, "") or valid_date(order["delivery_date"]),
                prefix + ".delivery_date must be null or YYYY-MM-DD")
        credit = order.get("payment_in_day")
        require(credit is None or (number(credit) and credit >= 0), prefix + ".payment_in_day must be null or >= 0")
        customer = order.get("customer")
        require(isinstance(customer, dict), prefix + ".customer is required")
        for key in ("code",):
            require(text(customer.get(key)), prefix + ".customer." + key + " is required")
        require(len(customer["code"]) <= 50, "customer.code must be <= 50 characters")
        items = order.get("items")
        require(isinstance(items, list) and 0 < len(items) <= 2000, prefix + ".items must contain 1..2000 items")
        for item in items:
            require(isinstance(item, dict), "item must be an object")
            require(text(item.get("item_code")), "item_code is required")
            require(len(item["item_code"]) <= 50, "item_code must be <= 50 characters")
            for dimension in ("cbm", "nw"):
                value = item.get(dimension)
                require(value is None or (number(value) and value >= 0), dimension + " must be null or >= 0")
            require(number(item.get("quantity")) and item["quantity"] > 0, "quantity must be > 0")
            require(number(item.get("unit_price")) and item["unit_price"] >= 0,
                    "unit_price must be >= 0; free items are supported")
    return payload
