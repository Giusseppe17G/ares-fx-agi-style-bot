"""Read-only latency measurement helpers."""

from __future__ import annotations

from time import perf_counter
from typing import Any, Callable


def measure_latency_ms(call: Callable[[], Any]) -> tuple[Any, int, str]:
    started = perf_counter()
    try:
        value = call()
        return value, int((perf_counter() - started) * 1000), ""
    except Exception as exc:
        return None, int((perf_counter() - started) * 1000), str(exc)

