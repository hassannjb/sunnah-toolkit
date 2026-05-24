"""Transliteration-tolerant matching between English and Arabic text.

Strategy: collapse both sides to a consonant skeleton. Index Arabic words with
case-aware z↔d substitution variants (for ض/ذ pronounced 'z' in Persian/Urdu
transliteration); fold user queries literally.
"""

from __future__ import annotations

import re

from unidecode import unidecode

_DIGRAPHS = [("kh", "k"), ("gh", "g"), ("dh", "d"), ("th", "t"), ("sh", "s")]
_STRIP_VOWELS = re.compile(r"[aeiouwyv]")
_NON_ALPHA = re.compile(r"[^a-z]")
_RUNS = re.compile(r"(.)\1+")

_ARABIC_WORD = re.compile(r"[ء-غف-يٱ-ۓ]+")
_ARABIC_DIACRITICS = re.compile(r"[ً-ٰٟۖ-ۭ]")


def _skeleton(text: str) -> set[str]:
    s = text.lower()
    for d, r in _DIGRAPHS:
        s = s.replace(d, r)
    out: set[str] = set()
    for taa in ("h", "t", ""):
        v = s.replace("@", taa)
        v = _STRIP_VOWELS.sub("", v)
        v = _NON_ALPHA.sub("", v)
        v = _RUNS.sub(r"\1", v)
        if v:
            out.add(v)
    return out


def fold_index(text: str) -> set[str]:
    """Generate skeletons for Arabic text to insert into the index.

    Substitutes 'D' (ض) and 'dh' (ذ) with 'z' as additional variants, since
    these letters are commonly transliterated 'z' in Persian/Urdu speakers
    (azan, ramazan). Plain 'd' (د) and plain 'z' (ز) are NOT substituted.
    """
    s = unidecode(text)
    variants = set(_skeleton(s))
    alt = s.replace("D", "z").replace("dh", "z")
    if alt != s:
        variants |= _skeleton(alt)
    return variants


def fold_query(text: str) -> set[str]:
    """Generate skeletons for a user query (literal, no z↔d expansion)."""
    return _skeleton(unidecode(text))


def arabic_words(text: str) -> list[str]:
    """Extract clean Arabic words from a hadith's Arabic text."""
    return _ARABIC_WORD.findall(_ARABIC_DIACRITICS.sub("", text))


# Issue #7: connectives we drop when tokenising multi-word term queries.
# Covers Persian "e" (izafat) and Arabic definite article "al" with its
# sun-letter assimilations. Conservative list — tune later if needed.
_QUERY_CONNECTIVES: frozenset[str] = frozenset({
    "e",                                         # Persian izafat ("dua e qunut")
    "ul",                                        # Arabic article enclitic ("laylatul")
    "al",                                        # Arabic definite article
    "ush", "ash",                                # sun-letter forms
    "an", "ar", "as", "at", "az", "ad",          # more sun-letter assimilations
})


def tokenize_query(query: str) -> list[str]:
    """Whitespace-split + lowercase + drop connectives.

    Issue #7. Returns the list of meaningful tokens for term-mode AND-logic.
    Single-word inputs remain a single-element list — single-word callers
    see no behavioural change.
    """
    if not query:
        return []
    return [t for t in query.lower().split() if t and t not in _QUERY_CONNECTIVES]
