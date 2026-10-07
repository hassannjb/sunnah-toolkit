#!/bin/bash
# launchd entry point for the sunnah-toolkit API on a CPU-only Intel Mac.
# Binds to localhost only: the ngrok tunnel is the sole way in.
set -euo pipefail
cd "$(dirname "$0")/../.."

# Secrets (ANTHROPIC_API_KEY for the natural-language router) live outside
# the repo in a chmod 600 file of KEY=value lines.
ENV_FILE="$HOME/.config/sunnah-toolkit/env"
if [ -f "$ENV_FILE" ]; then set -a; . "$ENV_FILE"; set +a; fi

export PYTHONUNBUFFERED=1
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
# bge-v2-m3 over the full pool is ~15 min/query on a dual-core i5; the
# small English cross-encoder over the first-stage top 40 is ~1.5-2.5 s.
export RERANKER_NAME="${RERANKER_NAME:-minilm-l6}"
export RERANKER_TOP_N="${RERANKER_TOP_N:-40}"
# bge-m3 bi-encoder: knows "dua", "qunut", question phrasing; +0.5 s, +1.5 GB.
# On torch < 2.6 it needs the safetensors weights (refs/pr/130), not the .bin.
export SEMANTIC_BACKEND="${SEMANTIC_BACKEND:-v2}"
# v2 extra legs: chapter-title match (needs chapters_*.npy from
# scripts/build_chapter_embeddings.py) and near-duplicate narrations of the
# top semantic hits. RETRIEVER_K and FUSION=rrf exist too but showed no gain.
export RETRIEVAL_CHAPTERS="${RETRIEVAL_CHAPTERS:-1}"
export RETRIEVAL_NEIGHBORS="${RETRIEVAL_NEIGHBORS:-1}"
PORT="${PORT:-8000}"

# The library and bi-encoder load lazily on the first query (~45 s here).
# Pay that at boot with one throwaway search instead of on a real user.
(
  until curl -fsS "http://127.0.0.1:$PORT/healthz" >/dev/null 2>&1; do sleep 2; done
  curl -fsS "http://127.0.0.1:$PORT/v1/search?query=warmup&limit=1" >/dev/null 2>&1 \
    && echo "warm-up search done"
) &

exec .venv/bin/python -m sunnah_toolkit --transport http --host 127.0.0.1 --port "$PORT"
