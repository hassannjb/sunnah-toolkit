"""Evaluation harness for the natural-language search endpoint (Issue #4).

Runs the LLM router + RRF retrieval pipeline against
``docs/eval/queries.json`` and reports macro P@10 / NDCG@10 / Recall@100 —
the same shape that ``scripts/eval_search`` produces for the regular search
modes, so the two reports can be compared head-to-head.

Currently supports only the Anthropic provider (Claude Haiku 4.5). Stubs
for OpenAI and Ollama are deferred: when those land, add a ``--provider``
flag that selects between the registered ``Router`` implementations rather
than hard-coding Anthropic here.

Usage:
    ANTHROPIC_API_KEY=sk-... python -m scripts.eval_natural

Without an API key set, the eval skips the LLM router and falls back to
plain Concept-mode for every query — the report still runs, but every row
will carry ``fallback=llm_unavailable`` so you can see the floor.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
QUERIES_PATH = ROOT / "docs" / "eval" / "queries.json"
RESULTS_DIR = ROOT / "docs" / "eval"


def _norm_num(s: str) -> str:
    return (s or "").split(",", 1)[0].strip().lower()


def _result_keys(results: list[dict]) -> list[tuple[str, str]]:
    return [(r.get("slug", ""), _norm_num(r.get("hadith_number", ""))) for r in results]


def _precision_at_k(retrieved: list[tuple[str, str]], gold: set[tuple[str, str]], k: int) -> float:
    if not gold or not retrieved:
        return 0.0
    top_k = retrieved[:k]
    if not top_k:
        return 0.0
    return sum(1 for r in top_k if r in gold) / len(top_k)


def _ndcg_at_k(retrieved: list[tuple[str, str]], gold: set[tuple[str, str]], k: int) -> float:
    if not gold or not retrieved:
        return 0.0
    dcg = 0.0
    for i, r in enumerate(retrieved[:k], start=1):
        if r in gold:
            dcg += 1.0 / math.log2(i + 1)
    ideal = sum(1.0 / math.log2(i + 1) for i in range(1, min(len(gold), k) + 1))
    return (dcg / ideal) if ideal > 0 else 0.0


def _recall_at_k(retrieved: list[tuple[str, str]], gold: set[tuple[str, str]], k: int) -> float:
    if not gold:
        return 0.0
    top_k = set(retrieved[:k])
    return len(top_k & gold) / len(gold)


def _load_queries() -> list[dict[str, Any]]:
    with QUERIES_PATH.open() as f:
        return json.load(f)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate natural-language search.")
    parser.add_argument(
        "--provider",
        default="anthropic",
        choices=["anthropic"],  # openai/ollama stubs land later
        help="LLM provider (currently only anthropic).",
    )
    parser.add_argument(
        "--limit", type=int, default=10, help="Strong-result cap passed to the API."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=RESULTS_DIR / "eval_natural_results.json",
        help="Where to write the per-query JSON report.",
    )
    args = parser.parse_args(argv)

    os.environ.setdefault("LLM_PROVIDER", args.provider)

    # Import lazily so the module can be loaded for `--help` even without the
    # core deps in place.
    from sunnah_toolkit.core import tools

    queries = _load_queries()

    rows: list[dict[str, Any]] = []
    macro_p10 = 0.0
    macro_ndcg10 = 0.0
    macro_r100 = 0.0
    n = 0
    for q in queries:
        text = q.get("query", "").strip()
        if not text:
            continue
        gold_raw = q.get("relevant") or q.get("gold") or []
        gold: set[tuple[str, str]] = set()
        for g in gold_raw:
            slug = g.get("slug", "")
            num = _norm_num(g.get("hadith_number", ""))
            if slug and num:
                gold.add((slug, num))

        t0 = time.perf_counter()
        result = tools.search_hadith_natural(text, limit=args.limit)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        strong = result.get("results") or []
        weak = result.get("results_weak") or []
        combined_keys = _result_keys(strong) + _result_keys(weak)

        p10 = _precision_at_k(combined_keys, gold, 10)
        ndcg10 = _ndcg_at_k(combined_keys, gold, 10)
        r100 = _recall_at_k(combined_keys, gold, 100)

        macro_p10 += p10
        macro_ndcg10 += ndcg10
        macro_r100 += r100
        n += 1

        rows.append({
            "query": text,
            "gold_count": len(gold),
            "variants": result.get("variants") or [],
            "fallback": result.get("fallback"),
            "mode_hint": result.get("mode_hint"),
            "pool_size": result.get("pool_size"),
            "elapsed_ms": round(elapsed_ms, 1),
            "p_at_10": round(p10, 4),
            "ndcg_at_10": round(ndcg10, 4),
            "recall_at_100": round(r100, 4),
        })

    macro_p10 /= max(n, 1)
    macro_ndcg10 /= max(n, 1)
    macro_r100 /= max(n, 1)

    summary = {
        "provider": args.provider,
        "queries": n,
        "macro_p_at_10": round(macro_p10, 4),
        "macro_ndcg_at_10": round(macro_ndcg10, 4),
        "macro_recall_at_100": round(macro_r100, 4),
        "rows": rows,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    print(f"provider={args.provider} queries={n}")
    print(f"macro P@10        {macro_p10:.4f}")
    print(f"macro NDCG@10     {macro_ndcg10:.4f}")
    print(f"macro Recall@100  {macro_r100:.4f}")
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
