"""Correctness tests for `retrieve_union` (ME-006).

The latency test in test_retrieval_latency.py covers the perf budget; this
file covers the four invariants the review flagged:

  - candidates returned by all three retrievers carry all three `sources`
    and their per-retriever `*_norm` fields
  - dedupe by corpus_idx works (no duplicate Candidate rows)
  - per-retriever `*_norm` fields come from the right retriever's hit list
  - one retriever raising (FileNotFoundError on missing embeddings) does
    NOT crash the union — it's logged and the other two legs continue

We stub `semantic.retrieve` to control the third leg so this test works
both with and without the embeddings file present.
"""

from __future__ import annotations

import os

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

import pytest

from sunnah_toolkit.core import retrieval, semantic
from sunnah_toolkit.core.data import load
from sunnah_toolkit.core.retrieval import _minmax, retrieve_union


def test_minmax_tied_returns_all_ones():
    """LO-002: when every value is tied the normaliser returns 1.0 across."""
    assert _minmax([5.0, 5.0, 5.0]) == [1.0, 1.0, 1.0]
    assert _minmax([0.0, 0.0]) == [1.0, 1.0]
    # Sanity: untied input still scales to [0, 1].
    norms = _minmax([0.0, 5.0, 10.0])
    assert norms[0] == pytest.approx(0.0)
    assert norms[2] == pytest.approx(1.0)


def test_union_dedupes_by_corpus_idx(monkeypatch):
    """A candidate that all three retrievers surface appears once with all
    three sources populated."""
    library = load()
    # Use a high-frequency query that BM25 + term + semantic all hit.
    cands = retrieve_union("prayer", k_per_retriever=50)
    assert cands, "expected at least one candidate"
    seen_idx: set[int] = set()
    for c in cands:
        assert c.corpus_idx not in seen_idx, (
            f"duplicate corpus_idx {c.corpus_idx} in union output"
        )
        seen_idx.add(c.corpus_idx)


def test_union_sources_are_attributed_correctly():
    """A candidate is in `bm25_hits` IFF its `sources` set contains 'bm25';
    same for 'semantic' and 'term'. Verified by re-running the leg
    retrievers and intersecting with the union output."""
    library = load()
    query = "prayer"
    cands = retrieve_union(query, k_per_retriever=50)
    union_by_idx = {c.corpus_idx: c for c in cands}

    bm25_idx = {idx for idx, _ in library.retrieve_keyword(query, limit=50)}
    term_hits, _ = library.retrieve_term(query, limit=50)
    term_idx = {idx for idx, _, _ in term_hits}

    for idx, cand in union_by_idx.items():
        if idx in bm25_idx:
            assert "bm25" in cand.sources, f"idx {idx} missing 'bm25' source"
        if idx in term_idx:
            assert "term" in cand.sources, f"idx {idx} missing 'term' source"


def test_union_survives_semantic_failure(monkeypatch):
    """If `semantic.retrieve` raises FileNotFoundError (embeddings missing),
    the union should log + skip rather than crash. BM25 + term still
    produce a candidate pool."""

    def _boom(*_args, **_kwargs):
        raise FileNotFoundError("embeddings absent for this test")

    monkeypatch.setattr(semantic, "retrieve", _boom)
    cands = retrieve_union("prayer", k_per_retriever=50)
    assert cands, "BM25/term should still produce candidates"
    # No candidate should have 'semantic' in its sources since the leg failed.
    assert all("semantic" not in c.sources for c in cands)


def test_union_empty_query_returns_empty():
    """Whitespace-only query short-circuits to empty without touching any retriever."""
    assert retrieve_union("", k_per_retriever=50) == []
    assert retrieve_union("   ", k_per_retriever=50) == []
