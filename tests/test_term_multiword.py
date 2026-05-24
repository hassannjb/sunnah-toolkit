"""Issue #7: multi-word Arabic term queries.

Verifies:
1. `tokenize_query` strips Persian/Arabic connectives.
2. `Library.search_term` ANDs across tokens (qunut + dua).
3. Flagship query "laylatul qadr" surfaces Laylat al-Qadr hadiths.
4. Single-word queries are unchanged (regression for the original "dua" query).
"""

from __future__ import annotations

import os

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

import pytest

from sunnah_toolkit.core.data import load
from sunnah_toolkit.core.translit import tokenize_query


def test_tokenize_drops_connectives():
    assert tokenize_query("dua e qunut") == ["dua", "qunut"]
    assert tokenize_query("youm e arafat") == ["youm", "arafat"]
    # All-lowercased; whitespace-split.
    assert tokenize_query("  Laylatul  qadr  ") == ["laylatul", "qadr"]
    # Single-word: unchanged (one token).
    assert tokenize_query("dua") == ["dua"]
    # Empty / whitespace-only: empty list.
    assert tokenize_query("") == []
    assert tokenize_query("   ") == []


def test_search_term_dua_e_qunut_intersects():
    """The dua-e-qunut query should AND the two skeleton families together —
    we should see hadiths that mention BOTH a دعا-family word AND a
    قنوت-family word in the Arabic text."""
    library = load()
    total, _word_freq, hits, match_logic = library.search_term(
        "dua e qunut", limit=50
    )
    assert total >= 1, "expected at least one dua-qunut hit"
    assert match_logic == "and"

    # Across all returned hadiths, at least one must match a qunut-family
    # word AND one must match a dua/duaa verb family. We treat the qunut
    # check as a tight skeleton match (يقنت / قنت / قنوت) and the dua check
    # as a relaxed prefix match against the د-ع-w / د-ع-y root family
    # (دعا, دعاء, يدعو, ادعو, الدعاء, دعوة, ادع, …).
    qunut_substrs = ("قنت", "قنوت")
    dua_substrs = ("دع",)  # د-ع covers دعا/دعاء/يدعو/الدعاء/دعوة/ادعو

    saw_qunut = False
    saw_dua = False
    for _h, matched in hits:
        if any(any(s in w for s in qunut_substrs) for w in matched):
            saw_qunut = True
        if any(any(s in w for s in dua_substrs) for w in matched):
            saw_dua = True
    assert saw_qunut, f"no qunut-family word surfaced; sample matched={[sorted(m) for _, m in hits[:3]]}"
    assert saw_dua, f"no dua-family word surfaced; sample matched={[sorted(m) for _, m in hits[:3]]}"


def test_search_term_laylatul_qadr_finds_canonical_hadiths():
    """laylatul qadr should surface Bukhari/Muslim Laylat al-Qadr narrations
    near the top of the result list."""
    library = load()
    total, _word_freq, hits, match_logic = library.search_term(
        "laylatul qadr", limit=50
    )
    assert total >= 10, f"expected >=10 Laylat al-Qadr hadiths, got {total}"
    assert match_logic in ("and", "and_fallback_to_or")

    top1_collection = hits[0][0].collection
    assert top1_collection in {"bukhari", "muslim"}, (
        f"top hit should be from bukhari/muslim, got {top1_collection}"
    )
    # Grade-tier 0 = sahih (Bukhari and Muslim hadiths are all grade-tier 0).
    assert hits[0][0].grade_tier == 0


def test_search_term_single_word_dua_regression():
    """The single-word `dua` query should still return results (no regression
    from the multi-word refactor). Capturing the top-3 references as a
    regression anchor."""
    library = load()
    total, _word_freq, hits, match_logic = library.search_term("dua", limit=20)
    assert total > 100, f"single-word dua should hit many hadiths, got {total}"
    assert match_logic == "and", "single-token query reports 'and'"
    assert len(hits) >= 3

    # The top hits should be from grade-tier 0 collections (sorted by
    # COLLECTION_TIER then grade_tier then id_in_book). Anchor the top-3
    # collections — we expect Bukhari first under the tier order.
    top_collections = [h.collection for h, _ in hits[:3]]
    assert top_collections[0] == "bukhari", (
        f"single-word dua top-1 collection regressed: got {top_collections[0]}"
    )
