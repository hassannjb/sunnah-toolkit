"""Results are ordered by grade first, then relevance, strong before weak."""

from __future__ import annotations

from types import SimpleNamespace

from sunnah_toolkit.core.tools import _split_strong_weak


def _p(idx, grade, score, collection="abudawud"):
    h = SimpleNamespace(english_grade=grade, collection=collection)
    return SimpleNamespace(corpus_idx=idx, hadith=h), score


def _ids(pairs):
    return [c.corpus_idx for c, _ in pairs]


def _order(scored):
    strong, _ = _split_strong_weak(scored, 3.5, 100, grade_first=True)
    return _ids(strong)


def test_full_group_order():
    # Every row scores the same, and listed worst first, so only grade decides.
    rows = [
        (11, "Maudu'"),
        (10, ""),
        (9, "Sahih Mauquf"),
        (8, "Da'if Jiddan"),
        (7, "Da'if"),
        (6, "Hasan li ghairih"),
        (5, "Hasan"),
        (4, "Hasan Sahih"),
        (3, "Sahih Isnād"),
        (2, "Sahih"),
    ]
    scored = [_p(i, g, 5.0) for i, g in rows] + [_p(1, "Sahih", 5.0, "bukhari")]
    assert _order(scored) == list(range(1, 12))


def test_sahihayn_and_muttafaq_first():
    scored = [
        _p(1, "Sahih", 9.0, "abudawud"),
        _p(2, "Sahih", 4.0, "muslim"),
        _p(3, "Muttafaqun 'alayh", 5.0, "bulugh"),
    ]
    assert _order(scored) == [3, 2, 1]


def test_mursal_is_daif_not_end():
    scored = [_p(1, "", 9.0), _p(2, "Da'if mursal", 4.0), _p(3, "Sahih Mauquf", 8.0)]
    assert _order(scored) == [2, 3, 1]


def test_non_prophetic_sorted_by_own_grade():
    scored = [_p(1, "Da'if Maqtu'", 9.0), _p(2, "Sahih Mauquf", 4.0), _p(3, "Hasan Maqtu'", 6.0)]
    assert _order(scored) == [2, 3, 1]


def test_munkar_below_daif():
    assert _order([_p(1, "Munkar", 9.0), _p(2, "Da'if", 4.0)]) == [2, 1]


def test_same_group_falls_back_to_score():
    assert _order([_p(1, "Hasan", 4.0), _p(2, "hasan", 6.0)]) == [2, 1]


def test_weak_rows_are_grade_sorted_too_and_strong_stay_first():
    scored = [_p(1, "", 6.0), _p(2, "Da'if", 3.0), _p(3, "Sahih", 1.0)]
    strong, weak = _split_strong_weak(scored, 3.5, 10, grade_first=True)
    assert _ids(strong) == [1] and _ids(weak) == [3, 2]


def test_grade_first_applies_before_limit_cap():
    scored = [_p(1, "Da'if", 6.0), _p(2, "Hasan", 5.0), _p(3, "Sahih", 4.0)]
    strong, weak = _split_strong_weak(scored, 3.5, 2, grade_first=True)
    assert _ids(strong) == [3, 2] and _ids(weak) == [1]


def test_off_keeps_score_order():
    scored = [_p(1, "Da'if", 6.0), _p(2, "Sahih", 5.0)]
    strong, _ = _split_strong_weak(scored, 3.5, 10)
    assert _ids(strong) == [1, 2]
