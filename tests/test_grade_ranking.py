"""Strong results are ordered by grade first; weak ones by relevance."""

from __future__ import annotations

from types import SimpleNamespace

from sunnah_toolkit.core.tools import _split_strong_weak


def _p(idx, grade, score):
    h = SimpleNamespace(english_grade=grade)
    return SimpleNamespace(corpus_idx=idx, hadith=h), score


def _ids(pairs):
    return [c.corpus_idx for c, _ in pairs]


SCORED = [  # reranker order, descending score; threshold 3.5
    _p(1, "Da'if", 6.0),
    _p(2, "Hasan", 5.8),
    _p(3, "Hasan Sahih", 5.5),
    _p(4, "Sahih", 5.1),
    _p(5, "", 4.0),            # ungraded (e.g. Riyad as-Salihin)
    _p(6, "Sahih", 3.0),       # below threshold
    _p(7, "Da'if", 2.0),
]


def test_grade_first_orders_strong_by_grade_then_score():
    strong, weak = _split_strong_weak(SCORED, 3.5, 10, grade_first=True)
    assert _ids(strong) == [4, 3, 2, 5, 1]
    assert _ids(weak) == [6, 7]


def test_grade_first_applies_before_limit_cap():
    # Without grade-first the daif at 6.0 would take one of the two slots.
    strong, weak = _split_strong_weak(SCORED, 3.5, 2, grade_first=True)
    assert _ids(strong) == [4, 3]
    assert _ids(weak)[:3] == [2, 5, 1]


def test_weak_rows_keep_relevance_order():
    scored = [_p(1, "Da'if", 2.0), _p(2, "Sahih", -1.0)]
    strong, weak = _split_strong_weak(scored, 3.5, 10, grade_first=True)
    assert strong == [] and _ids(weak) == [1, 2]


def test_off_keeps_score_order():
    strong, _ = _split_strong_weak(SCORED, 3.5, 10)
    assert _ids(strong) == [1, 2, 3, 4, 5]


def test_sahih_variants_rank_together():
    scored = [_p(1, "Sahih (Darussalam)", 4.0), _p(2, "Muttafaqun 'alayh", 5.0), _p(3, "Hasan", 6.0)]
    strong, _ = _split_strong_weak(scored, 3.5, 10, grade_first=True)
    assert _ids(strong) == [2, 1, 3]
