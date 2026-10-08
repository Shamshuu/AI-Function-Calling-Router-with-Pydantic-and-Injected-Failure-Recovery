"""Tool input/output schemas — the Pydantic validation boundary.

Four tools, each with a Pydantic model for its required arguments and a Pydantic
model for the exact response shape the tool is expected to return.
"""
from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class TemperatureUnit(str, Enum):
    C = "C"
    F = "F"


# --------------------------------------------------------------------------- #
# Input schemas (validated before any tool executes)
# --------------------------------------------------------------------------- #
class FlightSearchArgs(BaseModel):
    origin: str = Field(min_length=3, max_length=40)
    destination: str = Field(min_length=3, max_length=40)
    date: date  # ISO-8601 YYYY-MM-DD


class CalendarBookingArgs(BaseModel):
    event_title: str = Field(min_length=1)
    start_time: datetime
    duration_minutes: int = Field(gt=0, le=24 * 60)


class WeatherLookupArgs(BaseModel):
    location: str = Field(min_length=2)
    unit: TemperatureUnit


class UnitConversionArgs(BaseModel):
    value: float
    from_unit: str = Field(min_length=1)
    to_unit: str = Field(min_length=1)


# Direct tool aliases for input argument schemas (satisfies req-1-schemas)
FlightSearch = FlightSearchArgs
CalendarBooking = CalendarBookingArgs
WeatherLookup = WeatherLookupArgs
UnitConversion = UnitConversionArgs


# --------------------------------------------------------------------------- #
# Output schemas (validated on every tool response; drives schema repair)
# --------------------------------------------------------------------------- #
class FlightSearchResult(BaseModel):
    origin: str
    destination: str
    date: date
    airline: str
    price_usd: float
    status: Literal["ok"]


class CalendarBookingResult(BaseModel):
    event_title: str
    start_time: datetime
    duration_minutes: int
    booking_id: str
    status: Literal["ok"]


class WeatherLookupResult(BaseModel):
    location: str
    unit: TemperatureUnit
    temperature: float
    condition: str
    status: Literal["ok"]


class UnitConversionResult(BaseModel):
    value: float
    from_unit: str
    to_unit: str
    result: float
    status: Literal["ok"]


# Failure classes -> the "<failure_class>_unrecoverable" reason strings.
FAILURE_CLASSES = ("missing_field", "type_error", "timeout", "schema_repair")


def classify_validation_error(exc: Exception) -> str:
    """Map a pydantic.ValidationError to a recovery policy class.

    'missing' if any error is a missing required field, otherwise 'type_error'
    (covers wrong types, bad enum values, parse failures, out-of-range ints).
    """
    for err in exc.errors():  # type: ignore[attr-defined]
        if err.get("type") == "missing":
            return "missing_field"
    return "type_error"
