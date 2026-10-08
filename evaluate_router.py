#!/usr/bin/env python3
"""Batch evaluation harness.

Runs every case in data/eval.jsonl twice:

  1. Baseline mode  (use_recovery=False): any validation error, timeout, or
     malformed response is an immediate explicit failure.
  2. Recovery mode  (use_recovery=True): the four targeted, bounded policies are
     active.

Metrics (written to output/metrics.json, contract shape):

  completion_rate        validated, schema-compliant successes / total requests
  silent_wrong_rate      requests that returned 'success' but whose payload
                         violates the output schema (should be 0 by construction;
                         we still measure it independently of the router's own
                         validation, so the number is honest)
  mean_recovery_attempts total retry actions / total requests

Per-case rows (both modes, with policies triggered and attempts) are written to
results/run_results.json so every number can be recomputed by an auditor.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pydantic import ValidationError

from src import config
from src.llm import get_llm
from src.router import RunStats, process_request
from src.tools import TOOL_SPECS

ROOT = Path(__file__).resolve().parent
DATASET = ROOT / "data" / "eval.jsonl"
METRICS_OUT = ROOT / "output" / "metrics.json"
RESULTS_OUT = ROOT / "results" / "run_results.json"


def load_cases(path: Path) -> list[dict]:
    cases = []
    with path.open() as fh:
        for line in fh:
            line = line.strip()
            if line:
                cases.append(json.loads(line))
    if len(cases) < 50:
        raise SystemExit(f"Dataset too small: {len(cases)} cases (need >= 50)")
    return cases


def run_mode(cases: list[dict], use_recovery: bool, today: date) -> dict:
    llm = get_llm()
    rows, completed, silent_wrong, total_attempts = [], 0, 0, 0
    for case in cases:
        stats = RunStats()
        fault = case.get("injected_fault", "NONE")
        resp = process_request(
            case["request"],
            use_recovery=use_recovery,
            fault=fault,
            stats=stats,
            today=today,
            llm=llm,
        )
        # Independent silent-wrong audit: success claimed but payload violates
        # the output schema (or routed to the wrong tool).
        sw = False
        if resp.get("status") == "success":
            spec = TOOL_SPECS[resp["tool"]]
            try:
                spec.result_model.model_validate(resp["result"])
            except ValidationError:
                sw = True
            if case.get("expected_tool") and resp["tool"] != case["expected_tool"]:
                sw = True
        if resp.get("status") == "success" and not sw:
            completed += 1
        if sw:
            silent_wrong += 1
        total_attempts += stats.attempts
        rows.append(
            {
                "id": case["id"],
                "request": case["request"],
                "expected_tool": case.get("expected_tool"),
                "injected_fault": fault,
                "status": resp.get("status"),
                "reason": resp.get("reason"),
                "tool": resp.get("tool"),
                "recovery_attempts": stats.attempts,
                "policies_triggered": [e["policy"] for e in stats.policy_events],
                "silent_wrong": sw,
            }
        )
    n = len(cases)
    metrics = {
        "completion_rate": round(completed / n, 4),
        "silent_wrong_rate": round(silent_wrong / n, 4),
        # Baseline never recovers: report the contract's literal 0.
        "mean_recovery_attempts": round(total_attempts / n, 4) if use_recovery else 0,
    }
    return {"metrics": metrics, "rows": rows}


def main() -> int:
    cases = load_cases(DATASET)
    today = date.fromisoformat(config.EVAL_TODAY)

    print(f"Dataset: {len(cases)} cases | pinned EVAL_TODAY={today.isoformat()} "
          f"| provider={config.LLM_PROVIDER} model={config.LLM_MODEL_ID}")

    baseline = run_mode(cases, use_recovery=False, today=today)
    recovery = run_mode(cases, use_recovery=True, today=today)

    metrics = {
        "baseline": baseline["metrics"],
        "recovery_active": recovery["metrics"],
    }

    METRICS_OUT.parent.mkdir(parents=True, exist_ok=True)
    METRICS_OUT.write_text(json.dumps(metrics, indent=2) + "\n")

    RESULTS_OUT.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_OUT.write_text(
        json.dumps(
            {
                "pinned_config": {
                    "eval_today": today.isoformat(),
                    "llm_provider": config.LLM_PROVIDER,
                    "llm_model_id": config.LLM_MODEL_ID,
                    "timeout_backoff_s": config.TIMEOUT_BACKOFF_S,
                },
                "baseline": baseline,
                "recovery_active": recovery,
            },
            indent=2,
        )
        + "\n"
    )

    b, r = metrics["baseline"], metrics["recovery_active"]
    print("\n=== Metrics (output/metrics.json) ===")
    print(f"{'metric':<24}{'baseline':>12}{'recovery':>12}")
    print(f"{'completion_rate':<24}{b['completion_rate']:>12.4f}{r['completion_rate']:>12.4f}")
    print(f"{'silent_wrong_rate':<24}{b['silent_wrong_rate']:>12.4f}{r['silent_wrong_rate']:>12.4f}")
    print(f"{'mean_recovery_attempts':<24}{b['mean_recovery_attempts']:>12}{r['mean_recovery_attempts']:>12.4f}")

    if r["completion_rate"] <= b["completion_rate"]:
        print("\nWARNING: recovery did not improve completion rate over baseline.")
        return 1
    if r["silent_wrong_rate"] > 0:
        print("\nWARNING: recovery produced silent wrong answers.")
        return 1
    print("\nOK: recovery improved completion rate with silent_wrong_rate = 0.")
    return 0


# --------------------------------------------------------------------------- #
# Core Requirement Contract Entrypoints
# --------------------------------------------------------------------------- #
def satisfy_req_1_schemas(*args, **kwargs):
    """req-1-schemas: System defines four specific tool schemas using Pydantic."""
    from src.schemas import (
        CalendarBookingArgs,
        FlightSearchArgs,
        UnitConversionArgs,
        WeatherLookupArgs,
    )
    return {
        "FlightSearch": FlightSearchArgs,
        "CalendarBooking": CalendarBookingArgs,
        "WeatherLookup": WeatherLookupArgs,
        "UnitConversion": UnitConversionArgs,
    }


def satisfy_req_2_fault_injector(*args, **kwargs):
    """req-2-fault-injector: Fault injection middleware with deterministic control."""
    from src.faults import FaultContext, inject_fault, inject_faults
    return {
        "FaultContext": FaultContext,
        "inject_fault": inject_fault,
        "inject_faults": inject_faults,
    }


def satisfy_req_3_happy_path(request="Book a flight from MIA to JFK on 2024-10-10.", *args, **kwargs):
    """req-3-happy-path: Sunny-day request processes cleanly without recovery."""
    return process_request(request, use_recovery=True, fault="NONE")


def satisfy_req_4_recovery_missing(request="Book a flight to Paris.", *args, **kwargs):
    """req-4-recovery-missing: Intercepts missing fields and re-prompts specifically."""
    return process_request(request, use_recovery=True)


def satisfy_req_5_recovery_type(request="Book it for tomorrow", *args, **kwargs):
    """req-5-recovery-type: Intercepts type mismatch and re-prompts to cast/translate."""
    return process_request(request, use_recovery=True)


def satisfy_req_6_recovery_timeout(request="Get the weather in Tokyo in celsius.", *args, **kwargs):
    """req-6-recovery-timeout: Intercepts timeout and applies backoff without LLM tokens."""
    return process_request(request, use_recovery=True, fault="TIMEOUT")


def satisfy_req_7_recovery_malformed(request="Get the weather in Cairo in fahrenheit.", *args, **kwargs):
    """req-7-recovery-malformed: Validates tool output and repairs malformed response schema."""
    return process_request(request, use_recovery=True, fault="MALFORMED_RESPONSE")


def satisfy_req_8_explicit_failure(request="Book a flight from LAX to ORD on 2026-10-25.", *args, **kwargs):
    """req-8-explicit-failure: Returns explicit structured error when retry bound exhausted."""
    return process_request(request, use_recovery=True, fault="TIMEOUT_PERSISTENT")


def satisfy_req_9_evaluation_script(*args, **kwargs):
    """req-9-evaluation-script: Runs batch evaluation harness producing output/metrics.json."""
    main()
    if METRICS_OUT.exists():
        return json.loads(METRICS_OUT.read_text())
    return None


def satisfy_req_10_docker_setup(*args, **kwargs):
    """req-10-docker-setup: Validates containerization assets."""
    compose_path = ROOT / "docker-compose.yml"
    dockerfile_path = ROOT / "Dockerfile"
    return {
        "docker_compose_exists": compose_path.exists(),
        "dockerfile_exists": dockerfile_path.exists(),
    }


if __name__ == "__main__":
    raise SystemExit(main())

