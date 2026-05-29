"""Regression test for the hadith-number lookup fix.

Bug: `Library.get_hadith(slug, n)` used to key on `id_in_book` only, so a
user pasting `sunnah.com/bukhari:6312` in the Reference UI fetched a totally
different hadith (the one whose internal ordinal happened to be 6312, not
the one published on sunnah.com as #6312).

Fix: lookup now matches `hadith_number` (sunnah.com URL key) first and
falls back to `id_in_book`. Strings carry letter-suffix refs ("402b",
"1134b") through verbatim.
"""

from __future__ import annotations

import pytest

from sunnah_toolkit.core.data import load


@pytest.fixture(scope="module")
def lib():
    return load()


def test_bukhari_6312_resolves_to_sunnah_com_url(lib):
    """Canonical example from the user's bug screenshot.

    sunnah.com/bukhari:6312 is the pre-sleep dua ("Allahumma bismika
    amutu wa-ahya"). Before the fix, this resolved to whatever happened
    to sit at id_in_book=6312 (a hadith about the "width between the
    shoulders of a Kafir" with hadith_number=6551).
    """
    h = lib.get_hadith("bukhari", "6312")
    assert h is not None
    assert h.hadith_number == "6312"
    # Sleep dua content — not a verbatim quote, just a presence check.
    body = (h.english_text + " " + h.english_narrator).lower()
    assert "bismika" in body or "amutu" in body or "sleep" in body


def test_int_input_still_works(lib):
    """Old callers passing an int should still resolve sensibly."""
    h = lib.get_hadith("bukhari", 1)
    assert h is not None
    # hadith_number "1" is the Hadith of Intentions in Bukhari.
    assert h.hadith_number == "1"


def test_unknown_collection_returns_none(lib):
    assert lib.get_hadith("not-a-collection", "1") is None


def test_unknown_number_returns_none(lib):
    assert lib.get_hadith("bukhari", "999999") is None


def test_empty_string_returns_none(lib):
    assert lib.get_hadith("bukhari", "") is None


def test_letter_suffix_reference(lib):
    """Sunnah.com sometimes paginates a single matn as 1134a, 1134b, etc.
    The lookup must accept the suffixed form verbatim."""
    # Muslim 1134b is one of the canonical Arafah-fast hadiths the user
    # pasted during eval-set curation.
    h = lib.get_hadith("muslim", "1134b")
    assert h is not None
    # The upstream dump stores "1134 b" with a space; the lookup normalises
    # the URL form ("1134b") to find it. Either spelling must resolve.
    assert h.hadith_number.replace(" ", "").lower() == "1134b"
    # And the spaced form must also resolve to the same hadith.
    assert lib.get_hadith("muslim", "1134 b") is h


def test_bare_integer_resolves_to_first_lettered_variant(lib):
    """sunnah.com/muslim:375 maps to a hadith stored as "375 a" — the
    upstream dump paginates a single matn across lettered sub-rows. The
    URL has no letter, so a bare-integer lookup must land on the first
    variant (the one a click on sunnah.com would actually open)."""
    h = lib.get_hadith("muslim", "375")
    assert h is not None
    assert h.hadith_number.replace(" ", "").lower() == "375a"


def test_paired_range_first_part_resolves(lib):
    """Some hadith_numbers are stored as paired ranges like '272, 273'.
    A user typing the first part (which is what the sunnah.com URL uses)
    must still resolve to that hadith."""
    # Find any hadith with a comma in its hadith_number.
    for h in lib.iter_hadiths():
        if "," in h.hadith_number:
            first = h.hadith_number.split(",", 1)[0].strip()
            looked_up = lib.get_hadith(h.collection, first)
            assert looked_up is not None
            assert looked_up.hadith_number == h.hadith_number
            return
    pytest.skip("No paired-range hadith_number in this dataset snapshot.")
