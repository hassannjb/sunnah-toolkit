"""Query log: what gets recorded, what doesn't, and that it never breaks a request."""

from __future__ import annotations

import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from sunnah_toolkit.core import querylog, tools


def _fake_search(query, collection=None, limit=10):
    return {
        "query": query, "collection": collection, "reranker": "minilm-l6",
        "results": [{"slug": "bukhari", "hadith_number": "6312", "number": 6312, "score": 7.25}],
        "results_weak": [{"slug": "muslim", "hadith_number": "2711", "number": 2711, "score": 1.5}],
    }


def _fake_hadith(collection, number):
    return {"collection": collection, "number": number, "english": "..."}


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / "logs" / "queries.sqlite"
    monkeypatch.setenv("QUERY_LOG_PATH", str(path))
    monkeypatch.setattr(tools, "search_hadith_natural", _fake_search)
    monkeypatch.setattr(tools, "search_hadith", _fake_search)
    monkeypatch.setattr(tools, "get_hadith", _fake_hadith)
    return path


@pytest.fixture
def client():
    from sunnah_toolkit.api.app import create_app
    return TestClient(create_app())


def rows(path):
    querylog.flush()
    if not path.exists():
        return []
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return [dict(r) for r in conn.execute("SELECT * FROM queries ORDER BY id")]


WEB = {"X-Client": "web", "X-Session": "tab-1", "X-Search-Id": "s-1",
       "X-Search-Trigger": "typed", "X-UI-Mode": "auto",
       "cf-ray": "abc-YYZ", "cf-ipcountry": "CA"}


def test_web_search_is_recorded_with_context(db, client):
    r = client.get("/v1/search/natural", params={"query": "dua before sleep"}, headers=WEB)
    assert r.status_code == 200
    [row] = rows(db)
    assert row["source"] == "web" and row["local"] == 0
    assert row["session"] == "tab-1" and row["search_id"] == "s-1"
    assert row["trigger"] == "typed" and row["ui_mode"] == "auto"
    assert row["country"] == "CA"
    assert row["endpoint"] == "search_natural" and row["query"] == "dua before sleep"
    assert row["n_strong"] == 1 and row["n_weak"] == 1
    assert json.loads(row["top"]) == [["bukhari:6312", 7.25], ["muslim:2711", 1.5]]
    assert row["reranker"] == "minilm-l6"
    assert row["latency_ms"] is not None


def test_no_ip_or_user_agent_columns(db, client):
    client.get("/v1/search", params={"query": "anger"}, headers={"user-agent": "x"})
    [row] = rows(db)
    assert not {"ip", "user_agent", "ua"} & set(row)


def test_api_call_without_cloudflare_is_marked_local(db, client):
    client.get("/v1/search", params={"query": "anger"})
    [row] = rows(db)
    assert row["source"] == "api" and row["local"] == 1 and row["country"] is None


def test_warmup_is_not_recorded(db, client):
    client.get("/v1/search", params={"query": "warmup"}, headers={"X-Warmup": "1"})
    assert rows(db) == []


def test_web_hadith_fetch_only_counts_when_typed(db, client):
    # Row expand / copy: no search id, not a query.
    client.get("/v1/hadith/bukhari/1", headers={"X-Client": "web", "X-Session": "tab-1"})
    assert rows(db) == []
    # "Bukhari 1" typed into the search box.
    client.get("/v1/hadith/bukhari/1", headers=WEB)
    [row] = rows(db)
    assert row["endpoint"] == "get_hadith" and row["query"] == "bukhari 1"
    assert row["n_strong"] == 1 and json.loads(row["top"]) == [["bukhari:1", None]]


def test_mcp_tool_calls_are_recorded(db, monkeypatch):
    from sunnah_toolkit.core import text_format
    from sunnah_toolkit.mcp import server
    monkeypatch.setattr(text_format, "search_hadith", lambda result: "formatted")
    assert server.search_hadith("patience", limit=3) == "formatted"
    [row] = rows(db)
    assert row["source"] == "mcp" and row["endpoint"] == "search" and row["limit"] == 3


def test_disabled_without_path(monkeypatch, tmp_path, client):
    monkeypatch.delenv("QUERY_LOG_PATH", raising=False)
    monkeypatch.setattr(tools, "search_hadith", _fake_search)
    assert client.get("/v1/search", params={"query": "anger"}).status_code == 200
    assert not list(tmp_path.rglob("*.sqlite"))


def test_unwritable_log_never_breaks_search(monkeypatch, client):
    monkeypatch.setenv("QUERY_LOG_PATH", "/dev/null/nope/queries.sqlite")
    monkeypatch.setattr(tools, "search_hadith", _fake_search)
    r = client.get("/v1/search", params={"query": "anger"})
    assert r.status_code == 200 and r.json()["results"]
