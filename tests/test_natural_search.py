"""Tests for the Natural-language search mode (Issue #4).

Three scenarios:
  1. Mocked router yields predictable variants → `search_hadith_natural`
     calls `retrieve_union_multi` with those variants, the rerank
     pipeline runs, and the response carries `mode_hint` + `variants`.
  2. `LLM_PROVIDER` unset → factory returns None → endpoint falls
     through to concept-mode semantic search with `fallback: "llm_unavailable"`.
  3. Schema: response has the expected keys when the router succeeds.

Mocking is done at the module-attribute level on `core.tools` because
that's the binding the function actually reads. We pin
HF_HUB_OFFLINE/TRANSFORMERS_OFFLINE before importing tools so the
bi-encoder load (triggered by `retrieve_union`) does not stall on a
network metadata probe in CI.
"""

from __future__ import annotations

import os

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

import pytest  # noqa: E402

from sunnah_toolkit.core import llm_router, tools  # noqa: E402
from sunnah_toolkit.core.llm_router import RouterOutput  # noqa: E402


@pytest.fixture(autouse=True)
def _clear_llm_provider(monkeypatch):
    """Each test sets its own LLM_PROVIDER state. Start from a known-clean slate."""
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


class _FakeRouter:
    def __init__(self, mode_hint: str, variants: list[str]) -> None:
        self._mode_hint = mode_hint
        self._variants = variants
        self.calls: list[str] = []

    def route(self, query: str) -> RouterOutput | None:
        self.calls.append(query)
        return RouterOutput(mode_hint=self._mode_hint, variants=list(self._variants))


def test_router_variants_flow_into_retrieve_union_multi(monkeypatch):
    fake = _FakeRouter(mode_hint="concept", variants=["controlling anger", "anger restraint"])
    monkeypatch.setattr(tools.llm_router, "get_router", lambda: fake)

    seen_variants: list[list[str]] = []

    def _fake_multi(variants, collection=None, k_per_retriever=100):
        seen_variants.append(list(variants))
        # Reuse a single-variant retrieval so we get real Candidate
        # objects without depending on the live LLM path.
        from sunnah_toolkit.core.retrieval import retrieve_union

        return retrieve_union(variants[0], collection=collection, k_per_retriever=k_per_retriever)

    monkeypatch.setattr(tools, "retrieve_union_multi", _fake_multi)

    resp = tools.search_hadith_natural("what did the Prophet say about anger?", limit=5)

    assert fake.calls == ["what did the Prophet say about anger?"]
    assert seen_variants == [["controlling anger", "anger restraint"]]
    assert resp["mode_hint"] == "concept"
    assert resp["variants"] == ["controlling anger", "anger restraint"]
    assert "fallback" not in resp
    assert "results" in resp
    assert "results_weak" in resp


def test_fallback_when_llm_provider_unset(monkeypatch):
    # No LLM_PROVIDER and no API key → get_router() returns None.
    assert llm_router.get_router() is None

    resp = tools.search_hadith_natural("kindness", limit=3)

    assert resp.get("fallback") == "llm_unavailable"
    assert resp.get("variants") == []
    # Concept-mode fallback still returns the normal rerank shape.
    assert "results" in resp
    assert "results_weak" in resp


def test_response_schema(monkeypatch):
    fake = _FakeRouter(mode_hint="keyword", variants=["patience"])
    monkeypatch.setattr(tools.llm_router, "get_router", lambda: fake)

    resp = tools.search_hadith_natural("teach me about patience", limit=5)

    expected_keys = {
        "query",
        "collection",
        "mode_hint",
        "limit",
        "pool_size",
        "total",
        "reranker",
        "threshold",
        "results",
        "results_weak",
        "matched_words",
        "variants",
    }
    assert expected_keys.issubset(resp.keys()), (
        f"missing keys: {expected_keys - resp.keys()}"
    )
    assert resp["mode_hint"] == "keyword"
    assert resp["variants"] == ["patience"]


def test_router_returning_none_triggers_router_failed_fallback(monkeypatch):
    class _DeadRouter:
        def route(self, query: str) -> RouterOutput | None:
            return None

    monkeypatch.setattr(tools.llm_router, "get_router", lambda: _DeadRouter())

    resp = tools.search_hadith_natural("anger", limit=3)
    assert resp.get("fallback") == "router_failed"
    assert resp.get("variants") == []
    assert "results" in resp


def test_get_router_unknown_provider_returns_none(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "made_up_provider")
    assert llm_router.get_router() is None


def test_get_router_anthropic_without_key_returns_none(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    # No ANTHROPIC_API_KEY -> AnthropicRouter.__init__ raises -> factory swallows.
    assert llm_router.get_router() is None
