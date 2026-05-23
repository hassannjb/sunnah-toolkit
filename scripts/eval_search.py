"""Run docs/eval/queries.json against the search pipeline and report metrics.

Metrics: P@10, NDCG@10, Recall@100 — macro-averaged across queries.

Usage:
    python -m scripts.eval_search --reranker bge-v2-m3
    python -m scripts.eval_search --reranker none

Note:
    docs/eval/queries.json is auto-seeded — labels are noisy until a human
    curates them. To compare candidate rerankers, run this script once per
    candidate (`--reranker jina-v3`, `--reranker bge-v2-m3`,
    `--reranker mxbai-v2-base`, `--reranker jina-v2-base`) and pick the
    highest NDCG@10 within the size budget. The four candidates are listed
    in Issue #2.
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
    # Sunnah.com lists numbers like "402b" or "272, 273". For matching we take
    # the primary citation (first comma-split, lower-cased, stripped).
    return (s or "").split(",", 1)[0].strip().lower()


def _result_keys(results: list[dict]) -> list[tuple[str, str]]:
    return [(r.get("slug", ""), _norm_num(r.get("hadith_number", ""))) for r in results]


def _relevant_keys(rel_list: list[dict]) -> set[tuple[str, str]]:
    return {(r["collection"], _norm_num(r["hadith_number"])) for r in rel_list}


def precision_at_k(retrieved: list[tuple[str, str]], relevant: set, k: int) -> float:
    if not retrieved or not relevant:
        return 0.0
    top = retrieved[:k]
    hits = sum(1 for r in top if r in relevant)
    return hits / k


def recall_at_k(retrieved: list[tuple[str, str]], relevant: set, k: int) -> float:
    if not relevant:
        return 0.0
    top = retrieved[:k]
    hits = sum(1 for r in top if r in relevant)
    return hits / len(relevant)


def ndcg_at_k(retrieved: list[tuple[str, str]], relevant: set, k: int) -> float:
    if not retrieved or not relevant:
        return 0.0
    dcg = 0.0
    for i, r in enumerate(retrieved[:k]):
        if r in relevant:
            dcg += 1.0 / math.log2(i + 2)
    ideal = sum(1.0 / math.log2(i + 2) for i in range(min(k, len(relevant))))
    return dcg / ideal if ideal > 0 else 0.0


def _set_reranker_env(name: str) -> None:
    # Configures the runtime reranker before importing tools (which may
    # cache the choice via env var). `none` disables reranking entirely.
    if name == "none":
        os.environ["RERANKER_DISABLED"] = "1"
    else:
        os.environ.pop("RERANKER_DISABLED", None)
        os.environ["RERANKER_NAME"] = name


def run_eval(reranker: str, limit: int = 100) -> dict[str, Any]:
    _set_reranker_env(reranker)
    from sunnah_toolkit.core import tools  # noqa: E402  (env must be set first)

    data = json.loads(QUERIES_PATH.read_text())
    queries = data["queries"]

    per_query: list[dict] = []
    p10_acc = ndcg10_acc = r100_acc = 0.0
    timing_ms_acc = 0.0
    for q in queries:
        relevant = _relevant_keys(q["relevant"])
        t0 = time.perf_counter()
        # _search_with_rerank is the unified pipeline introduced in Phase C.
        # If it's not present yet (Phase A run), fall back to search_hadith.
        if hasattr(tools, "_search_with_rerank"):
            res = tools._search_with_rerank(
                q["query"],
                mode_hint=q.get("mode_hint", "concept"),
                collection=None,
                limit=limit,
            )
        else:
            res = tools.search_hadith(q["query"], limit=limit)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        retrieved = _result_keys(res.get("results", []) + res.get("results_weak", []))
        p10 = precision_at_k(retrieved, relevant, 10)
        ndcg10 = ndcg_at_k(retrieved, relevant, 10)
        r100 = recall_at_k(retrieved, relevant, 100)

        per_query.append({
            "query": q["query"],
            "mode_hint": q.get("mode_hint"),
            "n_relevant": len(relevant),
            "n_retrieved": len(retrieved),
            "p@10": round(p10, 4),
            "ndcg@10": round(ndcg10, 4),
            "recall@100": round(r100, 4),
            "latency_ms": round(elapsed_ms, 1),
        })
        p10_acc += p10
        ndcg10_acc += ndcg10
        r100_acc += r100
        timing_ms_acc += elapsed_ms

    n = max(len(queries), 1)
    return {
        "reranker": reranker,
        "n_queries": len(queries),
        "macro": {
            "p@10": round(p10_acc / n, 4),
            "ndcg@10": round(ndcg10_acc / n, 4),
            "recall@100": round(r100_acc / n, 4),
            "mean_latency_ms": round(timing_ms_acc / n, 1),
        },
        "per_query": per_query,
    }


def _print_table(report: dict[str, Any]) -> None:
    print(f"\nReranker: {report['reranker']}    queries: {report['n_queries']}")
    print("-" * 88)
    print(f"{'query':<40} {'mode':<8} {'rel':>4} {'P@10':>6} {'NDCG@10':>8} {'R@100':>6} {'ms':>6}")
    print("-" * 88)
    for q in report["per_query"]:
        print(
            f"{q['query'][:39]:<40} "
            f"{(q['mode_hint'] or '')[:7]:<8} "
            f"{q['n_relevant']:>4} "
            f"{q['p@10']:>6.3f} "
            f"{q['ndcg@10']:>8.3f} "
            f"{q['recall@100']:>6.3f} "
            f"{q['latency_ms']:>6.0f}"
        )
    m = report["macro"]
    print("-" * 88)
    print(
        f"{'MACRO':<40} {'':8} {'':>4} "
        f"{m['p@10']:>6.3f} {m['ndcg@10']:>8.3f} {m['recall@100']:>6.3f} "
        f"{m['mean_latency_ms']:>6.0f}"
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--reranker",
        default=os.environ.get("RERANKER_NAME", "bge-v2-m3"),
        choices=["none", "jina-v3", "bge-v2-m3", "mxbai-v2-base", "jina-v2-base"],
        help="Reranker model to evaluate (default: bge-v2-m3).",
    )
    ap.add_argument("--limit", type=int, default=100, help="K candidates returned.")
    ap.add_argument("--save", action="store_true", help="Archive JSON under docs/eval/.")
    args = ap.parse_args()

    report = run_eval(args.reranker, limit=args.limit)
    _print_table(report)

    if args.save:
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y%m%d-%H%M%S")
        out = RESULTS_DIR / f"results-{args.reranker}-{ts}.json"
        out.write_text(json.dumps(report, indent=2, ensure_ascii=False))
        print(f"\nSaved: {out}")


if __name__ == "__main__":
    main()
