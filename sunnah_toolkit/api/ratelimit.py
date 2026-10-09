"""Per-client request limits for the public instance.

Off unless RATE_LIMIT_SEARCH_PER_MIN / RATE_LIMIT_PER_MIN are set
(deploy/macos/run-api.sh sets them). A search costs ~2 s of CPU on the
dual-core host whatever `limit` is, so searches (and MCP calls, which run
them) get a tighter budget than page loads and hadith fetches.

The client is Cloudflare's CF-Connecting-IP, since behind the tunnel every
request arrives from localhost. Counts live in memory only and are never
logged: one process, and a restart forgiving everyone is fine.
"""

from __future__ import annotations

import math
import os
import threading
import time
from collections import deque


class SlidingWindow:
    """At most `limit` hits per `window` seconds for each key."""

    def __init__(self, limit: int, window: float = 60.0) -> None:
        self.limit = limit
        self.window = window
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def hit(self, key: str, now: float | None = None) -> int:
        """Count one request. Returns 0 if allowed, else seconds until it would be."""
        now = time.monotonic() if now is None else now
        cutoff = now - self.window
        with self._lock:
            q = self._hits.setdefault(key, deque())
            while q and q[0] <= cutoff:
                q.popleft()
            if len(q) >= self.limit:
                return max(1, math.ceil(q[0] - cutoff))
            q.append(now)
            if len(self._hits) > 10_000:
                self._prune(cutoff)
            return 0

    def _prune(self, cutoff: float) -> None:
        for k in [k for k, q in self._hits.items() if not q or q[-1] <= cutoff]:
            del self._hits[k]


def _env_int(name: str) -> int | None:
    raw = os.environ.get(name, "").strip()
    return int(raw) if raw.isdigit() and int(raw) > 0 else None


def from_env() -> tuple[SlidingWindow | None, SlidingWindow | None]:
    """(search limiter, general limiter); either is None when unset."""
    s, g = _env_int("RATE_LIMIT_SEARCH_PER_MIN"), _env_int("RATE_LIMIT_PER_MIN")
    return (SlidingWindow(s) if s else None, SlidingWindow(g) if g else None)


def is_search(method: str, path: str) -> bool:
    return path.startswith("/v1/search") or (path.startswith("/mcp") and method == "POST")


def client_key(headers, fallback: str | None) -> str:
    return (headers.get("cf-connecting-ip") or fallback or "unknown").strip()
