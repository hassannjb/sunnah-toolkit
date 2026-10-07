"""Chapter/neighbor legs and RRF fusion (no model loads)."""

from __future__ import annotations

from types import SimpleNamespace

from sunnah_toolkit.core import chapters
from sunnah_toolkit.core.retrieval import Candidate
from sunnah_toolkit.core.tools import _heuristic_scores


def _c(idx, **kw):
    return Candidate(corpus_idx=idx, hadith=None, **kw)  # type: ignore[arg-type]


def test_generic_titles_filtered():
    for t in ("", "Chapter", "chapter 12", "Another version", "Something else about that"):
        assert chapters.is_generic(t), t
    assert not chapters.is_generic("Supplication When Going To Sleep")


def test_clean_title_strips_mishkat_section():
    assert chapters.clean_title("Prayer for Rain - Section 2") == "Prayer for Rain"


def test_group_chapters_keys_on_title_and_skips_generic():
    h = lambda col, cid, en, ar="": SimpleNamespace(
        collection=col, chapter_id=cid, english_bab_name=en, arabic_bab_name=ar
    )
    corpus = [
        h("bukhari", 1, "Sleep", "النوم"),
        h("bukhari", 1, "Sleep"),
        h("bukhari", 1, "Rain"),  # same truncated id, different title
        h("bukhari", 2, "Chapter"),
        h("muslim", None, "Sleep"),
    ]
    keys, members, arabic = chapters.group_chapters(corpus)
    assert keys == [("bukhari", 1, "Rain"), ("bukhari", 1, "Sleep"), ("muslim", -1, "Sleep")]
    assert members == [[2], [0, 1], [4]]
    assert arabic[1] == "النوم"


def test_weighted_fusion_counts_chapter_leg(monkeypatch):
    monkeypatch.delenv("FUSION", raising=False)
    a = _c(1, sources={"semantic"}, semantic_norm=0.6)
    b = _c(2, sources={"semantic", "chapter"}, semantic_norm=0.5, chapter_norm=1.0)
    order = [c.corpus_idx for c, _ in _heuristic_scores([a, b], "concept")]
    assert order == [2, 1]


def test_rrf_fusion_is_rank_based(monkeypatch):
    monkeypatch.setenv("FUSION", "rrf")
    # a wins bm25 by a mile but nothing else; b is second everywhere.
    a = _c(1, sources={"bm25"}, bm25=100.0)
    b = _c(2, sources={"bm25", "semantic", "term"}, bm25=1.0, semantic=0.9, term=1.0)
    c = _c(3, sources={"semantic", "term"}, semantic=0.95, term=2.0)
    scored = _heuristic_scores([a, b, c], "concept")
    assert [x.corpus_idx for x, _ in scored][0] in (2, 3)
    assert scored[-1][0].corpus_idx == 1
    assert all(s > 0 for _, s in scored)
