"""req-1-schemas: Pydantic tool schemas accept valid data and reject invalid data."""
import pytest
from datetime import date, datetime
from pydantic import ValidationError

from src.schemas import (
    CalendarBookingArgs,
    FlightSearchArgs,
    TemperatureUnit,
    UnitConversionArgs,
    WeatherLookupArgs,
    classify_validation_error,
)


def test_flight_search_valid():
    args = FlightSearchArgs(origin="JFK", destination="LHR", date="2026-10-10")
    assert args.date == date(2026, 10, 10)


def test_flight_search_missing_date():
    with pytest.raises(ValidationError) as exc:
        FlightSearchArgs(origin="JFK", destination="LHR")
    assert classify_validation_error(exc.value) == "missing_field"


def test_flight_search_bad_date_type():
    with pytest.raises(ValidationError) as exc:
        FlightSearchArgs(origin="JFK", destination="LHR", date="tomorrow")
    assert classify_validation_error(exc.value) == "type_error"


def test_calendar_booking_valid():
    args = CalendarBookingArgs(
        event_title="Standup", start_time="2026-10-05 10:00", duration_minutes=45
    )
    assert args.start_time == datetime(2026, 10, 5, 10, 0)
    assert args.duration_minutes == 45


def test_calendar_booking_missing_start_time():
    with pytest.raises(ValidationError) as exc:
        CalendarBookingArgs(event_title="Standup", duration_minutes=45)
    assert classify_validation_error(exc.value) == "missing_field"


def test_calendar_booking_bad_duration():
    with pytest.raises(ValidationError) as exc:
        CalendarBookingArgs(event_title="Standup", start_time="2026-10-05 10:00", duration_minutes=0)
    assert classify_validation_error(exc.value) == "type_error"


def test_weather_lookup_valid_units():
    assert WeatherLookupArgs(location="Tokyo", unit="C").unit is TemperatureUnit.C
    assert WeatherLookupArgs(location="Tokyo", unit="F").unit is TemperatureUnit.F


def test_weather_lookup_missing_unit():
    with pytest.raises(ValidationError) as exc:
        WeatherLookupArgs(location="Tokyo")
    assert classify_validation_error(exc.value) == "missing_field"


def test_weather_lookup_invalid_unit():
    with pytest.raises(ValidationError) as exc:
        WeatherLookupArgs(location="Tokyo", unit="kelvin")
    assert classify_validation_error(exc.value) == "type_error"


def test_unit_conversion_valid():
    args = UnitConversionArgs(value=5, from_unit="kg", to_unit="lbs")
    assert args.value == 5.0


def test_unit_conversion_bad_value_type():
    with pytest.raises(ValidationError) as exc:
        UnitConversionArgs(value="five", from_unit="kg", to_unit="lbs")
    assert classify_validation_error(exc.value) == "type_error"


def test_unit_conversion_missing_field():
    with pytest.raises(ValidationError) as exc:
        UnitConversionArgs(value=3, from_unit="kg")
    assert classify_validation_error(exc.value) == "missing_field"


def test_direct_tool_model_aliases():
    from src.schemas import CalendarBooking, FlightSearch, UnitConversion, WeatherLookup
    assert issubclass(FlightSearch, FlightSearchArgs)
    assert issubclass(CalendarBooking, CalendarBookingArgs)
    assert issubclass(WeatherLookup, WeatherLookupArgs)
    assert issubclass(UnitConversion, UnitConversionArgs)

