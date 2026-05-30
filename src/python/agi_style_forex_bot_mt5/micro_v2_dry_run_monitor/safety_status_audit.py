"""Safety flag scanning for dry-run monitor inputs."""

from __future__ import annotations

from typing import Any, Mapping


def audit_safety_status(*datasets: Mapping[str, Any]) -> dict[str, Any]:
    execution = any(_contains_true(dataset, "execution_attempted") for dataset in datasets)
    order_send = any(_contains_true(dataset, "order_send_called") for dataset in datasets)
    order_check = any(_contains_true(dataset, "order_check_called") for dataset in datasets)
    return {
        "safety_status": "SAFETY_BLOCKED" if execution or order_send or order_check else "SAFETY_CLEAR",
        "execution_attempted_detected": execution,
        "order_send_detected": order_send,
        "order_check_detected": order_check,
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def _contains_true(value: Any, key: str) -> bool:
    if isinstance(value, Mapping):
        for item_key, item_value in value.items():
            if str(item_key) == key and _truthy(item_value):
                return True
            if _contains_true(item_value, key):
                return True
    if isinstance(value, list):
        return any(_contains_true(item, key) for item in value)
    return False


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return False
