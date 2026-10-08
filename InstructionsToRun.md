# Step-by-Step Guide to Run & Test the AI Function-Calling Router

This guide provides end-to-end instructions for running, testing, and evaluating the **AI Function-Calling Router with Pydantic & Failure Recovery**.

Everything runs **100% locally and offline by default** using deterministic heuristics—no external API keys or cloud services are needed unless you deliberately configure one.

---

## Table of Contents
1. [Prerequisites & Initial Setup](#1-prerequisites--initial-setup)
2. [Step-by-Step Functional Walkthrough](#2-step-by-step-functional-walkthrough)
   - [Step 2.1: Happy Path (Clean Request)](#step-21-happy-path-clean-request)
   - [Step 2.2: Recovery from Missing Fields](#step-22-recovery-from-missing-fields)
   - [Step 2.3: Recovery from Wrong Formats / Types](#step-23-recovery-from-wrong-formats--types)
   - [Step 2.4: Recovery from Upstream System Timeouts](#step-24-recovery-from-upstream-system-timeouts)
   - [Step 2.5: Recovery from Malformed Tool Responses (Schema Repair)](#step-25-recovery-from-malformed-tool-responses-schema-repair)
   - [Step 2.6: Explicit Give-Up on Persistent Failures](#step-26-explicit-give-up-on-persistent-failures)
   - [Step 2.7: Side-by-Side Comparison: Baseline vs. Recovery](#step-27-side-by-side-comparison-baseline-vs-recovery)
3. [Running the Full Test Suite (`pytest`)](#3-running-the-full-test-suite-pytest)
4. [Running the Batch Evaluation Benchmark (`evaluate_router.py`)](#4-running-the-batch-evaluation-benchmark-evaluate_routerpy)
5. [Running with Docker Compose (1 Command)](#5-running-with-docker-compose-1-command)
6. [Inspecting Output Artifacts](#6-inspecting-output-artifacts)
7. [Optional: Connecting a Real LLM (OpenAI / Ollama)](#7-optional-connecting-a-real-llm-openai--ollama)

---

## 1. Prerequisites & Initial Setup

### Requirements:
- Python 3.10+ installed
- Git
- (Optional) Docker & Docker Compose

### Clone and Environment Setup:

Open your terminal in the project directory:

```bash
# 1. Navigate to the project root
cd /home/shamshu/GPP/Week37/AI-Function-Calling-Router-with-Pydantic-and-Injected-Failure-Recovery

# 2. Create a clean virtual environment
python3 -m venv .venv

# 3. Activate the virtual environment
source .venv/bin/activate

# 4. Install the required dependencies
pip install -r requirements.txt
```

Verify that the environment is set up properly:
```bash
python -c "import pydantic, openai, pytest; print('Environment ready!')"
```

---

## 2. Step-by-Step Functional Walkthrough

Each step below can be run directly from your terminal using Python one-liners to test and observe each mechanism in isolation.

---

### Step 2.1: Happy Path (Clean Request)
> **Goal:** Verify that a standard request with all necessary details succeeds on the first try without triggering any recovery policies (`attempts == 0`).

Run in your terminal:
```bash
python -c '
from src.router import process_request, RunStats

stats = RunStats()
query = "Book a flight from MIA to JFK on 2024-10-10."
response = process_request(query, stats=stats)

print("Status:", response["status"])
print("Tool Selected:", response["tool"])
print("Recovery Attempts:", response["attempts"])
print("Result Data:", response["result"])
'
```

**Expected Output:**
```
Status: success
Tool Selected: FlightSearch
Recovery Attempts: 0
Result Data: {'status': 'ok', 'origin': 'MIA', 'destination': 'JFK', 'date': '2024-10-10', 'airline': 'SkyLine', 'price_usd': 431.5}
```

---

### Step 2.2: Recovery from Missing Fields
> **Goal:** Test what happens when the user request omits required information (e.g. asking to *"Book a flight to Paris"* without providing a departure date or origin airport).
>
> **Mechanism:** Pydantic catches `type="missing"`. The router triggers the `missing_field` recovery policy, generates a targeted prompt asking *only* for the missing data, merges it, and executes the tool.

Run in your terminal:
```bash
python -c '
from src.router import process_request, RunStats

stats = RunStats()
query = "Book a flight to Paris."
response = process_request(query, stats=stats)

print("Status:", response["status"])
print("Policies Triggered:", [e["policy"] for e in stats.policy_events])
print("Recovery Attempts:", response["attempts"])
print("Origin Airport:", response["result"]["origin"])
print("Destination Airport:", response["result"]["destination"])
print("Inferred Date:", response["result"]["date"])
'
```

**Expected Output:**
```
Status: success
Policies Triggered: ['missing_field']
Recovery Attempts: 1
Origin Airport: JFK
Destination Airport: Paris
Inferred Date: 2026-10-04
```

---

### Step 2.3: Recovery from Wrong Formats / Types
> **Goal:** Test what happens when the AI provides loose, conversational values (like `"tomorrow"`, `"next Tuesday"`, or `"one hour"`) instead of strict ISO dates or integers.
>
> **Mechanism:** Pydantic raises a `ValidationError` of type `type_error`. The router triggers the `type_error` policy, translates the phrase to standard format (e.g. `"tomorrow"` ➔ `"2026-10-04"`), and retries.

Run in your terminal:
```bash
python -c '
from src.router import process_request, RunStats

stats = RunStats()
query = "Book it for tomorrow"
response = process_request(query, stats=stats)

print("Status:", response["status"])
print("Policies Triggered:", [e["policy"] for e in stats.policy_events])
print("Recovery Attempts:", response["attempts"])
print("Converted ISO Date:", response["result"]["date"])
'
```

**Expected Output:**
```
Status: success
Policies Triggered: ['type_error']
Recovery Attempts: 1
Converted ISO Date: 2026-10-04
```

---

### Step 2.4: Recovery from Upstream System Timeouts
> **Goal:** Verify that when an external API times out (simulated via `fault="TIMEOUT"`), the system recovers without invoking the LLM or wasting AI tokens.
>
> **Mechanism:** Catch `TimeoutError` from the fault injector, wait `0.1s` (system backoff), and retry the tool call directly in Python.

Run in your terminal:
```bash
python -c '
from src.router import process_request, RunStats
from src.llm import get_llm

llm = get_llm()
stats = RunStats()
query = "Get the weather in Tokyo in celsius."

# Inject a transient timeout
response = process_request(query, fault="TIMEOUT", stats=stats, llm=llm)

print("Status:", response["status"])
print("Policies Triggered:", [e["policy"] for e in stats.policy_events])
print("Total LLM Calls:", llm.call_count)
print("Attempts:", response["attempts"])
print("Weather Result:", response["result"])
'
```

**Expected Output:**
```
Status: success
Policies Triggered: ['timeout']
Total LLM Calls: 1
Attempts: 1
Weather Result: {'status': 'ok', 'location': 'Tokyo', 'unit': 'C', 'temperature': 72.0, 'condition': 'Clear'}
```
*(Notice: `Total LLM Calls: 1` proves zero additional LLM tokens were spent on the timeout retry).*

---

### Step 2.5: Recovery from Malformed Tool Responses (Schema Repair)
> **Goal:** Test when an API returns unexpected or corrupted dictionary keys (e.g. `{temp_str: "72 degrees", place: "Cairo"}` instead of `{temperature: 72.0, location: "Cairo"}`).
>
> **Mechanism:** Output schema validation catches the invalid response shape, prompts the model to extract and map the fields into the clean output schema, and re-validates.

Run in your terminal:
```bash
python -c '
from src.router import process_request, RunStats

stats = RunStats()
query = "Get the weather in Cairo in fahrenheit."

# Inject a malformed tool response
response = process_request(query, fault="MALFORMED_RESPONSE", stats=stats)

print("Status:", response["status"])
print("Policies Triggered:", [e["policy"] for e in stats.policy_events])
print("Attempts:", response["attempts"])
print("Repaired Result:", response["result"])
'
```

**Expected Output:**
```
Status: success
Policies Triggered: ['schema_repair']
Attempts: 1
Repaired Result: {'status': 'ok', 'location': 'Cairo', 'unit': 'F', 'temperature': 72.0, 'condition': 'Clear'}
```

---

### Step 2.6: Explicit Give-Up on Persistent Failures
> **Goal:** Verify that when retries are exhausted (1 retry bound), the router gives up cleanly with an explicit error code instead of hallucinating fake success data or crashing with a stack trace.

Run in your terminal:
```bash
python -c '
from src.router import process_request

# Inject a persistent timeout (fails even after retry)
response = process_request("Book a flight from LAX to ORD on 2026-10-25.", fault="TIMEOUT_PERSISTENT")

print("Response JSON:", response)
'
```

**Expected Output:**
```
Response JSON: {'status': 'error', 'reason': 'timeout_unrecoverable'}
```

---

### Step 2.7: Side-by-Side Comparison: Baseline vs. Recovery
> **Goal:** Directly observe the difference between a naive router (`use_recovery=False`) and the targeted recovery router (`use_recovery=True`).

Run in your terminal:
```bash
python -c '
from src.router import process_request

prompt = "Book a flight to Paris."

# 1. Baseline Mode: Any validation issue fails immediately
baseline = process_request(prompt, use_recovery=False)
print("Baseline Mode (No Recovery):", baseline)

# 2. Recovery Mode: Self-healing policies active
recovery = process_request(prompt, use_recovery=True)
print("Recovery Mode (Active):     ", recovery["status"], "-> Destination:", recovery["result"]["destination"], "| Date:", recovery["result"]["date"])
'
```

**Expected Output:**
```
Baseline Mode (No Recovery): {'status': 'error', 'reason': 'missing_field_unrecoverable'}
Recovery Mode (Active):      success -> Destination: Paris | Date: 2026-10-04
```

---

## 3. Running the Full Test Suite (`pytest`)

To run all 37 automated contract and unit tests:

```bash
pytest -v
```

### What these tests cover:
- **`tests/test_schemas.py`**: Validates input models (`FlightSearchArgs`, `CalendarBookingArgs`, etc.) and output models, checking proper `ValidationError` classification.
- **`tests/test_faults.py`**: Tests fault injection directives (`NONE`, `TIMEOUT`, `MALFORMED_RESPONSE`, `TIMEOUT_PERSISTENT`, `MALFORMED_PERSISTENT`).
- **`tests/test_router.py`**: Tests happy path, all 4 recovery policies, bounded retries, and baseline mode.

**Expected Test Summary:**
```
============================== 37 passed in 1.05s ==============================
```

---

## 4. Running the Batch Evaluation Benchmark (`evaluate_router.py`)

To evaluate the entire system across all 56 real-world benchmark cases in [`data/eval.jsonl`](file:///home/shamshu/GPP/Week37/AI-Function-Calling-Router-with-Pydantic-and-Injected-Failure-Recovery/data/eval.jsonl):

```bash
python evaluate_router.py
```

### Console Output:
```
Dataset: 56 cases | pinned EVAL_TODAY=2026-10-03 | provider=offline model=offline-heuristic-v1

=== Metrics (output/metrics.json) ===
metric                      baseline    recovery
completion_rate               0.6071      0.9464
silent_wrong_rate             0.0000      0.0000
mean_recovery_attempts             0      0.3929

OK: recovery improved completion rate with silent_wrong_rate = 0.
```

---

## 5. Running with Docker Compose (1 Command)

To run the full evaluation in an isolated, containerized environment:

```bash
docker compose up --build --abort-on-container-exit
```

### What happens:
1. Docker builds the container image (`function-calling-router:latest`).
2. Installs pinned dependencies from `requirements.txt`.
3. Runs `evaluate_router.py`.
4. Saves `./output/metrics.json` and `./results/run_results.json` directly to your host machine via volume mounts.
5. Container shuts down cleanly with status code `0`.

---

## 6. Inspecting Output Artifacts

After running the evaluation (locally or via Docker), inspect the generated files:

### 1. View Summary Metrics:
```bash
cat output/metrics.json
```
```json
{
  "baseline": {
    "completion_rate": 0.6071,
    "silent_wrong_rate": 0.0,
    "mean_recovery_attempts": 0
  },
  "recovery_active": {
    "completion_rate": 0.9464,
    "silent_wrong_rate": 0.0,
    "mean_recovery_attempts": 0.3929
  }
}
```

### 2. View Detailed Audit Logs:
```bash
# View the first 3 evaluated cases in recovery mode:
python -c '
import json
data = json.load(open("results/run_results.json"))
for row in data["recovery_active"]["rows"][:3]:
    print(f"ID {row[\"id\"]}: {row[\"request\"]} -> {row[\"status\"]} (Policies: {row[\"policies_triggered\"]})")
'
```

---

## 7. Optional: Connecting a Real LLM (OpenAI / Ollama)

If you want to use a real model instead of the default offline engine:

1. Copy the example configuration:
   ```bash
   cp .env.example .env
   ```

2. Open `.env` and set:
   ```ini
   LLM_PROVIDER=openai
   LLM_API_KEY=your_api_key_here
   LLM_MODEL_ID=gpt-4o-mini
   ```

   *(For local Ollama / vLLM, add: `LLM_BASE_URL=http://localhost:11434/v1`)*

3. Run the evaluation script or test queries:
   ```bash
   python evaluate_router.py
   ```
