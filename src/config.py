"""Central configuration. Everything that can move a metric is pinned here / via env."""
import os

from dotenv import load_dotenv

load_dotenv()

# "offline" (deterministic heuristic backend, default) or "openai" (OpenAI-compatible API)
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "offline").strip().lower()
LLM_API_KEY = os.getenv("LLM_API_KEY", "").strip()
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "").strip() or None
LLM_MODEL_ID = os.getenv("LLM_MODEL_ID", "offline-heuristic-v1").strip()

# Pinned reference date for resolving relative dates ("tomorrow", "next Tuesday").
EVAL_TODAY = os.getenv("EVAL_TODAY", "2026-10-03").strip()

# Backoff (seconds) before the single system-level timeout retry.
TIMEOUT_BACKOFF_S = float(os.getenv("TIMEOUT_BACKOFF_S", "0.1"))
