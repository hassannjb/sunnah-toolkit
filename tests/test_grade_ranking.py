"""Results are ordered by grade first, then relevance, strong before weak."""

from __future__ import annotations

from types import SimpleNamespace

from sunnah_toolkit.core.tools import _split_strong_weak


def _p(idx, grade, score):
    h = SimpleNamespace(english_grade=grade)
    return SimpleNamespace(corpus_idx=idx, hadith=h), score


def _ids(pairs):
    return [c.corpus_idx for c, _ in pairs]


SCORED = [  # reranker order, descending score; threshold 3.5
    _p(1, "", 6.5),            # ungraded (e.g. Riyad as-Salihin)
    _p(2, "Da'if", 6.0),
    _p(3, "Hasan", 5.8),
    _p(4, "Hasan Sahih", 5.5),
    _p(5, "Sahih li ghairih", 5.3),
    _p(6, "Sahih", 5.1),
    _p(7, "Da'if", 3.0),       # below threshold from here
    _p(8, "", 2.5),
    _p(9, "Sahih", 1.0),
]


def test_grade_first_orders_strong_by_grade_then_score():
    strong, weak = _split_strong_weak(SCORED, 3.5, 10, grade_first=True)
    assert _ids(strong) == [6, 5, 4, 3, 2, 1]


def test_weak_rows_are_grade_sorted_too():
    _, weak = _split_strong_weak(SCORED, 3.5, 10, grade_first=True)
    assert _ids(weak) == [9, 7, 8]


def test_grade_first_applies_before_limit_cap():
    strong, weak = _split_strong_weak(SCORED, 3.5, 2, grade_first=True)
    assert _ids(strong) == [6, 5]
    assert _ids(weak) == [4, 3, 2, 1, 9, 7, 8]


def test_ungraded_after_maudu():
    scored = [_p(1, "", 5.0), _p(2, "Maudu", 4.0), _p(3, "Da'if", 3.6)]
    strong, _ = _split_strong_weak(scored, 3.5, 10, grade_first=True)
    assert _ids(strong) == [3, 2, 1]


def test_qualified_grades_go_below_plain():
    scored = [
        _p(1, "Sahih Isnād", 6.0),
        _p(2, "Sahih Mauquf", 5.9),
        _p(3, "Sahih because of corroborating evidence]", 5.8),
        _p(4, "Sahih (Darussalam)", 4.0),
        _p(5, "Muttafaqun 'alayh", 3.9),
        _p(6, "Hasan", 7.0),
        _p(7, "Hasan li ghairih", 8.0),
    ]
    strong, _ = _split_strong_weak(scored, 3.5, 10, grade_first=True)
    assert _ids(strong) == [4, 5, 1, 2, 3, 6, 7]


def test_off_keeps_score_order():
    strong, _ = _split_strong_weak(SCORED, 3.5, 10)
    assert _ids(strong) == [1, 2, 3, 4, 5, 6]
