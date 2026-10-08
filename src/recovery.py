"""Targeted recovery strategies, documented as first-class policy objects.

Each policy in src/router.py is a DISTINCT code path — not one generic retry:

1. missing_field policy (req-4)
   Trigger: pydantic.ValidationError with type == "missing".
   Action:  tiny targeted re-prompt per missing field —
            "The tool [ToolName] is missing the field [FieldName]. Based on the
            user's original request '[Request]', what should this value be?
            Return only the value."
            The full system prompt / history is NOT re-sent. The value is merged
            into the arguments and the tool execution is retried once.

2. type_error policy (req-5)
   Trigger: pydantic.ValidationError with a type/parse/enum error.
   Action:  "The field [FieldName] requires format [Format], but you provided
            [BadValue]. Translate this into the correct format."
            The corrected value is merged and execution retried once.

3. timeout policy (req-6)
   Trigger: TimeoutError raised by the Fault Injector.
   Action:  wait TIMEOUT_BACKOFF_S and re-invoke the same Python tool function
            directly. The LLM is NOT invoked — zero tokens on timeout retries.

4. schema_repair policy (req-7)
   Trigger: tool payload fails validation against the tool's Output model.
   Action:  "The tool returned this malformed payload: [Payload]. Extract the
            data to match this JSON schema: [Schema]." Re-validate the repaired
            payload once.

Bound: each policy has exactly ONE retry. On the second failure the router
returns {"status": "error", "reason": "<class>_unrecoverable"} (req-8) — an
explicit give-up, never a fabricated success.
"""

RETRY_BOUND = 1  # strict: every policy retries at most once

POLICY_PROMPTS = {
    "missing_field": (
        "The tool [ToolName] is missing the field [FieldName]. Based on the user's "
        "original request '[Request]', what should this value be? Return only the value."
    ),
    "type_error": (
        "The field [FieldName] requires format [Format], but you provided [BadValue]. "
        "Translate this into the correct format."
    ),
    "schema_repair": (
        "The tool returned this malformed payload: [Payload]. Extract the data to "
        "match this JSON schema: [Schema]."
    ),
}
