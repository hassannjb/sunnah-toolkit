"""Issue #3: matched-words chip strip is aggregated from STRONG results
only (with a fallback to WEAK when the strong bucket is empty).

We don't want to depend on a real cross-encoder here — the reranker eats
seconds of cold-load on first use and adds a HuggingFace network probe in
CI. Instead we monkey-patch `get_reranker` to return deterministic scores,
then drive a real `retrieve_union` candidate set through `_search_with_rerank`.
"""

from __future__ import annotations

import os

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

import pytest

from sunnah_toolkit.core import reranker as reranker_mod
from sunnah_toolkit.core import tools
from sunnah_toolkit.core.retrieval import retrieve_union


class _FakeReranker:
    """Score-by-position helper. The caller pre-computes a score map keyed
    by candidate hash so we can deterministically split strong/weak."""

    name = "fake"
    model_id = "fake/test"

    def __init__(self, score_fn):
        self._score_fn = score_fn

    def score(self, query, docs):
        return [self._score_fn(i, d) for i, d in enumerate(docs)]


@pytest.fixture(autouse=True)
def _clear_rerank_lru():
    """Each test stamps its own fake reranker; clear the lru between runs."""
    reranker_mod.get_reranker.cache_clear()
    yield
    reranker_mod.get_reranker.cache_clear()


def _install_fake(monkeypatch, score_fn, threshold: float = 0.0):
    monkeypatch.setattr(reranker_mod, "get_reranker", lambda name: _FakeReranker(score_fn))
    monkeypatch.setattr(reranker_mod, "default_reranker_name", lambda: "fake")
    monkeypatch.setattr(reranker_mod, "default_threshold", lambda: threshold)
    monkeypatch.setattr(reranker_mod, "reranker_enabled", lambda: True)


def test_matched_words_from_strong_only(monkeypatch):
    """If strong is non-empty, the aggregate excludes words seen only in
    weak. Setup: pick a query with multiple matched-skeleton variants;
    score the first half above threshold and the rest below."""
    query = "dua"
    candidates = retrieve_union(query, k_per_retriever=80)
    # Term-mode hadiths must have matched_words for this test to be meaningful.
    term_cands = [c for c in candidates if c.matched_words]
    assert len(term_cands) >= 4, "need enough term candidates for split"

    half = len(candidates) // 2
    # Score: first half gets +1.0 (strong), rest -1.0 (weak).
    def _score(i, _doc):
        return 1.0 if i < half else -1.0

    _install_fake(monkeypatch, _score, threshold=0.0)

    result = tools.search_hadith_term(query, limit=200, rerank=True)

    assert result["results"], "expected at least one strong row"
    # Build expected-words from the rows we actually placed in `strong`.
    expected_words: set[str] = set()
    for row in result["results"]:
        for w in row.get("matched_words", []):
            expected_words.add(w)

    aggregate_words = {item["word"] for item in result["matched_words"]}
    # Every word in the chip strip must come from a strong row.
    assert aggregate_words <= expected_words, (
        f"aggregate {aggregate_words - expected_words} not present in any strong row"
    )

    # And every word that *is* in a strong row should appear in the aggregate.
    assert expected_words <= aggregate_words

    # The weak rows may contain extra words; confirm at least one such word
    # exists and was correctly excluded from the aggregate.
    weak_only: set[str] = set()
    for row in result["results_weak"]:
        for w in row.get("matched_words", []):
            if w not in expected_words:
                weak_only.add(w)
    # If the corpus happens to have no weak-only words, the test still
    # passes on the subset assertions above — but log it for debugging.
    if weak_only:
        assert weak_only.isdisjoint(aggregate_words), (
            f"weak-only words leaked into aggregate: {weak_only & aggregate_words}"
        )


def test_matched_words_falls_back_to_weak_when_strong_empty(monkeypatch):
    """Strong bucket empty -> aggregate comes from weak rows so users still
    see chips."""
    query = "dua"
    candidates = retrieve_union(query, k_per_retriever=80)
    assert any(c.matched_words for c in candidates), "need term-mode hits"

    # Score everything below threshold so the strong bucket is empty.
    _install_fake(monkeypatch, lambda i, _d: -10.0, threshold=0.0)

    result = tools.search_hadith_term(query, limit=200, rerank=True)

    assert result["results"] == [], "strong bucket should be empty"
    assert result["results_weak"], "weak bucket should hold everything"
    # Fallback: aggregate is non-empty (would be empty under naive impl).
    assert result["matched_words"], "expected fallback to populate chip strip"

    # And every aggregate word should appear in at least one weak row.
    weak_words: set[str] = set()
    for row in result["results_weak"]:
        for w in row.get("matched_words", []):
            weak_words.add(w)
    assert {item["word"] for item in result["matched_words"]} <= weak_words
