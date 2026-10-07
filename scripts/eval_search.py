"""Evaluate the search pipeline against expert-graded relevance labels.

Metrics (macro-averaged across queries):
  * **NDCG@10** — graded. Gain is the expert's 0-3 judgment, discounted as
    (2^gain - 1) / log2(rank + 1). This is the headline number: it rewards
    putting a *canonical* hadith at rank 1 more than a merely-relevant one,
    which binary NDCG cannot express.
  * **P@10 / Recall@100** — computed against a relevance threshold
    (default: gain >= 2, i.e. "directly relevant" or better).
  * **Recall@100 on expert-added refs** — how many hadiths the experts had to
    add by hand does the system now find? These are the known recall failures,
    so this is the most diagnostic single number for retrieval quality.

Unjudged results are scored as gain 0. Labels are pooled from this system, so
that assumption is standard but does mean an unpooled gem is invisible here.

Input, in order of preference:
  1. docs/eval/queries-graded.json  (expert labels; written by ingest_eval_sheet)
  2. --queries <path>

Usage:
    python -m scripts.eval_search --reranker bge-v2-m3
    python -m scripts.eval_search --reranker none --save
    python -m scripts.eval_search --rel-threshold 1
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
EVAL_DIR = ROOT / "docs" / "eval"
GRADED_PATH = EVAL_DIR / "queries-graded.json"
RESULTS_DIR = EVAL_DIR


def _norm_num(s: str) -> str:
    """Sunnah.com numbers look like "402b" or "272, 273"; key on the primary."""
    return "".join((s or "").split(",", 1)[0].split()).lower()


def _result_keys(results: list[dict]) -> list[tuple[str, str]]:
    return [(r.get("slug", ""), _norm_num(r.get("hadith_number", ""))) for r in results]


def _gain_map(rel_list: list[dict]) -> dict[tuple[str, str], int]:
    return {
        (r["collection"], _norm_num(r["hadith_number"])): int(r.get("gain", 1))
        for r in rel_list
    }


def ndcg_at_k(
    retrieved: list[tuple[str, str]], gains: dict[tuple[str, str], int], k: int
) -> float:
    """Graded NDCG. Exponential gain, log2 discount, ideal from all judgments."""
    if not retrieved or not gains:
        return 0.0
    dcg = sum(
        (2 ** gains.get(key, 0) - 1) / math.log2(i + 2)
        for i, key in enumerate(retrieved[:k])
    )
    ideal_gains = sorted(gains.values(), reverse=True)[:k]
    idcg = sum((2 ** g - 1) / math.log2(i + 2) for i, g in enumerate(ideal_gains))
    return dcg / idcg if idcg > 0 else 0.0


def precision_at_k(
    retrieved: list[tuple[str, str]], gains: dict, k: int, threshold: int
) -> float:
    if not retrieved:
        return 0.0
    hits = sum(1 for key in retrieved[:k] if gains.get(key, 0) >= threshold)
    return hits / k


def recall_at_k(
    retrieved: list[tuple[str, str]], gains: dict, k: int, threshold: int
) -> float:
    relevant = {key for key, g in gains.items() if g >= threshold}
    if not relevant:
        return 0.0
    hits = sum(1 for key in retrieved[:k] if key in relevant)
    return hits / len(relevant)


def _set_reranker_env(name: str) -> None:
    # Must run before importing tools -- the reranker choice is read from env.
    if name == "none":
        os.environ["RERANKER_DISABLED"] = "1"
    else:
        os.environ.pop("RERANKER_DISABLED", None)
        os.environ["RERANKER_NAME"] = name


def run_eval(
    reranker: str, queries_path: Path, limit: int = 100, threshold: int = 2
) -> dict[str, Any]:
    _set_reranker_env(reranker)
    from sunnah_toolkit.core import tools  # noqa: E402  (env must be set first)

    data = json.loads(queries_path.read_text())
    queries = data["queries"]

    per_query: list[dict] = []
    acc = {"p@10": 0.0, "ndcg@10": 0.0, "recall@100": 0.0, "added_recall": 0.0, "ms": 0.0}
    n_added_total = 0

    for q in queries:
        gains = _gain_map(q["relevant"])
        added = {
            (r["collection"], _norm_num(r["hadith_number"]))
            for r in q["relevant"]
            if r.get("added_by_expert") and int(r.get("gain", 0)) >= threshold
        }

        t0 = time.perf_counter()
        res = tools.search_with_rerank(
            q["query"], mode_hint=q.get("mode_hint", "concept"),
            collection=None, limit=limit,
        )
        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        retrieved = _result_keys(res.get("results", []) + res.get("results_weak", []))
        p10 = precision_at_k(retrieved, gains, 10, threshold)
        ndcg10 = ndcg_at_k(retrieved, gains, 10)
        r100 = recall_at_k(retrieved, gains, 100, threshold)

        top100 = set(retrieved[:100])
        added_recall = (
            len(added & top100) / len(added) if added else float("nan")
        )

        per_query.append({
            "id": q.get("id"),
            "query": q["query"],
            "mode_hint": q.get("mode_hint"),
            "n_relevant": sum(1 for g in gains.values() if g >= threshold),
            "n_judged": len(gains),
            "n_expert_added": len(added),
            "p@10": round(p10, 4),
            "ndcg@10": round(ndcg10, 4),
            "recall@100": round(r100, 4),
            "expert_added_recall@100": (
                None if added != added or not added else round(added_recall, 4)
            ),
            "latency_ms": round(elapsed_ms, 1),
        })
        acc["p@10"] += p10
        acc["ndcg@10"] += ndcg10
        acc["recall@100"] += r100
        acc["ms"] += elapsed_ms
        if added:
            acc["added_recall"] += added_recall
            n_added_total += 1

    n = max(len(queries), 1)
    return {
        "reranker": reranker,
        "queries_file": queries_path.name,
        "rel_threshold": threshold,
        "n_queries": len(queries),
        "macro": {
            "p@10": round(acc["p@10"] / n, 4),
            "ndcg@10": round(acc["ndcg@10"] / n, 4),
            "recall@100": round(acc["recall@100"] / n, 4),
            "expert_added_recall@100": (
                round(acc["added_recall"] / n_added_total, 4) if n_added_total else None
            ),
            "mean_latency_ms": round(acc["ms"] / n, 1),
        },
        "per_query": per_query,
    }


def _print_table(report: dict[str, Any]) -> None:
    print(f"\nReranker: {report['reranker']}    queries: {report['n_queries']}"
          f"    labels: {report['queries_file']}"
          f"    relevant = gain >= {report['rel_threshold']}")
    print("-" * 100)
    print(f"{'query':<38} {'mode':<8} {'rel':>4} {'P@10':>6} {'NDCG@10':>8} "
          f"{'R@100':>6} {'add-R':>6} {'ms':>6}")
    print("-" * 100)
    for q in report["per_query"]:
        add = q["expert_added_recall@100"]
        print(
            f"{q['query'][:37]:<38} "
            f"{(q['mode_hint'] or '')[:7]:<8} "
            f"{q['n_relevant']:>4} "
            f"{q['p@10']:>6.3f} "
            f"{q['ndcg@10']:>8.3f} "
            f"{q['recall@100']:>6.3f} "
            f"{('  —  ' if add is None else f'{add:>6.3f}')} "
            f"{q['latency_ms']:>6.0f}"
        )
    m = report["macro"]
    add = m["expert_added_recall@100"]
    print("-" * 100)
    print(
        f"{'MACRO':<38} {'':8} {'':>4} "
        f"{m['p@10']:>6.3f} {m['ndcg@10']:>8.3f} {m['recall@100']:>6.3f} "
        f"{('  —  ' if add is None else f'{add:>6.3f}')} "
        f"{m['mean_latency_ms']:>6.0f}"
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--reranker",
        default=os.environ.get("RERANKER_NAME", "bge-v2-m3"),
        choices=["none", "jina-v3", "bge-v2-m3", "mxbai-v2-base", "jina-v2-base"],
    )
    ap.add_argument("--queries", default="", help="Label file (default: queries-graded.json).")
    ap.add_argument("--limit", type=int, default=100, help="K candidates returned.")
    ap.add_argument("--rel-threshold", type=int, default=2, choices=[1, 2, 3],
                    help="Minimum gain counted as relevant for P/R (default 2).")
    ap.add_argument("--save", action="store_true", help="Archive JSON under docs/eval/.")
    args = ap.parse_args()

    queries_path = Path(args.queries) if args.queries else GRADED_PATH
    if not queries_path.exists():
        print(
            f"No label file at {queries_path}.\n"
            f"Expert judgments have not been ingested yet. Run:\n"
            f"  python -m scripts.ingest_eval_sheet docs/eval/expert-sheet-<date>.xlsx",
            file=sys.stderr,
        )
        return 2

    report = run_eval(args.reranker, queries_path, args.limit, args.rel_threshold)
    _print_table(report)

    if args.save:
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y%m%d-%H%M%S")
        out = RESULTS_DIR / f"results-{args.reranker}-{ts}.json"
        out.write_text(json.dumps(report, indent=2, ensure_ascii=False))
        print(f"\nSaved: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
