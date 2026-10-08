"""Mock tool implementations, each wrapped by the Fault Injector.

The tools return static JSON dictionaries representing success; the decorator in
src/faults.py intercepts every call and may raise TimeoutError or corrupt the
returned payload according to FaultContext.
"""
from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel

from src.faults import inject_fault
from src.schemas import (
    CalendarBookingArgs,
    CalendarBookingResult,
    FlightSearchArgs,
    FlightSearchResult,
    UnitConversionArgs,
    UnitConversionResult,
    WeatherLookupArgs,
    WeatherLookupResult,
)


@inject_fault
def flight_search(origin: str, destination: str, date: str) -> dict:
    """Static flight-offer payload for the requested route/date."""
    return {
        "status": "ok",
        "origin": origin,
        "destination": destination,
        "date": date,
        "airline": "SkyLine",
        "price_usd": 431.5,
    }


@inject_fault
def calendar_book(event_title: str, start_time: str, duration_minutes: int) -> dict:
    """Static booking-confirmation payload."""
    return {
        "status": "ok",
        "event_title": event_title,
        "start_time": start_time,
        "duration_minutes": duration_minutes,
        "booking_id": "BK-7QZ1",
    }


@inject_fault
def weather_lookup(location: str, unit: str) -> dict:
    """Static weather payload."""
    return {
        "status": "ok",
        "location": location,
        "unit": unit,
        "temperature": 72.0,
        "condition": "Clear",
    }


_UNIT_TABLE = {
    ("kg", "lbs"): 2.20462,
    ("kilograms", "grams"): 1000.0,
    ("grams", "kilograms"): 0.001,
    ("miles", "kilometers"): 1.60934,
    ("inches", "cm"): 2.54,
    ("dollars", "euros"): 0.92,
    ("cups", "milliliters"): 240.0,
    ("ounces", "grams"): 28.3495,
}


@inject_fault
def unit_convert(value: float, from_unit: str, to_unit: str) -> dict:
    """Small deterministic conversion table."""
    factor = _UNIT_TABLE.get((from_unit.lower(), to_unit.lower()), 1.0)
    return {
        "status": "ok",
        "value": value,
        "from_unit": from_unit,
        "to_unit": to_unit,
        "result": round(value * factor, 5),
    }


@dataclass(frozen=True)
class ToolSpec:
    name: str
    func: callable
    args_model: type[BaseModel]
    result_model: type[BaseModel]
    description: str


TOOL_SPECS: dict[str, ToolSpec] = {
    spec.name: spec
    for spec in [
        ToolSpec(
            name="FlightSearch",
            func=flight_search,
            args_model=FlightSearchArgs,
            result_model=FlightSearchResult,
            description="Search flights. Required: origin (str), destination (str), date (ISO YYYY-MM-DD).",
        ),
        ToolSpec(
            name="CalendarBooking",
            func=calendar_book,
            args_model=CalendarBookingArgs,
            result_model=CalendarBookingResult,
            description="Book a calendar event. Required: event_title (str), start_time (ISO datetime), duration_minutes (int > 0).",
        ),
        ToolSpec(
            name="WeatherLookup",
            func=weather_lookup,
            args_model=WeatherLookupArgs,
            result_model=WeatherLookupResult,
            description="Look up weather. Required: location (str), unit (enum: 'C' or 'F').",
        ),
        ToolSpec(
            name="UnitConversion",
            func=unit_convert,
            args_model=UnitConversionArgs,
            result_model=UnitConversionResult,
            description="Convert units. Required: value (float), from_unit (str), to_unit (str).",
        ),
    ]
}
