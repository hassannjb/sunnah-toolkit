"""Auto-seed docs/eval/queries.json from sunnah.com chapter structure.

For each query, finds chapters whose English or Arabic name matches any of
the provided keyword patterns (SQL LIKE), then collects every hadith in
those chapters as a draft "relevant" set. The output is marked as auto-seeded
and must be reviewed/refined by a human before being used for any final
threshold/model decision.

Usage:
    python -m scripts.seed_eval_set

Writes:
    docs/eval/queries.json
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "hadith.sqlite"
OUT_PATH = ROOT / "docs" / "eval" / "queries.json"


# (query, mode_hint, [LIKE patterns for englishBabName OR arabicBabName])
# Patterns are matched case-insensitively via SQL LIKE with explicit % wildcards.
# Hardcoded for v1 — Issue #2 explicitly says we auto-seed then human-review.
QUERIES: list[tuple[str, str, list[str]]] = [
    # --- supplication / dua ---
    ("dua", "term", ["%supplication%", "%invocation%", "%dua%", "%دعاء%"]),
    ("supplication before sleep", "concept", ["%before sleep%", "%bed%", "%النوم%"]),
    ("dua for entering the toilet", "concept", ["%toilet%", "%relieving%", "%الخلاء%"]),
    ("dua after prayer", "concept", ["%after the prayer%", "%after prayer%", "%dhikr%", "%remembrance after%"]),
    # --- prayer / salah ---
    ("qunut", "term", ["%qunut%", "%witr%", "%قنوت%"]),
    ("witr prayer", "concept", ["%witr%", "%وتر%"]),
    ("tahajjud night prayer", "concept", ["%night prayer%", "%tahajjud%", "%قيام الليل%", "%تهجد%"]),
    ("friday prayer", "concept", ["%friday%", "%jumu%", "%الجمعة%"]),
    ("eclipse prayer", "concept", ["%eclipse%", "%kusoof%", "%الكسوف%", "%الخسوف%"]),
    # --- fasting / ramadan ---
    ("ramadan fasting", "concept", ["%fasting%", "%ramadan%", "%الصوم%", "%رمضان%"]),
    ("breaking the fast", "concept", ["%breaking the fast%", "%iftar%", "%الفطر%"]),
    ("laylat al-qadr", "term", ["%laylat al-qadr%", "%night of qadr%", "%القدر%"]),
    # --- character / akhlaq ---
    ("kindness to neighbors", "concept", ["%neighbor%", "%neighbour%", "%الجار%"]),
    ("controlling anger", "concept", ["%anger%", "%الغضب%"]),
    ("patience", "concept", ["%patience%", "%الصبر%"]),
    ("truthfulness", "concept", ["%truthful%", "%honesty%", "%lying%", "%الصدق%", "%الكذب%"]),
    ("backbiting", "concept", ["%backbit%", "%gheebah%", "%الغيبة%"]),
    # --- worship / pillars ---
    ("hajj pilgrimage", "concept", ["%hajj%", "%pilgrimage%", "%الحج%"]),
    ("zakat charity", "concept", ["%zakat%", "%zakah%", "%الزكاة%"]),
    # --- knowledge / iman ---
    ("seeking knowledge", "concept", ["%knowledge%", "%العلم%"]),
    ("seven sins major", "concept", ["%major sin%", "%great sin%", "%الكبائر%"]),
    # --- Arabic terms (skeleton match exercise) ---
    ("azan", "term", ["%adhan%", "%call to prayer%", "%الأذان%"]),
    ("ramazan", "term", ["%ramadan%", "%رمضان%"]),
    ("zikr", "term", ["%remembrance%", "%dhikr%", "%الذكر%"]),
    # --- Prophet's life ---
    ("the Prophet's farewell sermon", "concept", ["%farewell%", "%hajjat al-wadaa%", "%الوداع%"]),
]


def seed() -> dict:
    if not DB_PATH.exists():
        raise FileNotFoundError(f"SQLite dataset not found at {DB_PATH}")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        out_queries: list[dict] = []
        for query, mode_hint, patterns in QUERIES:
            chapter_keys: set[tuple[str, str]] = set()
            for pat in patterns:
                rows = conn.execute(
                    """
                    SELECT DISTINCT collection, bookNumber, babID
                    FROM HadithTable
                    WHERE englishBabName LIKE :p COLLATE NOCASE
                       OR arabicBabName LIKE :p
                    """,
                    {"p": pat},
                ).fetchall()
                for r in rows:
                    chapter_keys.add(
                        (r["collection"], f"{r['bookNumber']}|{r['babID']}")
                    )

            relevant: list[dict] = []
            seen: set[tuple[str, str]] = set()
            for (coll, book_bab) in chapter_keys:
                book, bab = book_bab.split("|", 1)
                rows = conn.execute(
                    """
                    SELECT collection, hadithNumber
                    FROM HadithTable
                    WHERE collection = ? AND bookNumber = ? AND babID = ?
                    """,
                    (coll, book, bab),
                ).fetchall()
                for r in rows:
                    key = (r["collection"], r["hadithNumber"] or "")
                    if key in seen or not key[1]:
                        continue
                    seen.add(key)
                    relevant.append({
                        "collection": r["collection"],
                        "hadith_number": r["hadithNumber"],
                    })

            relevant.sort(key=lambda d: (d["collection"], d["hadith_number"]))

            out_queries.append({
                "query": query,
                "mode_hint": mode_hint,
                "relevant": relevant,
            })
    finally:
        conn.close()

    return {
        "_status": "auto-seeded; needs human review",
        "_note": (
            "Chapter-derived relevance labels. Each query's `relevant` list is "
            "every hadith in chapters whose English or Arabic title matched the "
            "seed patterns in scripts/seed_eval_set.py. Many will be false "
            "positives (chapter contains adjacent material) or false negatives "
            "(target hadith lives in an oddly-named chapter). A human pass is "
            "required before this set is treated as ground truth."
        ),
        "queries": out_queries,
    }


def main() -> None:
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    data = seed()
    OUT_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    n = len(data["queries"])
    total_rel = sum(len(q["relevant"]) for q in data["queries"])
    print(f"Wrote {n} queries with {total_rel} total relevance labels to {OUT_PATH}")


if __name__ == "__main__":
    main()
