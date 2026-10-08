"""Fault Injector Middleware.

Deterministically induces failures on tool execution so recovery policies can be
tested without waiting for real upstream outages.

FaultContext carries the current directive (set per test case / per request):

    NONE                 pass through normally
    TIMEOUT              sleep briefly, then raise TimeoutError  (transient: first call only)
    TIMEOUT_PERSISTENT   every call raises TimeoutError
    MALFORMED            execute the tool, then corrupt the payload so it violates
                         the expected output schema (transient: first call only;
                         the corrupted payload still carries recoverable data)
    MALFORMED_PERSISTENT every call returns an unrecoverable, data-less payload

The *_PERSISTENT directives exercise the explicit give-up path (bounded retries).
"""
from __future__ import annotations

import contextvars
import functools
import re
import time

FAULT_NONE = "NONE"
FAULT_TIMEOUT = "TIMEOUT"
FAULT_TIMEOUT_PERSISTENT = "TIMEOUT_PERSISTENT"
FAULT_MALFORMED = "MALFORMED"
FAULT_MALFORMED_RESPONSE = "MALFORMED_RESPONSE"
FAULT_MALFORMED_PERSISTENT = "MALFORMED_PERSISTENT"

ALL_FAULTS = (
    FAULT_NONE,
    FAULT_TIMEOUT,
    FAULT_TIMEOUT_PERSISTENT,
    FAULT_MALFORMED,
    FAULT_MALFORMED_RESPONSE,
    FAULT_MALFORMED_PERSISTENT,
)

FAULT_SLEEP_S = 0.05  # "sleep briefly" before raising TimeoutError


class _FaultContextMeta(type):
    @property
    def current_fault(cls) -> str:
        return cls.get()

    @current_fault.setter
    def current_fault(cls, value: str) -> None:
        cls.set(value)


class FaultContext(metaclass=_FaultContextMeta):
    """Holds the fault directive for the current execution context."""

    _current: contextvars.ContextVar = contextvars.ContextVar(
        "current_fault", default=FAULT_NONE
    )

    @property
    def current_fault(self) -> str:
        return self.get()

    @current_fault.setter
    def current_fault(self, value: str) -> None:
        self.set(value)

    @classmethod
    def set(cls, fault: str):
        if fault not in ALL_FAULTS:
            raise ValueError(f"Unknown fault directive: {fault!r}")
        if fault == FAULT_MALFORMED_RESPONSE:
            fault = FAULT_MALFORMED
        return cls._current.set(fault)

    @classmethod
    def get(cls) -> str:
        return cls._current.get()

    @classmethod
    def reset(cls, token) -> None:
        cls._current.reset(token)


def _mangle(tool_name: str, payload: dict, persistent: bool) -> dict:
    """Corrupt a successful payload so it violates the tool's output schema.

    Transient (persistent=False): keys renamed / values re-typed, but the data is
    still in there — a schema-repair re-prompt can recover it.
    Persistent: the essential data is gone entirely — repair must give up.
    """
    if tool_name == "flight_search":
        if persistent:
            return {"msg": "success", "origin": payload["origin"]}
        return {
            "msg": "success",
            "origin": payload["origin"],
            "destination": payload["destination"],
            "dep_date": payload["date"],
            "carrier": payload["airline"],
            "fare_usd_str": f"{payload['price_usd']:.2f} USD",
        }
    if tool_name == "weather_lookup":
        if persistent:
            return {"msg": "success", "place": payload["location"]}
        return {
            "msg": "success",
            "place": payload["location"],
            "temp_str": f"{payload['temperature']:.0f} degrees",
            "unit_label": payload["unit"],
            "sky": payload["condition"],
        }
    if tool_name == "calendar_book":
        if persistent:
            return {"msg": "success", "title": payload["event_title"]}
        return {
            "msg": "success",
            "title": payload["event_title"],
            "when": payload["start_time"],
            "mins": payload["duration_minutes"],
            "ref": payload["booking_id"],
        }
    if tool_name == "unit_convert":
        if persistent:
            return {"msg": "success", "src": payload["from_unit"]}
        return {
            "msg": "success",
            "in": payload["value"],
            "amount": f"{payload['result']:.5f}",
            "src": payload["from_unit"],
            "dst": payload["to_unit"],
        }
    return payload


def inject_fault(func):
    """Decorator applied to every mock tool; reads FaultContext per call."""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        fault = FaultContext.get()
        if fault in (FAULT_TIMEOUT, FAULT_TIMEOUT_PERSISTENT):
            if fault == FAULT_TIMEOUT:
                FaultContext.set(FAULT_NONE)  # transient: consumed on first call
            time.sleep(FAULT_SLEEP_S)
            raise TimeoutError("Upstream service timed out")
        result = func(*args, **kwargs)
        if fault in (FAULT_MALFORMED, FAULT_MALFORMED_PERSISTENT):
            persistent = fault == FAULT_MALFORMED_PERSISTENT
            if not persistent:
                FaultContext.set(FAULT_NONE)
            return _mangle(func.__name__, result, persistent)
        return result

    return wrapper


def payload_float(raw: str) -> float:
    """Extract the first numeric token from a corrupted string value."""
    match = re.search(r"-?\d+(?:\.\d+)?", str(raw))
    if not match:
        raise ValueError(f"No number in {raw!r}")
    return float(match.group())


# Alias for plural decorator naming convention
inject_faults = inject_fault
