"""Sweep reranker thresholds against docs/eval/queries.json.

Computes per-query and macro F1 at each threshold step in [0.0, 1.0] (step
0.02 by default) and prints the threshold that maximises macro F1. Also
writes the full curve to docs/eval/threshold-curve.json so the user can
inspect the precision-recall trade-off.

Re-run after human-curating queries.json for a meaningful threshold. The
labels emitted by scripts/seed_eval_set.py are noisy — the threshold this
script picks today is *provisional*; the default of 0.5 in
sunnah_toolkit.core.reranker is the safer fallback.

Usage:
    python -m scripts.tune_threshold
    python -m scripts.tune_threshold --reranker bge-v2-m3 --step 0.01
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
QUERIES_PATH = ROOT / "docs" / "eval" / "queries.json"
OUT_PATH = ROOT / "docs" / "eval" / "threshold-curve.json"


def _norm_num(s: str) -> str:
    return (s or "").split(",", 1)[0].strip().lower()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--reranker", default=os.environ.get("RERANKER_NAME", "bge-v2-m3"))
    ap.add_argument("--step", type=float, default=0.02)
    ap.add_argument("--k_candidates", type=int, default=100)
    args = ap.parse_args()

    os.environ["RERANKER_NAME"] = args.reranker
    os.environ.pop("RERANKER_DISABLED", None)
    # Set threshold to -inf so _search_with_rerank returns every candidate
    # in `results_weak`. We do the F1 calculation here over the union.
    os.environ["RERANKER_THRESHOLD"] = "-1e9"

    from sunnah_toolkit.core import tools  # noqa: E402

    data = json.loads(QUERIES_PATH.read_text())
    queries = data["queries"]

    per_query_scores: list[list[tuple[float, bool]]] = []
    for q in queries:
        relevant = {(r["collection"], _norm_num(r["hadith_number"])) for r in q["relevant"]}
        res = tools._search_with_rerank(
            q["query"],
            mode_hint=q.get("mode_hint", "concept"),
            collection=None,
            limit=10**6,
            k_per_retriever=args.k_candidates,
        )
        rows = res["results"] + res["results_weak"]
        scored: list[tuple[float, bool]] = []
        for row in rows:
            key = (row["slug"], _norm_num(row.get("hadith_number", "")))
            scored.append((float(row.get("score", 0.0)), key in relevant))
        per_query_scores.append(scored)
        print(f"query {q['query']!r}: {len(scored)} candidates, {sum(1 for _,r in scored if r)} relevant")

    thresholds: list[float] = []
    t = 0.0
    while t <= 1.0 + 1e-9:
        thresholds.append(round(t, 4))
        t += args.step

    curve: list[dict] = []
    best = {"threshold": 0.5, "macro_f1": -1.0, "macro_precision": 0.0, "macro_recall": 0.0}
    for thr in thresholds:
        p_sum = r_sum = f_sum = 0.0
        n = 0
        for scored in per_query_scores:
            tp = sum(1 for s, r in scored if s >= thr and r)
            fp = sum(1 for s, r in scored if s >= thr and not r)
            fn = sum(1 for s, r in scored if s < thr and r)
            precision = tp / (tp + fp) if (tp + fp) else 0.0
            recall = tp / (tp + fn) if (tp + fn) else 0.0
            f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
            p_sum += precision
            r_sum += recall
            f_sum += f1
            n += 1
        macro_p = p_sum / max(n, 1)
        macro_r = r_sum / max(n, 1)
        macro_f = f_sum / max(n, 1)
        curve.append({
            "threshold": thr,
            "macro_precision": round(macro_p, 4),
            "macro_recall": round(macro_r, 4),
            "macro_f1": round(macro_f, 4),
        })
        if macro_f > best["macro_f1"]:
            best = {
                "threshold": thr,
                "macro_f1": round(macro_f, 4),
                "macro_precision": round(macro_p, 4),
                "macro_recall": round(macro_r, 4),
            }

    out = {
        "_status": "provisional; eval queries are auto-seeded, not human-curated",
        "_reranker": args.reranker,
        "_generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "best": best,
        "curve": curve,
    }
    OUT_PATH.write_text(json.dumps(out, indent=2))
    print(f"\nBest threshold for {args.reranker} (provisional): {best}")
    print(f"Wrote {OUT_PATH}")


if __name__ == "__main__":
    main()
