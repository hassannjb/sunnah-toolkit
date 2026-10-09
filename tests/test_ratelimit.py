"""Per-client rate limits (api/ratelimit.py)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from sunnah_toolkit.api import ratelimit
from sunnah_toolkit.core import tools


def test_sliding_window_allows_then_blocks_then_recovers():
    w = ratelimit.SlidingWindow(2, window=60)
    assert w.hit("a", now=0) == 0 and w.hit("a", now=1) == 0
    assert w.hit("a", now=2) == 58
    assert w.hit("b", now=2) == 0  # other clients are unaffected
    assert w.hit("a", now=60.5) == 0


def test_is_search():
    assert ratelimit.is_search("GET", "/v1/search/natural")
    assert ratelimit.is_search("POST", "/mcp/")
    assert not ratelimit.is_search("GET", "/v1/hadith/bukhari/1")
    assert not ratelimit.is_search("GET", "/")


def _client(monkeypatch, **env):
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(tools, "search_hadith", lambda q, collection=None, limit=10: {"results": []})
    from sunnah_toolkit.api.app import create_app
    return TestClient(create_app())


def test_search_limit_is_per_cloudflare_ip(monkeypatch):
    c = _client(monkeypatch, RATE_LIMIT_SEARCH_PER_MIN="2")
    a, b = {"cf-connecting-ip": "203.0.113.1"}, {"cf-connecting-ip": "203.0.113.2"}
    assert [c.get("/v1/search", params={"query": "x"}, headers=a).status_code for _ in range(3)] == [200, 200, 429]
    r = c.get("/v1/search", params={"query": "x"}, headers=a)
    assert int(r.headers["retry-after"]) > 0 and "Too many requests" in r.json()["detail"]
    assert c.get("/v1/search", params={"query": "x"}, headers=b).status_code == 200
    # Non-search routes use the general budget, which is unset here.
    assert c.get("/healthz", headers=a).status_code == 200


def test_off_by_default(monkeypatch):
    monkeypatch.delenv("RATE_LIMIT_SEARCH_PER_MIN", raising=False)
    monkeypatch.delenv("RATE_LIMIT_PER_MIN", raising=False)
    c = _client(monkeypatch)
    assert all(c.get("/v1/search", params={"query": "x"}).status_code == 200 for _ in range(5))
