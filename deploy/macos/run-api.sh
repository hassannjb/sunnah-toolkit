#!/bin/bash
# launchd entry point for the sunnah-toolkit API on a CPU-only Intel Mac.
# Binds to localhost only: the ngrok tunnel is the sole way in.
set -euo pipefail
cd "$(dirname "$0")/../.."

export PYTHONUNBUFFERED=1
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
# bge-v2-m3 over the full pool is ~15 min/query on a dual-core i5; the
# small English cross-encoder over the first-stage top 40 is ~1.5-2.5 s.
export RERANKER_NAME="${RERANKER_NAME:-minilm-l6}"
export RERANKER_TOP_N="${RERANKER_TOP_N:-40}"
PORT="${PORT:-8000}"

# The library and bi-encoder load lazily on the first query (~45 s here).
# Pay that at boot with one throwaway search instead of on a real user.
(
  until curl -fsS "http://127.0.0.1:$PORT/healthz" >/dev/null 2>&1; do sleep 2; done
  curl -fsS "http://127.0.0.1:$PORT/v1/search?query=warmup&limit=1" >/dev/null 2>&1 \
    && echo "warm-up search done"
) &

exec .venv/bin/python -m sunnah_toolkit --transport http --host 127.0.0.1 --port "$PORT"
