"""Routing core: NL request -> LLM tool selection -> Pydantic validation ->
fault-injected execution -> output-schema validation, with a distinct, bounded
recovery policy per failure class.

Bounded retry policy (strict): every recovery policy gets exactly ONE attempt.
If it fails a second time, the router returns an explicit failure object:
    {"status": "error", "reason": "<failure_class>_unrecoverable"}
It never returns a fabricated success and never leaks a stack trace.

Policies (src/recovery.py documents each):
    missing_field  -> tiny targeted re-prompt for ONLY the missing field(s)
    type_error     -> re-prompt to translate the bad value into the required format
    timeout        -> system-level backoff + direct Python retry, zero LLM tokens
    schema_repair  -> re-prompt to extract the corrupted payload into the output schema
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date, datetime

from pydantic import BaseModel, ValidationError

from src import config
from src.faults import FaultContext
from src.llm import BaseLLM, get_llm
from src.schemas import classify_validation_error
from src.tools import TOOL_SPECS, ToolSpec


@dataclass
class RunStats:
    """Per-request accounting used by the evaluation harness and tests."""

    recovery_attempts: int = 0
    policy_events: list = field(default_factory=list)

    @property
    def attempts(self) -> int:
        return self.recovery_attempts

    def record(self, policy: str, detail: dict) -> None:
        self.recovery_attempts += 1
        self.policy_events.append({"policy": policy, **detail})


def _fail(reason: str) -> dict:
    """Explicit, structured give-up. Never a fabricated success, never a trace."""
    return {"status": "error", "reason": reason}


def _validate(model: type[BaseModel], args: dict):
    try:
        return model.model_validate(args)
    except ValidationError as exc:
        return exc


def _missing_fields(exc: ValidationError) -> list[str]:
    return [e["loc"][0] for e in exc.errors() if e.get("type") == "missing" and e.get("loc")]


def _type_error_fields(exc: ValidationError, raw_args: dict) -> list[tuple[str, object]]:
    seen, out = set(), []
    for e in exc.errors():
        if e.get("type") == "missing" or not e.get("loc"):
            continue
        name = e["loc"][0]
        if name not in seen:
            seen.add(name)
            out.append((name, raw_args.get(name)))
    return out


def _tool_kwargs(model: BaseModel) -> dict:
    return {
        k: v.isoformat() if isinstance(v, (date, datetime)) else v
        for k, v in model.model_dump().items()
    }


def process_request(
    request: str,
    use_recovery: bool = True,
    fault: str | None = None,
    stats: RunStats | None = None,
    today: date | None = None,
    llm: BaseLLM | None = None,
) -> dict:
    """Route one natural-language request through the full pipeline.

    Returns a standardized success dict or the explicit error dict
    {"status": "error", "reason": "<failure_class>_unrecoverable"}.
    """
    stats = stats or RunStats()
    today = today or date.fromisoformat(config.EVAL_TODAY)
    llm = llm or get_llm()
    if fault is not None:
        token = FaultContext.set(fault)
        need_reset = True
    else:
        token = None
        need_reset = False
    try:
        # Step 1: LLM selects the tool and extracts raw arguments.
        selection = llm.select_tool(request)
        if selection is None:
            return _fail("tool_selection_unrecoverable")
        tool_name, raw_args = selection
        spec: ToolSpec = TOOL_SPECS[tool_name]

        # Step 2: Pydantic boundary on the arguments.
        validated = _validate(spec.args_model, raw_args)
        if isinstance(validated, ValidationError):
            failure_class = classify_validation_error(validated)
            if not use_recovery:
                return _fail(f"{failure_class}_unrecoverable")
            # Targeted recovery (bounded: exactly one retry of execution).
            stats.record(failure_class, {"tool": tool_name, "fields": _error_field_names(validated)})
            args2 = dict(raw_args)
            if failure_class == "missing_field":
                for field_name in _missing_fields(validated):
                    value = llm.fill_missing_field(request, tool_name, field_name, today)
                    if value is None:
                        return _fail("missing_field_unrecoverable")
                    args2[field_name] = value
            else:
                for field_name, bad_value in _type_error_fields(validated, raw_args):
                    value = llm.correct_type(tool_name, field_name, bad_value, today)
                    if value is None:
                        return _fail("type_error_unrecoverable")
                    args2[field_name] = value
            validated = _validate(spec.args_model, args2)
            if isinstance(validated, ValidationError):
                return _fail(f"{failure_class}_unrecoverable")

        kwargs = _tool_kwargs(validated)

        # Step 3: execute through the Fault Injector.
        try:
            payload = spec.func(**kwargs)
        except TimeoutError:
            if not use_recovery:
                return _fail("timeout_unrecoverable")
            # System-level policy: backoff and retry the exact same call.
            # No LLM invocation — zero tokens spent on a timeout retry.
            stats.record("timeout", {"tool": tool_name, "backoff_s": config.TIMEOUT_BACKOFF_S})
            time.sleep(config.TIMEOUT_BACKOFF_S)
            try:
                payload = spec.func(**kwargs)
            except TimeoutError:
                return _fail("timeout_unrecoverable")

        # Step 4: output-schema validation (catches MALFORMED responses).
        try:
            out = spec.result_model.model_validate(payload)
        except ValidationError:
            if not use_recovery:
                return _fail("schema_repair_unrecoverable")
            stats.record("schema_repair", {"tool": tool_name})
            repaired = llm.repair_schema(tool_name, payload)
            if repaired is None:
                return _fail("schema_repair_unrecoverable")
            try:
                out = spec.result_model.model_validate(repaired)
            except ValidationError:
                return _fail("schema_repair_unrecoverable")

        return {
            "status": "success",
            "tool": tool_name,
            "result": out.model_dump(mode="json"),
            "attempts": stats.attempts,
        }
    finally:
        if need_reset and token is not None:
            FaultContext.reset(token)


def _error_field_names(exc: ValidationError) -> list[str]:
    names = []
    for e in exc.errors():
        if e.get("loc"):
            names.append(e["loc"][0])
    return names
