"""req-2-fault-injector: deterministic fault injection on the mock tools (no LLM)."""
import pytest
from pydantic import ValidationError

from src.faults import FaultContext
from src.schemas import WeatherLookupResult
from src.tools import calendar_book, flight_search, unit_convert, weather_lookup


def test_none_passthrough_matches_schema():
    payload = weather_lookup(location="Tokyo", unit="C")
    WeatherLookupResult.model_validate(payload)  # must not raise


def test_timeout_raises_timeout_error():
    token = FaultContext.set("TIMEOUT")
    try:
        with pytest.raises(TimeoutError):
            weather_lookup(location="Tokyo", unit="C")
    finally:
        FaultContext.reset(token)


def test_timeout_is_transient_then_normal():
    token = FaultContext.set("TIMEOUT")
    try:
        with pytest.raises(TimeoutError):
            flight_search(origin="JFK", destination="LHR", date="2026-10-10")
        # transient: the fault is consumed, the retry succeeds
        payload = flight_search(origin="JFK", destination="LHR", date="2026-10-10")
        assert payload["status"] == "ok"
    finally:
        FaultContext.reset(token)


def test_timeout_persistent_always_raises():
    token = FaultContext.set("TIMEOUT_PERSISTENT")
    try:
        for _ in range(2):
            with pytest.raises(TimeoutError):
                weather_lookup(location="Tokyo", unit="C")
    finally:
        FaultContext.reset(token)


def test_malformed_violates_output_schema():
    token = FaultContext.set("MALFORMED")
    try:
        payload = weather_lookup(location="Tokyo", unit="C")
        with pytest.raises(ValidationError):
            WeatherLookupResult.model_validate(payload)
        assert "temperature" not in payload  # schema-required data is renamed/retyped
    finally:
        FaultContext.reset(token)


def test_malformed_persistent_always_violates():
    token = FaultContext.set("MALFORMED_PERSISTENT")
    try:
        for _ in range(2):
            payload = unit_convert(value=5, from_unit="kg", to_unit="lbs")
            with pytest.raises(ValidationError):
                from src.schemas import UnitConversionResult

                UnitConversionResult.model_validate(payload)
    finally:
        FaultContext.reset(token)


def test_fault_context_rejects_unknown_directive():
    with pytest.raises(ValueError):
        FaultContext.set("GREMLINS")


def test_malformed_response_directive_violates_output_schema():
    token = FaultContext.set("MALFORMED_RESPONSE")
    try:
        payload = weather_lookup(location="Tokyo", unit="C")
        with pytest.raises(ValidationError):
            WeatherLookupResult.model_validate(payload)
        assert "temperature" not in payload
    finally:
        FaultContext.reset(token)


def test_fault_context_current_fault_property():
    original = FaultContext.current_fault
    try:
        FaultContext.current_fault = "TIMEOUT"
        assert FaultContext.current_fault == "TIMEOUT"
        assert FaultContext.get() == "TIMEOUT"
    finally:
        FaultContext.current_fault = original


def test_inject_faults_alias_is_available():
    from src.faults import inject_fault, inject_faults
    assert inject_faults is inject_fault

