from sunnah_toolkit.core.data import GRADE_TIER, normalize_grade


def test_empty_string():
    assert normalize_grade("") == "ungraded"


def test_none_like_empty():
    assert normalize_grade("") == "ungraded"


def test_plain_sahih():
    assert normalize_grade("Sahih") == "sahih"


def test_sahih_with_macron():
    assert normalize_grade("Sahīh") == "sahih"


def test_hasan_sahih():
    assert normalize_grade("Hasan Sahih") == "hasan_sahih"


def test_daif_ascii_apostrophe():
    assert normalize_grade("Da'if") == "daif"


def test_daif_smart_apostrophe():
    assert normalize_grade("Da’if") == "daif"


def test_sahih_with_trailing_qualifier():
    assert normalize_grade("Sahih (Darussalam)]") == "sahih"


def test_albani_json_blob_sahih():
    raw = '[{"graded_by": "Al-Albani", "grade": "Sahih", "priority": 50}]'
    assert normalize_grade(raw) == "sahih"


def test_zubair_json_blob_macron_sahih():
    raw = '[{"graded_by": "Zubair `Aliza`i", "grade": "Sahīh", "priority": 50}]'
    assert normalize_grade(raw) == "sahih"


def test_zubair_json_blob_muttafaqun():
    raw = '[{"graded_by": "Zubair `Aliza`i", "grade": "Muttafaqun \'alayh", "priority": 60}]'
    assert normalize_grade(raw) == "sahih"


def test_bare_bracket_isnad_sahih():
    assert normalize_grade("[Its isnad is Sahih and the men are reliable]") == "sahih"


def test_maudu():
    assert normalize_grade("Maudu") == "maudu"


def test_fabricated_maps_to_maudu():
    assert normalize_grade("Fabricated") == "maudu"


def test_unknown_gibberish():
    assert normalize_grade("xyzqq") == "ungraded"


def test_all_outputs_in_grade_tier():
    for label in ("sahih", "hasan_sahih", "hasan", "daif", "ungraded", "maudu"):
        assert label in GRADE_TIER
