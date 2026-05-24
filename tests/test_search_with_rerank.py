"""Unit-level contracts for `tools.search_with_rerank` (HI-006).

These tests stub the cross-encoder with a fake `Reranker` so they run in
seconds without a HF download. They exercise the seven invariants the
review flagged as untested:

  (a) reranker-disabled fallback uses the heuristic ordering
  (b) strong/weak split happens at the configured threshold
  (c) `limit` saturates strong at the requested count
  (d) matched_words aggregation comes from strong rows when strong is non-empty
      (this overlaps with test_term_matched_words.py — covered there)
  (e) reranker exception falls back to heuristic + sets reranker_status
  (f) empty-candidate input short-circuits to a zero-result response
  (g) collection filter combined with rerank only returns rows from that collection
"""

from __future__ import annotations

import os

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

import pytest

from sunnah_toolkit.core import reranker as reranker_mod
from sunnah_toolkit.core import tools
from sunnah_toolkit.core.retrieval import Candidate, retrieve_union


class _FakeReranker:
    name = "fake"
    model_id = "fake/test"

    def __init__(self, score_fn):
        self._score_fn = score_fn

    def score(self, query, docs):
        return [self._score_fn(i, d) for i, d in enumerate(docs)]


class _BoomReranker:
    name = "boom"
    model_id = "fake/boom"

    def score(self, query, docs):
        raise RuntimeError("forced reranker failure")


@pytest.fixture(autouse=True)
def _clear_rerank_singleton():
    reranker_mod.get_reranker.cache_clear()
    yield
    reranker_mod.get_reranker.cache_clear()


def _install_fake(monkeypatch, score_fn, threshold: float = 0.0):
    monkeypatch.setattr(reranker_mod, "get_reranker", lambda name: _FakeReranker(score_fn))
    monkeypatch.setattr(reranker_mod, "default_reranker_name", lambda: "fake")
    monkeypatch.setattr(reranker_mod, "default_threshold", lambda: threshold)
    monkeypatch.setattr(reranker_mod, "reranker_enabled", lambda: True)


def _install_boom(monkeypatch, threshold: float = 0.0):
    monkeypatch.setattr(reranker_mod, "get_reranker", lambda name: _BoomReranker())
    monkeypatch.setattr(reranker_mod, "default_reranker_name", lambda: "boom")
    monkeypatch.setattr(reranker_mod, "default_threshold", lambda: threshold)
    monkeypatch.setattr(reranker_mod, "reranker_enabled", lambda: True)


# (a) Reranker-disabled fallback.
def test_reranker_disabled_falls_back_to_heuristic(monkeypatch):
    monkeypatch.setattr(reranker_mod, "reranker_enabled", lambda: False)
    # `limit` high enough to fit every candidate so we can verify that no
    # row is shunted into the weak bucket purely by the limit cap.
    res = tools.search_with_rerank("prayer", mode_hint="concept", limit=10**6)
    assert res["reranker"] == "none"
    assert res["reranker_active"] is False
    assert res["reranker_status"] == "disabled"
    assert res["threshold"] is None  # no calibrated threshold without rerank
    assert res["results"], "heuristic still returns results"
    # With threshold=-inf and unbounded limit, every candidate is strong.
    assert res["results_weak"] == []


# (b) Strong/weak split at threshold.
def test_strong_weak_split_at_threshold(monkeypatch):
    # Score descending by candidate position; half land above 0.5.
    _install_fake(monkeypatch, score_fn=lambda i, _d: 1.0 - i * 0.01, threshold=0.5)
    res = tools.search_with_rerank("prayer", mode_hint="concept", limit=1000)
    assert res["results"], "strong bucket should not be empty"
    # Every strong row has score >= threshold; every weak row is below it.
    assert all(r["score"] >= 0.5 for r in res["results"])
    assert all(r["score"] < 0.5 for r in res["results_weak"])
    # Strong and weak are disjoint by construction.
    strong_keys = {(r["slug"], r["number"]) for r in res["results"]}
    weak_keys = {(r["slug"], r["number"]) for r in res["results_weak"]}
    assert strong_keys.isdisjoint(weak_keys)


# (c) Limit saturation: strong is capped at `limit` even if more would qualify.
def test_limit_saturates_strong(monkeypatch):
    # Every candidate scores above threshold so the only cap is `limit`.
    _install_fake(monkeypatch, score_fn=lambda i, _d: 1.0, threshold=0.0)
    res = tools.search_with_rerank("prayer", mode_hint="concept", limit=5)
    assert len(res["results"]) <= 5
    assert res["limit"] == 5
    # Overflow lands in weak rather than being silently dropped.
    assert len(res["results"]) + len(res["results_weak"]) == res["pool_size"]


# (e) Reranker exception -> heuristic fallback + status reflects failure.
def test_reranker_exception_falls_back(monkeypatch):
    _install_boom(monkeypatch, threshold=0.5)
    res = tools.search_with_rerank("prayer", mode_hint="concept", limit=10)
    assert res["reranker"] == "none"
    assert res["reranker_active"] is False
    assert res["reranker_status"].startswith("fell_back: RuntimeError")
    assert res["results"], "heuristic fallback should still produce results"
    # Threshold collapses to None in the fallback path so callers can
    # detect the degraded state.
    assert res["threshold"] is None


# (f) Empty candidate set -> zero-result response with the expected shape.
def test_empty_candidates_short_circuits(monkeypatch):
    _install_fake(monkeypatch, score_fn=lambda i, _d: 1.0, threshold=0.0)
    # A query that won't hit any of the three retrievers. The library
    # tokeniser strips junk; we use a string that yields no tokens.
    res = tools.search_with_rerank("", mode_hint="concept", limit=10)
    assert res["total"] == 0
    assert res["results"] == []
    assert res["results_weak"] == []
    assert res["pool_size"] == 0


# (g) Collection filter narrows results to that collection.
def test_collection_filter_restricts_results(monkeypatch):
    _install_fake(monkeypatch, score_fn=lambda i, _d: 1.0, threshold=0.0)
    res = tools.search_with_rerank(
        "prayer", mode_hint="concept", collection="bukhari", limit=50
    )
    assert res["results"], "expected at least one result in bukhari"
    for r in res["results"] + res["results_weak"]:
        assert r["slug"] == "bukhari"


# Unknown mode_hint is rejected (HI-005).
def test_unknown_mode_hint_raises():
    with pytest.raises(ValueError, match="Unknown mode_hint"):
        tools.search_with_rerank("prayer", mode_hint="conept", limit=10)
