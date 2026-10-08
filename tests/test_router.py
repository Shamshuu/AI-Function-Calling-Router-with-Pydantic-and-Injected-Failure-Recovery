"""Router behavior tests: req-3 through req-8, each policy distinct and bounded."""
from datetime import date

from src.llm import OfflineLLM
from src.router import RunStats, process_request

TODAY = date(2026, 10, 3)


def stats_run(request, use_recovery=True, fault="NONE"):
    stats = RunStats()
    llm = OfflineLLM()
    resp = process_request(
        request, use_recovery=use_recovery, fault=fault, stats=stats, today=TODAY, llm=llm
    )
    return resp, stats, llm


# ------------------------------- req-3 ------------------------------------- #
def test_happy_path_no_recovery_triggered():
    resp, stats, _ = stats_run("Book a flight from MIA to JFK on 2024-10-10.")
    assert resp["status"] == "success"
    assert resp["attempts"] == 0
    assert stats.policy_events == []
    assert resp["result"]["origin"] == "MIA"
    assert resp["result"]["date"] == "2024-10-10"


# ------------------------------- req-4 ------------------------------------- #
def test_missing_field_recovery_triggers_once_and_succeeds():
    resp, stats, _ = stats_run("Book a flight to Paris.")
    assert resp["status"] == "success"
    assert [e["policy"] for e in stats.policy_events] == ["missing_field"]
    assert resp["attempts"] == 1
    # deterministic targeted fill: origin inferred, date resolved from pinned today
    assert resp["result"]["destination"] == "Paris"
    assert resp["result"]["date"] == "2026-10-04"


def test_missing_field_recovery_bounded():
    # 'Schedule' with no time info at all and no fillable duration phrase
    resp, stats, _ = stats_run("Schedule 'Standup'.")
    # start_time missing -> filled; event_title present; duration missing -> filled 60
    assert resp["status"] == "success"
    assert [e["policy"] for e in stats.policy_events] == ["missing_field"]
    assert resp["result"]["duration_minutes"] == 60


# ------------------------------- req-5 ------------------------------------- #
def test_type_error_recovery_triggers_and_succeeds():
    resp, stats, _ = stats_run("Book a flight from JFK to LHR tomorrow.")
    assert resp["status"] == "success"
    assert [e["policy"] for e in stats.policy_events] == ["type_error"]
    assert resp["attempts"] == 1
    assert resp["result"]["date"] == "2026-10-04"  # resolved from pinned 2026-10-03


def test_type_error_duration_phrase_recovered():
    resp, stats, _ = stats_run("Schedule 'Board Briefing' on 2026-10-09 at 12:00 for one hour.")
    assert resp["status"] == "success"
    assert [e["policy"] for e in stats.policy_events] == ["type_error"]
    assert resp["result"]["duration_minutes"] == 60


# ------------------------------- req-6 ------------------------------------- #
def test_timeout_retry_uses_no_llm_tokens():
    resp, stats, llm = stats_run("Get the weather in Tokyo in celsius.", fault="TIMEOUT")
    assert resp["status"] == "success"
    assert [e["policy"] for e in stats.policy_events] == ["timeout"]
    assert resp["attempts"] == 1
    # exactly one LLM call (tool selection); the timeout retry spent zero tokens
    assert llm.call_count == 1


def test_timeout_persistent_gives_up_explicitly():
    resp, stats, _ = stats_run("Book a flight from LAX to ORD on 2026-10-25.", fault="TIMEOUT_PERSISTENT")
    assert resp == {"status": "error", "reason": "timeout_unrecoverable"}
    assert stats.attempts == 1  # bounded: exactly one retry


# ------------------------------- req-7 ------------------------------------- #
def test_malformed_response_repaired():
    resp, stats, _ = stats_run("Get the weather in Cairo in fahrenheit.", fault="MALFORMED")
    assert resp["status"] == "success"
    assert [e["policy"] for e in stats.policy_events] == ["schema_repair"]
    assert resp["result"]["temperature"] == 72.0
    assert resp["result"]["unit"] == "F"


def test_malformed_unrepairable_gives_up_explicitly():
    resp, _, _ = stats_run("Get the weather in Nairobi in celsius.", fault="MALFORMED_PERSISTENT")
    assert resp == {"status": "error", "reason": "schema_repair_unrecoverable"}


# ------------------------------- req-8 ------------------------------------- #
def test_explicit_failure_shape_is_exact():
    resp, _, _ = stats_run("Book a flight from LAX to ORD on 2026-10-25.", fault="TIMEOUT_PERSISTENT")
    assert set(resp.keys()) == {"status", "reason"}


def test_baseline_mode_fails_immediately_without_recovery():
    resp, stats, _ = stats_run("Book a flight from LAX to ORD on 2026-10-25.",
                               use_recovery=False, fault="TIMEOUT_PERSISTENT")
    assert resp == {"status": "error", "reason": "timeout_unrecoverable"}
    assert stats.attempts == 0

    resp, stats, _ = stats_run("Book a flight to Paris.", use_recovery=False)
    assert resp == {"status": "error", "reason": "missing_field_unrecoverable"}
    assert stats.attempts == 0

    resp, _, _ = stats_run("Book a flight from JFK to LHR tomorrow.", use_recovery=False)
    assert resp == {"status": "error", "reason": "type_error_unrecoverable"}

    resp, _, _ = stats_run("Get the weather in Tokyo in celsius.", use_recovery=False, fault="MALFORMED")
    assert resp == {"status": "error", "reason": "schema_repair_unrecoverable"}


def test_type_error_book_it_for_tomorrow():
    """req-5 verification example: 'Book it for tomorrow' triggers type_error and succeeds."""
    resp, stats, _ = stats_run("Book it for tomorrow")
    assert resp["status"] == "success"
    assert [e["policy"] for e in stats.policy_events] == ["type_error"]
    assert resp["attempts"] == 1
    assert resp["result"]["date"] == "2026-10-04"


def test_malformed_response_directive_in_router():
    """req-7 verification: fault='MALFORMED_RESPONSE' triggers schema_repair."""
    resp, stats, _ = stats_run("Get the weather in Cairo in fahrenheit.", fault="MALFORMED_RESPONSE")
    assert resp["status"] == "success"
    assert [e["policy"] for e in stats.policy_events] == ["schema_repair"]
    assert resp["result"]["temperature"] == 72.0


def test_fault_configured_via_context_is_respected():
    """req-2: Router accepts fault configuration set via FaultContext without parameter."""
    from src.faults import FaultContext

    original = FaultContext.current_fault
    try:
        FaultContext.current_fault = "TIMEOUT"
        stats = RunStats()
        resp = process_request("Get the weather in Tokyo in celsius.", stats=stats)
        assert resp["status"] == "success"
        assert [e["policy"] for e in stats.policy_events] == ["timeout"]
    finally:
        FaultContext.current_fault = original

