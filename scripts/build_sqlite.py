"""Convert sunnah.com's MariaDB HadithTable dump into a SQLite database.

Run from the project root:
    python -m scripts.build_sqlite [--dump-path PATH] [--out PATH]

Defaults read data/HadithTable.sql.gz and write data/hadith.sqlite. Stdlib-only
parser handles MariaDB single-quoted strings with backslash escapes
(\\n \\r \\t \\0 \\b \\Z \\' \\\\), the unquoted NULL literal, and numeric
columns. The [narrator id="..." role="..." tooltip="..."]name[/narrator] markup
in arabicText is preserved verbatim for downstream parsing in Stage J.
"""

from __future__ import annotations

import argparse
import gzip
import sqlite3
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DUMP = REPO_ROOT / "data" / "HadithTable.sql.gz"
DEFAULT_OUT = REPO_ROOT / "data" / "hadith.sqlite"

# Column order in the dump, matching the source CREATE TABLE.
COLUMNS = (
    "collection",
    "bookNumber",
    "babID",
    "englishBabNumber",
    "arabicBabNumber",
    "hadithNumber",
    "ourHadithNumber",
    "arabicURN",
    "arabicBabName",
    "arabicText",
    "arabicgrade1",
    "englishURN",
    "englishBabName",
    "englishText",
    "englishgrade1",
    "last_updated",
    "xrefs",
)

SCHEMA_SQL = """\
CREATE TABLE HadithTable (
  collection         TEXT    NOT NULL,
  bookNumber         TEXT    NOT NULL,
  babID              REAL    NOT NULL,
  englishBabNumber   TEXT,
  arabicBabNumber    TEXT,
  hadithNumber       TEXT    NOT NULL,
  ourHadithNumber    INTEGER NOT NULL,
  arabicURN          INTEGER NOT NULL PRIMARY KEY,
  arabicBabName      TEXT,
  arabicText         TEXT,
  arabicgrade1       TEXT    NOT NULL,
  englishURN         INTEGER NOT NULL UNIQUE,
  englishBabName     TEXT,
  englishText        TEXT,
  englishgrade1      TEXT    NOT NULL,
  last_updated       TEXT,
  xrefs              TEXT    NOT NULL
);
CREATE INDEX colbook_idx       ON HadithTable(collection, bookNumber);
CREATE INDEX hadith_number_idx ON HadithTable(hadithNumber);
CREATE INDEX collection_idx    ON HadithTable(collection);
"""

# MariaDB backslash escapes that appear inside single-quoted strings in dumps.
MARIADB_ESCAPES = {
    "\\\\": "\\",
    "\\'": "'",
    '\\"': '"',
    "\\n": "\n",
    "\\r": "\r",
    "\\t": "\t",
    "\\0": "\x00",
    "\\b": "\x08",
    "\\Z": "\x1a",
}

BATCH_SIZE = 1000


def parse_row_tuple(line: str) -> list:
    """Parse one MariaDB row tuple line into a list of Python values.

    A tuple line looks like ``('bukhari','1',1.00,...,'')`` optionally
    suffixed with a comma or a semicolon. Strings are single-quoted with
    backslash escapes; numbers and NULL are unquoted.
    """
    s = line.strip()
    if s.endswith(",") or s.endswith(";"):
        s = s[:-1]
    if not (s.startswith("(") and s.endswith(")")):
        raise ValueError(f"not a row tuple: {s[:80]!r}")
    inner = s[1:-1]

    fields: list = []
    i = 0
    n = len(inner)
    while i < n:
        # Skip whitespace + the comma separator between fields.
        while i < n and inner[i] in " ,":
            i += 1
        if i >= n:
            break

        if inner[i] == "'":
            # Quoted string: walk until the closing unescaped single quote.
            i += 1
            buf: list[str] = []
            while i < n:
                ch = inner[i]
                if ch == "\\" and i + 1 < n:
                    pair = inner[i : i + 2]
                    buf.append(MARIADB_ESCAPES.get(pair, pair))
                    i += 2
                elif ch == "'":
                    i += 1
                    break
                else:
                    buf.append(ch)
                    i += 1
            fields.append("".join(buf))
        else:
            # Unquoted literal: NULL, integer, or decimal.
            start = i
            while i < n and inner[i] != ",":
                i += 1
            raw = inner[start:i].strip()
            if raw.upper() == "NULL":
                fields.append(None)
            elif "." in raw:
                fields.append(float(raw))
            else:
                fields.append(int(raw))

    return fields


def iter_rows(dump_path: Path):
    """Yield parsed row tuples from the gzipped MariaDB dump."""
    in_values = False
    with gzip.open(dump_path, "rt", encoding="utf-8", errors="strict") as f:
        for line in f:
            stripped = line.lstrip()
            if stripped.startswith("INSERT INTO `HadithTable` VALUES"):
                in_values = True
                continue
            if not in_values:
                continue
            if not stripped.startswith("("):
                in_values = False
                continue
            yield parse_row_tuple(stripped)


def build_sqlite(dump_path: Path, out_path: Path) -> None:
    if out_path.exists():
        out_path.unlink()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(out_path)
    try:
        conn.executescript(SCHEMA_SQL)

        placeholders = ", ".join("?" * len(COLUMNS))
        insert_sql = (
            f"INSERT INTO HadithTable ({', '.join(COLUMNS)}) "
            f"VALUES ({placeholders})"
        )

        batch: list[list] = []
        inserted = 0
        for row in iter_rows(dump_path):
            if len(row) != len(COLUMNS):
                raise ValueError(
                    f"row has {len(row)} fields, expected {len(COLUMNS)}; "
                    f"first 3: {row[:3]!r}"
                )
            batch.append(row)
            if len(batch) >= BATCH_SIZE:
                conn.executemany(insert_sql, batch)
                inserted += len(batch)
                batch.clear()
        if batch:
            conn.executemany(insert_sql, batch)
            inserted += len(batch)

        conn.commit()

        row_count = conn.execute("SELECT COUNT(*) FROM HadithTable").fetchone()[0]
        if row_count != inserted:
            raise RuntimeError(
                f"insert count mismatch: streamed {inserted}, table has {row_count}"
            )

        print(f"Inserted {row_count:,} rows into {out_path}")
        print()
        print("Row count by collection:")
        for coll, n in conn.execute(
            "SELECT collection, COUNT(*) FROM HadithTable "
            "GROUP BY collection ORDER BY 2 DESC"
        ):
            print(f"  {coll:25s} {n:>6,}")
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dump-path",
        type=Path,
        default=DEFAULT_DUMP,
        help=f"gzipped MariaDB dump (default: {DEFAULT_DUMP.relative_to(REPO_ROOT)})",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUT,
        help=f"output SQLite path (default: {DEFAULT_OUT.relative_to(REPO_ROOT)})",
    )
    args = parser.parse_args(argv)

    if not args.dump_path.exists():
        print(f"error: dump not found at {args.dump_path}", file=sys.stderr)
        return 1

    build_sqlite(args.dump_path, args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
