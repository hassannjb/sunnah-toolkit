"""Read a completed expert-review workbook back into graded eval labels.

Consumes the .xlsx produced by `scripts/build_eval_sheet.py` after scholars
have filled in the 0-3 relevance column, and emits
`docs/eval/queries-graded.json` for `scripts/eval_search.py`.

Handles the realities of a spreadsheet filled in by humans:
  * grades as int, float, "2", "2.", " 2 ", or "3 - canonical" -> 3
  * blank grades  -> unjudged, reported but not treated as 0
  * out-of-range values -> reported, skipped
  * rows pasted into the "ADD MISSING HADITHS" block, identified by a
    sunnah.com link (or by typing collection + number directly)
  * sunnah.com slug aliases (nawawi40 -> forty)
  * duplicate refs within a tab -> highest grade wins, conflict reported

Every added ref is verified through `Library.get_hadith` before it enters the
label set. An unresolvable ref is reported loudly and dropped -- silently
keeping it would reintroduce the bad-reference class of bug that corrupted the
2026-05-29 labels.

Usage:
    python -m scripts.ingest_eval_sheet docs/eval/expert-sheet-20260801.xlsx
    python -m scripts.ingest_eval_sheet <path> --pool docs/eval/pool-20260801.json
    python -m scripts.ingest_eval_sheet <path> --strict   # nonzero exit on any warning
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

from sunnah_toolkit.core.data import Library, load

ROOT = Path(__file__).resolve().parent.parent
EVAL_DIR = ROOT / "docs" / "eval"
QUERIES_PATH = EVAL_DIR / "queries-20.json"
OUT_PATH = EVAL_DIR / "queries-graded.json"

# Columns as written by build_eval_sheet.py (1-indexed).
C_N, C_REL, C_NOTES, C_COLL, C_NUM, C_LINK = 1, 2, 3, 4, 5, 6
HEADER_ROW = 4

# sunnah.com uses a few slugs that differ from ours.
SLUG_ALIASES = {
    "nawawi40": "forty",
    "nawawi": "forty",
    "40": "forty",
    "adabalmufrad": "adab",
    "riyadus-salihin": "riyadussalihin",
    "riyadussaliheen": "riyadussalihin",
    "hisnulmuslim": "hisn",
}

_LINK_RE = re.compile(
    r"sunnah\.com/(?P<slug>[a-zA-Z0-9_-]+)\s*:\s*(?P<num>[0-9]+[a-zA-Z]?)"
)
_BOOK_FORM_RE = re.compile(r"sunnah\.com/(?P<slug>[a-zA-Z0-9_-]+)/(?P<book>\d+)/(?P<n>\d+)")
_GRADE_RE = re.compile(r"[0-3]")


class Report:
    def __init__(self) -> None:
        self.warnings: list[str] = []
        self.info: list[str] = []

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)
        print(f"  !! {msg}")

    def note(self, msg: str) -> None:
        self.info.append(msg)


def parse_grade(raw: Any) -> int | None:
    """Coerce a spreadsheet cell into 0-3, or None if blank/unparseable."""
    if raw is None:
        return None
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        v = int(raw)
        return v if 0 <= v <= 3 else None
    s = str(raw).strip()
    if not s:
        return None
    m = _GRADE_RE.search(s)
    return int(m.group()) if m else None


def parse_ref(link: Any, coll: Any, num: Any) -> tuple[str, str] | None:
    """Resolve a row to (collection_slug, hadith_number).

    Prefers explicit collection/number cells; falls back to parsing a
    sunnah.com URL out of the Link column.
    """
    if coll and num:
        slug = str(coll).strip().lower()
        return SLUG_ALIASES.get(slug, slug), str(num).strip()

    if not link:
        return None
    text = str(link).strip()
    m = _LINK_RE.search(text)
    if m:
        slug = m.group("slug").lower()
        return SLUG_ALIASES.get(slug, slug), m.group("num")
    if _BOOK_FORM_RE.search(text):
        return None  # book/hadith URL form -- different lookup, needs a human
    return None


def read_tab(
    ws,
    library: Library,
    rep: Report,
    tab: str,
    pooled_keys: set[tuple[str, str]] | None = None,
) -> tuple[dict[tuple[str, str], dict], int, int]:
    """Return {(coll, num): {gain, notes, added}}, n_judged, n_rows_seen.

    `added` means "no retriever surfaced this ref", which is the signal
    `expert_added_recall@100` is built on. It is decided against `pooled_keys`
    (the candidate pool of record) rather than against which spreadsheet row
    the grade arrived on: a reviewer who blanks a pooled row and re-pastes the
    same ref into the ADD block must not manufacture a phantom recall failure.
    """
    judged: dict[tuple[str, str], dict] = {}
    n_rows = 0
    conflicts: dict[tuple[str, str], set[int]] = defaultdict(set)

    for row in range(HEADER_ROW + 1, ws.max_row + 1):
        rel_raw = ws.cell(row=row, column=C_REL).value
        coll_raw = ws.cell(row=row, column=C_COLL).value
        num_raw = ws.cell(row=row, column=C_NUM).value
        link_raw = ws.cell(row=row, column=C_LINK).value
        notes = ws.cell(row=row, column=C_NOTES).value

        # The "ADD MISSING" banner spans the row with text in column A only.
        if not any((rel_raw, coll_raw, num_raw, link_raw)):
            continue

        was_pooled = bool(coll_raw and num_raw)
        if was_pooled:
            n_rows += 1

        ref = parse_ref(link_raw, coll_raw, num_raw)
        if ref is None:
            if rel_raw is not None or link_raw:
                rep.warn(
                    f"{tab} row {row}: could not resolve a hadith reference "
                    f"(link={link_raw!r}) -- skipped"
                )
            continue

        slug, num = ref
        if slug not in library.collections:
            rep.warn(f"{tab} row {row}: unknown collection {slug!r} -- skipped")
            continue

        h = library.get_hadith(slug, num)
        if h is None:
            rep.warn(f"{tab} row {row}: {slug}:{num} does not resolve -- skipped")
            continue

        grade = parse_grade(rel_raw)
        if grade is None:
            if not was_pooled:
                rep.warn(
                    f"{tab} row {row}: added ref {slug}:{num} has no relevance "
                    f"grade -- skipped"
                )
            continue

        # Canonicalise on what get_hadith resolved to, so "375" and "375a"
        # collapse to one key.
        canon_num = "".join((h.hadith_number or num).split(",", 1)[0].split())
        key = (slug, canon_num)
        conflicts[key].add(grade)
        is_added = (key not in pooled_keys) if pooled_keys else (not was_pooled)
        prev = judged.get(key)
        if prev is None:
            judged[key] = {
                "gain": grade,
                "notes": str(notes).strip() if notes else "",
                "added": is_added,
            }
        elif grade > prev["gain"]:
            # Highest grade wins, but `added` stays keyed to the pool and any
            # earlier note survives if this row didn't carry one.
            prev["gain"] = grade
            prev["notes"] = prev["notes"] or (str(notes).strip() if notes else "")

    for key, grades in conflicts.items():
        if len(grades) > 1:
            rep.warn(
                f"{tab}: {key[0]}:{key[1]} graded {sorted(grades)} more than once "
                f"-- taking {max(grades)}"
            )

    return judged, len(judged), n_rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("workbook", help="Path to the filled-in .xlsx")
    ap.add_argument("--pool", default="", help="pool-<date>.json for coverage cross-check")
    ap.add_argument("--out", default=str(OUT_PATH))
    ap.add_argument("--strict", action="store_true",
                    help="Exit nonzero if any warning was raised.")
    args = ap.parse_args()

    wb_path = Path(args.workbook)
    if not wb_path.exists():
        print(f"No such workbook: {wb_path}", file=sys.stderr)
        return 2

    spec = json.loads(QUERIES_PATH.read_text())
    by_id = {q["id"]: q for q in spec["queries"]}
    pool = {}
    if args.pool:
        pool_data = json.loads(Path(args.pool).read_text())
        pool = {q["id"]: q for q in pool_data["queries"]}

    print(f"Loading library ...")
    library = load()
    print(f"Reading {wb_path.name} ...\n")
    wb = load_workbook(wb_path, data_only=True)
    rep = Report()

    out_queries: list[dict] = []
    tot_judged = tot_added = tot_pooled = 0

    for qid, q in by_id.items():
        tab = f"{qid}_{q['slug']}"[:31]
        if tab not in wb.sheetnames:
            rep.warn(f"tab {tab!r} missing from workbook -- query skipped")
            continue

        pooled_keys = {
            (c["collection"], c["hadith_number"].lower())
            for c in pool.get(qid, {}).get("candidates", [])
        } if pool else None
        judged, n_judged, n_rows = read_tab(wb[tab], library, rep, tab, pooled_keys)
        added = sum(1 for v in judged.values() if v["added"])
        pooled_n = len(pooled_keys) if pooled_keys else n_rows
        unjudged = max(0, pooled_n - (n_judged - added))

        relevant = [
            {
                "collection": c, "hadith_number": n,
                "gain": v["gain"], "added_by_expert": v["added"],
                **({"notes": v["notes"]} if v["notes"] else {}),
            }
            for (c, n), v in sorted(judged.items())
        ]
        dist = defaultdict(int)
        for v in judged.values():
            dist[v["gain"]] += 1

        out_queries.append({
            "id": qid, "query": q["query"], "mode_hint": q["mode_hint"],
            "variants": q.get("variants", []),
            "n_judged": n_judged, "n_added_by_expert": added, "n_unjudged": unjudged,
            "grade_distribution": {str(k): dist[k] for k in (3, 2, 1, 0)},
            "relevant": relevant,
        })
        tot_judged += n_judged
        tot_added += added
        tot_pooled += pooled_n

        flag = "" if unjudged == 0 else f"  ({unjudged} unjudged)"
        print(
            f"  {qid}  judged={n_judged:>3}  added={added:>2}  "
            f"3/2/1/0 = {dist[3]}/{dist[2]}/{dist[1]}/{dist[0]}{flag}"
        )

    out = {
        "_source_workbook": wb_path.name,
        "_scale": spec["_scale"],
        "_note": (
            "Graded relevance from expert review. `gain` is the 0-3 judgment. "
            "Items with gain 0 are judged-and-rejected, which is information: "
            "keep them so precision denominators and error analysis are honest. "
            "`added_by_expert` marks refs no retriever surfaced -- those are the "
            "recall failures worth studying."
        ),
        "n_queries": len(out_queries),
        "n_judgments": tot_judged,
        "n_added_by_expert": tot_added,
        "queries": out_queries,
    }
    Path(args.out).write_text(json.dumps(out, indent=2, ensure_ascii=False))

    print(f"\n{tot_judged} judgments across {len(out_queries)} queries "
          f"({tot_added} added by experts, {tot_pooled} candidates pooled)")
    n_pos = sum(
        1 for q in out_queries for r in q["relevant"] if r["gain"] > 0
    )
    print(f"{n_pos} judged relevant (gain > 0)")
    print(f"Wrote {args.out}")

    if rep.warnings:
        print(f"\n{len(rep.warnings)} warning(s) -- review before trusting these labels.")
        if args.strict:
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
