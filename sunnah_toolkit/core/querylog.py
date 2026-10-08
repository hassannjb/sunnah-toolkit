"""Append-only log of search queries, kept for later analysis.

Off unless QUERY_LOG_PATH is set (deploy/macos/run-api.sh sets it), so tests
and local runs write nothing. Rows are written by one background thread;
a failure to log is reported and swallowed, never raised into a request.

No IP addresses or user agents are stored. Request-level details (where it
came from, an anonymous per-tab session id, Cloudflare's country code) are
collected by the middleware in api/app.py into `request_meta`.
"""

from __future__ import annotations

import contextvars
import json
import logging
import os
import queue
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any

_log = logging.getLogger(__name__)

# Filled per HTTP request by the middleware in api/app.py. MCP tool calls run
# outside that context, so they pass source="mcp" explicitly.
request_meta: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "request_meta", default=None
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS queries (
    id          INTEGER PRIMARY KEY,
    ts          TEXT NOT NULL,     -- UTC, ISO 8601, when the request started
    source      TEXT NOT NULL,     -- web | api | mcp
    local       INTEGER NOT NULL,  -- 1 = did not come through Cloudflare (tests, local runs)
    session     TEXT,              -- random id per browser tab (web only)
    country     TEXT,              -- Cloudflare CF-IPCountry, e.g. CA
    search_id   TEXT,              -- groups the per-collection calls of one web search
    trigger     TEXT,              -- web: typed | link (page opened with ?q=) | back (history navigation)
    ui_mode     TEXT,              -- web: mode chosen in the UI (auto, natural, term, ...)
    endpoint    TEXT NOT NULL,     -- search | search_term | search_semantic | search_natural | get_hadith
    query       TEXT NOT NULL,
    collection  TEXT,              -- collection this call was limited to
    collections TEXT,              -- web: every collection ticked for the search, comma-separated
    "limit"     INTEGER,
    n_strong    INTEGER,
    n_weak      INTEGER,
    top         TEXT,              -- JSON [["bukhari:1", score], ...], first 10 shown
    reranker    TEXT,
    latency_ms  INTEGER,
    error       TEXT
);
CREATE INDEX IF NOT EXISTS queries_ts ON queries(ts);
"""

_COLUMNS = (
    "ts", "source", "local", "session", "country", "search_id", "trigger", "ui_mode",
    "endpoint", "query", "collection", "collections", "limit", "n_strong", "n_weak",
    "top", "reranker", "latency_ms", "error",
)
_TOP_N = 10


def log_path() -> str | None:
    return os.environ.get("QUERY_LOG_PATH", "").strip() or None


def connect(path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    return conn


class _Writer:
    def __init__(self, path: str) -> None:
        self.path = path
        self.q: queue.Queue[dict[str, Any] | None] = queue.Queue(maxsize=10_000)
        self.thread = threading.Thread(target=self._run, name="querylog", daemon=True)
        self.thread.start()

    def _run(self) -> None:
        try:
            conn = connect(self.path)
        except Exception as e:
            _log.warning("query log disabled, cannot open %s: %s", self.path, e)
            return
        cols = ", ".join(f'"{c}"' for c in _COLUMNS)
        marks = ", ".join("?" for _ in _COLUMNS)
        sql = f"INSERT INTO queries ({cols}) VALUES ({marks})"
        while True:
            row = self.q.get()
            if row is None:
                break
            try:
                conn.execute(sql, [row.get(c) for c in _COLUMNS])
                conn.commit()
            except Exception as e:
                _log.warning("query log write failed: %s", e)
            finally:
                self.q.task_done()

    def put(self, row: dict[str, Any]) -> None:
        try:
            self.q.put_nowait(row)
        except queue.Full:
            _log.warning("query log queue full, dropping a row")


_writer: _Writer | None = None
_writer_lock = threading.Lock()


def _get_writer() -> _Writer | None:
    global _writer
    path = log_path()
    if not path:
        return None
    with _writer_lock:
        if _writer is None or _writer.path != path:
            _writer = _Writer(path)
        return _writer


def flush() -> None:
    """Block until queued rows are written (tests use this)."""
    if _writer is not None:
        _writer.q.join()


def _ref(row: dict[str, Any]) -> str:
    return f"{row.get('slug') or row.get('collection')}:{row.get('hadith_number') or row.get('number')}"


def _summary(result: dict[str, Any] | None) -> dict[str, Any]:
    if not result or "error" in result:
        return {}
    if "results" not in result:  # a single hadith (get_hadith)
        return {"n_strong": 1, "n_weak": 0, "top": json.dumps([[_ref(result), None]])}
    strong = result.get("results") or []
    weak = result.get("results_weak") or []
    shown = (strong + weak)[:_TOP_N]
    top = [[_ref(r), round(float(r.get("score", r.get("similarity", 0.0)) or 0.0), 3)] for r in shown]
    return {
        "n_strong": len(strong),
        "n_weak": len(weak),
        "top": json.dumps(top),
        "reranker": result.get("reranker"),
    }


def timed(endpoint: str, query: str, fn, *, source: str | None = None, **fields: Any) -> dict[str, Any]:
    """Run `fn()`, record it with its latency, and return its result."""
    import time
    started = _now()
    t0 = time.perf_counter()
    try:
        result = fn()
    except Exception as e:
        record(endpoint, query, error=f"{type(e).__name__}: {e}", source=source, started=started,
               latency_ms=(time.perf_counter() - t0) * 1000, **fields)
        raise
    record(endpoint, query, result=result, source=source, started=started,
           latency_ms=(time.perf_counter() - t0) * 1000, **fields)
    return result


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def record(
    endpoint: str,
    query: str,
    *,
    result: dict[str, Any] | None = None,
    collection: str | None = None,
    limit: int | None = None,
    latency_ms: float | None = None,
    error: str | None = None,
    source: str | None = None,
    started: str | None = None,
) -> None:
    """Queue one row. Never raises. `ts` is when the request started."""
    try:
        meta = request_meta.get() or {}
        if meta.get("skip"):
            return
        writer = _get_writer()
        if writer is None:
            return
        if result and "error" in result and not error:
            error = str(result["error"])
        row = {
            "ts": started or _now(),
            "source": source or meta.get("source") or "api",
            "local": int(meta.get("local", 0)),
            "session": meta.get("session"),
            "country": meta.get("country"),
            "search_id": meta.get("search_id"),
            "trigger": meta.get("trigger"),
            "ui_mode": meta.get("ui_mode"),
            "collections": meta.get("collections"),
            "endpoint": endpoint,
            "query": query,
            "collection": collection,
            "limit": limit,
            "latency_ms": int(latency_ms) if latency_ms is not None else None,
            "error": error,
            **_summary(result),
        }
        writer.put(row)
    except Exception as e:
        _log.warning("query log record failed: %s", e)
