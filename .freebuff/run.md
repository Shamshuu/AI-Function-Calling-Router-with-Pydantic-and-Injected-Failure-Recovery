# Run doc — this thread's preview

## Preview mode

Standalone HTML page — **no server, no port, no process**. The preview is registered
against `index.html` at the repo root (served by the Freebuff preview runtime, which
reloads it from disk on every change).

## How to reproduce the artifacts the page shows

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/pytest -q                    # 30 tests, req-1..req-8 contract checks
.venv/bin/python evaluate_router.py    # writes output/metrics.json + results/run_results.json
```

Fully offline; defaults come from `.env.example` pins (`EVAL_TODAY=2026-10-03`,
`LLM_PROVIDER=offline`). Rerunning with the same pins reproduces the same numbers.

## How to run the containerized harness

```bash
docker compose up --build --abort-on-container-exit   # exits 0, writes ./output volume
```

The preview page (`index.html`) is a static snapshot of the committed run; regenerate
`output/metrics.json` with the commands above if you change code or dataset.
