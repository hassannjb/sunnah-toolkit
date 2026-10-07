"""LlamaCppRouter contract: parses llama-server output, fails soft on errors."""

from __future__ import annotations

import json

import httpx

from sunnah_toolkit.core import llm_router


def _router_with(handler) -> llm_router.LlamaCppRouter:
    r = llm_router.LlamaCppRouter()
    r._client = httpx.Client(transport=httpx.MockTransport(handler))
    return r


def _reply(content: str) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


def test_parses_variants_and_caps_at_max():
    payload = {"mode_hint": "concept", "variants": [" a ", "b", "", "c", "d"]}
    out = _router_with(lambda req: _reply(json.dumps(payload))).route("q")
    assert out is not None
    assert out.mode_hint == "concept"
    assert out.variants == ["a", "b", "c"]


def test_sends_schema_constrained_request():
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen.update(json.loads(req.content))
        return _reply('{"mode_hint": "term", "variants": ["qunut"]}')

    _router_with(handler).route("is qunut required in witr?")
    assert seen["response_format"]["type"] == "json_schema"
    assert seen["messages"][-1]["content"] == "is qunut required in witr?"


def test_server_error_returns_none():
    assert _router_with(lambda req: httpx.Response(503)).route("q") is None


def test_bad_json_returns_none():
    assert _router_with(lambda req: _reply("not json")).route("q") is None


def test_factory_selects_llamacpp(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "llamacpp")
    assert isinstance(llm_router.get_router(), llm_router.LlamaCppRouter)


def test_natural_search_tolerates_reference_mode(monkeypatch):
    from sunnah_toolkit.core import tools

    class _Router:
        def route(self, q):
            return llm_router.RouterOutput(mode_hint="reference", variants=["hajj rites"])

    monkeypatch.setattr(llm_router, "get_router", lambda: _Router())
    monkeypatch.setattr(tools.reranker_mod, "reranker_enabled", lambda: False)
    res = tools.search_hadith_natural("what are the rites of hajj", limit=3)
    assert res["mode_hint"] == "concept"
    assert res["variants"] == ["hajj rites"]
