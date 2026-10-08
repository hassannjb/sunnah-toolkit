"""Export the query log to CSV for analysis.

    python scripts/export_queries.py                       # all remote queries -> stdout
    python scripts/export_queries.py --since 2026-10-01 -o queries.csv
    python scripts/export_queries.py --include-local       # keep tests and local runs

A web search with several collections ticked is one call per collection;
--per-search folds those into one row (summed counts, first call's top hits).
"""

from __future__ import annotations

import argparse
import csv
import os
import sqlite3
import sys

DEFAULT_DB = os.environ.get("QUERY_LOG_PATH") or os.path.join(
    os.path.dirname(__file__), "..", "data", "logs", "queries.sqlite"
)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--since", help="UTC date or timestamp, inclusive (e.g. 2026-10-01)")
    ap.add_argument("--until", help="UTC date or timestamp, exclusive")
    ap.add_argument("--include-local", action="store_true", help="include calls that did not come through Cloudflare")
    ap.add_argument("--per-search", action="store_true", help="one row per web search instead of per API call")
    ap.add_argument("-o", "--out", help="CSV path (default: stdout)")
    args = ap.parse_args()

    if not os.path.exists(args.db):
        print(f"no query log at {args.db}", file=sys.stderr)
        return 1
    conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    where, params = [], []
    if args.since:
        where.append("ts >= ?"); params.append(args.since)
    if args.until:
        where.append("ts < ?"); params.append(args.until)
    if not args.include_local:
        where.append("local = 0")
    clause = ("WHERE " + " AND ".join(where)) if where else ""

    if args.per_search:
        sql = f"""
            SELECT MIN(ts) AS ts, source, session, country, trigger, ui_mode, endpoint, query,
                   collections, SUM(n_strong) AS n_strong, SUM(n_weak) AS n_weak,
                   MAX(latency_ms) AS latency_ms, MIN(top) AS top, GROUP_CONCAT(error) AS error
            FROM queries {clause}
            GROUP BY COALESCE(search_id, 'row-' || id)
            ORDER BY MIN(ts)"""
    else:
        sql = f"SELECT * FROM queries {clause} ORDER BY id"
    cur = conn.execute(sql, params)
    cols = [d[0] for d in cur.description]

    out = open(args.out, "w", newline="", encoding="utf-8") if args.out else sys.stdout
    w = csv.writer(out)
    w.writerow(cols)
    n = 0
    for row in cur:
        w.writerow([row[c] for c in cols])
        n += 1
    if args.out:
        out.close()
        print(f"wrote {n} rows to {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
