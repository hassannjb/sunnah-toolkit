"""In-memory hadith library loaded from data/hadith.sqlite at startup.

Backed by sunnah.com's official MariaDB dump (converted to SQLite by
scripts/build_sqlite.py). Preserves the [narrator id=... role=... tooltip=...]
markup verbatim in `Hadith.arabic` for downstream parsing.
"""

from __future__ import annotations

import functools
import json
import math
import re
import sqlite3
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Iterable

from rank_bm25 import BM25Okapi

from .translit import arabic_words, fold_index, fold_query, tokenize_query

DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "hadith.sqlite"


COLLECTION_TIER: dict[str, int] = {
    "bukhari": 0,
    "muslim": 1,
    "abudawud": 2,
    "tirmidhi": 3,
    "nasai": 4,
    "ibnmajah": 5,
    "ahmad": 6,
    "mishkat": 7,
    "riyadussalihin": 8,
    "adab": 9,
    "bulugh": 10,
    "shamail": 11,
    "forty": 12,
    "hisn": 13,
    "virtues": 14,
}

GRADE_TIER: dict[str, int] = {
    "sahih": 0,
    "hasan_sahih": 1,
    "hasan": 2,
    "daif": 3,
    "ungraded": 4,
    "maudu": 5,
}


_APOSTROPHES = str.maketrans({"'": "", "’": "", "‘": "", "`": "", "´": ""})


@functools.lru_cache(maxsize=None)
def normalize_grade(raw: str) -> str:
    """Map an englishgrade1 value to one of GRADE_TIER's keys."""
    if not raw:
        return "ungraded"

    stripped = raw.lstrip()
    if stripped.startswith("[{"):
        try:
            data = json.loads(stripped)
            if isinstance(data, list) and data:
                inner = data[0].get("grade", "") if isinstance(data[0], dict) else ""
                return normalize_grade(inner)
        except (json.JSONDecodeError, ValueError):
            pass

    folded = unicodedata.normalize("NFKD", raw).encode("ascii", "ignore").decode("ascii")
    folded = folded.translate(_APOSTROPHES).lower()

    if "maudu" in folded or "fabricated" in folded:
        return "maudu"
    if "hasan sahih" in folded or "sahih hasan" in folded:
        return "hasan_sahih"
    if "muttafaqun" in folded:
        return "sahih"
    if "sahih" in folded:
        return "sahih"
    if "hasan" in folded:
        return "hasan"
    if "daif" in folded or "weak" in folded:
        return "daif"
    return "ungraded"


# Hardcoded metadata for the 15 collections sunnah.com hosts. Keys are the
# slugs that appear in HadithTable.collection. Order here also defines the
# canonical iteration order for list_collections and the BM25 corpus.
COLLECTIONS_METADATA: dict[str, dict[str, str]] = {
    "bukhari": {
        "english_title": "Sahih al-Bukhari",
        "arabic_title": "صحيح البخاري",
        "english_author": "Imam Muhammad ibn Ismail al-Bukhari",
        "arabic_author": "الإمام محمد بن إسماعيل البخاري",
    },
    "muslim": {
        "english_title": "Sahih Muslim",
        "arabic_title": "صحيح مسلم",
        "english_author": "Imam Muslim ibn al-Hajjaj al-Naysaburi",
        "arabic_author": "الإمام مسلم بن الحجاج القشيري النيسابوري",
    },
    "abudawud": {
        "english_title": "Sunan Abi Dawud",
        "arabic_title": "سنن أبي داود",
        "english_author": "Imam Sulayman ibn al-Ash'ath Abu Dawud al-Sijistani",
        "arabic_author": "الإمام سليمان بن الأشعث أبو داود السجستاني",
    },
    "tirmidhi": {
        "english_title": "Jami' al-Tirmidhi",
        "arabic_title": "جامع الترمذي",
        "english_author": "Imam Abu Isa Muhammad ibn Isa al-Tirmidhi",
        "arabic_author": "الإمام أبو عيسى محمد بن عيسى الترمذي",
    },
    "nasai": {
        "english_title": "Sunan al-Nasa'i",
        "arabic_title": "سنن النسائي",
        "english_author": "Imam Ahmad ibn Shu'ayb al-Nasa'i",
        "arabic_author": "الإمام أبو عبد الرحمن أحمد بن شعيب النسائي",
    },
    "ibnmajah": {
        "english_title": "Sunan Ibn Majah",
        "arabic_title": "سنن ابن ماجه",
        "english_author": "Imam Muhammad ibn Yazid Ibn Majah al-Qazwini",
        "arabic_author": "الإمام محمد بن يزيد بن ماجه القزويني",
    },
    "ahmad": {
        "english_title": "Musnad Ahmad ibn Hanbal",
        "arabic_title": "مسند الإمام أحمد بن حنبل",
        "english_author": "Imam Ahmad ibn Hanbal",
        "arabic_author": "الإمام أحمد بن حنبل",
    },
    "mishkat": {
        "english_title": "Mishkat al-Masabih",
        "arabic_title": "مشكاة المصابيح",
        "english_author": "Al-Khatib Al-Tabrizi",
        "arabic_author": "الإمام الكاتب التبريزي",
    },
    "riyadussalihin": {
        "english_title": "Riyad as-Salihin",
        "arabic_title": "رياض الصالحين",
        "english_author": "Imam Yahya ibn Sharaf al-Nawawi",
        "arabic_author": "الإمام يحيى بن شرف النووي",
    },
    "shamail": {
        "english_title": "Shama'il al-Muhammadiyah",
        "arabic_title": "الشمائل المحمدية",
        "english_author": "Imam Abu Isa Muhammad ibn Isa al-Tirmidhi",
        "arabic_author": "الإمام أبو عيسى محمد بن عيسى الترمذي",
    },
    "bulugh": {
        "english_title": "Bulugh al-Maram",
        "arabic_title": "بلوغ المرام",
        "english_author": "Ibn Hajar al-Asqalani",
        "arabic_author": "الإمام ابن حجر العسقلاني",
    },
    "adab": {
        "english_title": "Al-Adab Al-Mufrad",
        "arabic_title": "الأدب المفرد",
        "english_author": "Imam Muhammad ibn Ismail al-Bukhari",
        "arabic_author": "الإمام محمد بن إسماعيل البخاري",
    },
    "forty": {
        "english_title": "Forty Hadith Collections",
        "arabic_title": "الأربعون",
        "english_author": "Various (Nawawi, Qudsi, Shah Waliullah)",
        "arabic_author": "علماء متعددون",
    },
    "hisn": {
        "english_title": "Hisn al-Muslim",
        "arabic_title": "حصن المسلم",
        "english_author": "Sa'id ibn Ali ibn Wahf al-Qahtani",
        "arabic_author": "سعيد بن علي بن وهف القحطاني",
    },
    "virtues": {
        "english_title": "Virtues",
        "arabic_title": "الفضائل",
        "english_author": "Various",
        "arabic_author": "علماء متعددون",
    },
}


_TOKEN_RE = re.compile(r"[A-Za-z0-9']+")

# Matches sunnah.com's [narrator id="..." role="..." tooltip="..."]name[/narrator]
# markup embedded in arabicText. Attribute order is consistent across the dump.
_NARRATOR_RE = re.compile(
    r'\[narrator\s+id="(\d+)"\s+role="([^"]*)"\s+tooltip="([^"]*)"\](.*?)\[/narrator\]',
    re.DOTALL,
)

# Brackets used as content markers in arabicText: [prematn] separates the
# isnad (chain) from the matn (the prophetic statement). There may be others
# in the future — strip generically.
_MARKER_RE = re.compile(r"\[(?!narrator\b|/narrator\b)[^\]]*\]")


def _tokenize(text: str) -> list[str]:
    return [tok for tok in _TOKEN_RE.findall(text.lower()) if len(tok) >= 2]


def parse_narrators(arabic_text: str) -> list[dict]:
    """Extract the structured narrator chain from a hadith's arabicText.

    Returns a list of dicts in chain order, one per [narrator id=... role=...
    tooltip=...]name[/narrator] tag found. Empty list if no markup is present.

    Each dict carries:
      - position    int  0-indexed order in the isnad
      - id          int  sunnah.com's narrator ID (stable across hadiths)
      - role        str  "first", "chain", or whatever sunnah.com assigns
      - tooltip     str  canonical Arabic name (often the fuller form)
      - inline_name str  the name as it appears inline in the text
    """
    out: list[dict] = []
    for i, m in enumerate(_NARRATOR_RE.finditer(arabic_text or "")):
        out.append({
            "position": i,
            "id": int(m.group(1)),
            "role": m.group(2),
            "tooltip": m.group(3),
            "inline_name": m.group(4).strip(),
        })
    return out


def strip_narrator_markup(arabic_text: str) -> str:
    """Return arabicText with all [narrator ...]...[/narrator] tags removed
    (keeping the inline name) and [prematn]/[postmatn] markers stripped.

    Intended for display in LLM-facing text where the markup would be noise.
    The structured chain (parse_narrators) carries the same data."""
    if not arabic_text:
        return ""
    s = _NARRATOR_RE.sub(lambda m: m.group(4), arabic_text)
    s = _MARKER_RE.sub("", s)
    return s.strip()


@dataclass(frozen=True, slots=True)
class Hadith:
    collection: str
    id_in_book: int            # 1-indexed ordinal in canonical sort within the collection
    global_id: int             # arabicURN — globally unique across all collections
    chapter_id: int | None     # int(babID); fractional info preserved in SQLite babID column
    arabic: str                # arabicText with [narrator id=...]...[/narrator] markup verbatim
    english_narrator: str      # leading "Narrated X:" line, if any (split off from englishText)
    english_text: str          # remainder of englishText after the narrator line is stripped
    # Fields added in Stage H, surfaced in tool outputs in Stage J:
    hadith_number: str = ""    # canonical citation string (e.g. "1", "402b", "272, 273")
    book_number: str = ""      # bookNumber within collection (usually integer-as-string)
    urn_arabic: int = 0
    urn_english: int = 0
    arabic_grade: str = ""     # Arabic grading (e.g. "صحيح")
    english_grade: str = ""    # English grading (e.g. "Sahih")
    grade_tier: int = 4        # GRADE_TIER index; default 4 == "ungraded"


@dataclass(frozen=True, slots=True)
class Chapter:
    id: int | None
    arabic_title: str
    english_title: str


@dataclass(frozen=True, slots=True)
class Collection:
    slug: str
    english_title: str
    arabic_title: str
    english_author: str
    arabic_author: str
    hadith_count: int


@dataclass
class Library:
    collections: dict[str, Collection] = field(default_factory=dict)
    hadiths: dict[str, list[Hadith]] = field(default_factory=dict)
    chapters: dict[str, list[Chapter]] = field(default_factory=dict)
    bm25: BM25Okapi | None = None
    bm25_corpus: list[Hadith] = field(default_factory=list)
    arabic_index: dict[str, list[tuple[int, str]]] = field(default_factory=dict)
    # Word -> number of hadiths containing it. Used to weight Arabic-term
    # matches: rarer words contribute more to the per-hadith score.
    arabic_word_doc_freq: dict[str, int] = field(default_factory=dict)

    def get_collection(self, slug: str) -> Collection | None:
        return self.collections.get(slug)

    def get_hadith(self, slug: str, id_in_book: int) -> Hadith | None:
        hadiths = self.hadiths.get(slug)
        if not hadiths:
            return None
        if 1 <= id_in_book <= len(hadiths):
            candidate = hadiths[id_in_book - 1]
            if candidate.id_in_book == id_in_book:
                return candidate
        for h in hadiths:
            if h.id_in_book == id_in_book:
                return h
        return None

    def iter_hadiths(self, collection: str | None = None) -> Iterable[Hadith]:
        if collection:
            yield from self.hadiths.get(collection, [])
            return
        for hs in self.hadiths.values():
            yield from hs

    def retrieve_keyword(
        self,
        query: str,
        collection: str | None = None,
        limit: int = 100,
    ) -> list[tuple[int, float]]:
        """BM25 over English text. Returns (corpus_idx, bm25_score) top-N
        with positive scores."""
        tokens = _tokenize(query)
        if not tokens or self.bm25 is None:
            return []
        scores = self.bm25.get_scores(tokens)
        candidates: list[tuple[int, float]] = []
        for idx, score in enumerate(scores):
            if score <= 0:
                continue
            if collection is not None and self.bm25_corpus[idx].collection != collection:
                continue
            candidates.append((idx, float(score)))
        candidates.sort(key=lambda p: p[1], reverse=True)
        return candidates[:limit]

    def _per_token_hits(
        self, query: str
    ) -> tuple[list[dict[int, set[str]]], list[str]]:
        """Issue #7 helper: per-query-token map of corpus_idx -> matched Arabic
        words. Tokens that hit nothing are dropped from the returned list (so
        an AND intersection isn't degraded by an unknown token). Also returns
        the surviving tokens for diagnostics.
        """
        tokens = tokenize_query(query)
        # Whole-string fallback when the tokenizer drops everything (e.g. the
        # input is a single connective word like "al"). Preserves single-word
        # behaviour for inputs the tokenizer wouldn't otherwise touch.
        if not tokens:
            tokens = [query.lower().strip()] if query and query.strip() else []
        per_token_hits: list[dict[int, set[str]]] = []
        kept_tokens: list[str] = []
        for tok in tokens:
            skels = fold_query(tok)
            if not skels:
                continue
            token_hits: dict[int, set[str]] = {}
            for skel in skels:
                for corpus_idx, arabic_word in self.arabic_index.get(skel, ()):
                    token_hits.setdefault(corpus_idx, set()).add(arabic_word)
            if token_hits:
                per_token_hits.append(token_hits)
                kept_tokens.append(tok)
        return per_token_hits, kept_tokens

    def term_match_logic(
        self, query: str, collection: str | None = None
    ) -> str | None:
        """Compute only the AND/OR-fallback flag for the current term query.

        Returns one of: "and", "and_fallback_to_or", or None when there is no
        usable token. Single-token queries return "and" (vacuously satisfied).
        Used by `_search_with_rerank` so the term-mode response can surface
        which logic was applied without re-running the heavy retrieve_union.
        """
        per_token_hits, _kept = self._per_token_hits(query)
        if not per_token_hits:
            return None
        # Restrict each per-token corpus_idx set to the collection filter so
        # the AND check honours the same scope the user sees.
        if collection is not None:
            filtered: list[set[int]] = []
            for t in per_token_hits:
                f = {i for i in t.keys() if self.bm25_corpus[i].collection == collection}
                if f:
                    filtered.append(f)
            keysets = filtered
        else:
            keysets = [set(t.keys()) for t in per_token_hits]
        if not keysets:
            return None
        intersect = keysets[0].copy()
        for ks in keysets[1:]:
            intersect &= ks
        return "and" if intersect else "and_fallback_to_or"

    def retrieve_term(
        self,
        query: str,
        collection: str | None = None,
        limit: int = 100,
    ) -> tuple[list[tuple[int, float, set[str]]], dict[str, int]]:
        """Arabic-skeleton match. Returns
        (list of (corpus_idx, score, matched_words) top-N, {word: freq}).

        Issue #7: multi-token queries are intersected (AND) across tokens —
        a hadith must contain at least one Arabic word matching every token.
        If AND yields zero hits the function falls back to OR (union),
        preserving previous single-word behaviour automatically.

        Per-hadith score is sum(1 / log(1 + global_word_doc_freq[w])) over
        matched words (union across query tokens). Rarer words contribute
        more; common skeletons (which collide widely) contribute very little.
        """
        per_token_hits, _kept = self._per_token_hits(query)
        if not per_token_hits:
            return [], {}

        # AND: intersection of corpus_idx sets across all (kept) tokens.
        intersect: set[int] = set(per_token_hits[0].keys())
        for t in per_token_hits[1:]:
            intersect &= t.keys()

        if intersect:
            target_keys = intersect
        else:
            # OR fallback: union of corpus_idx across all tokens.
            target_keys = set().union(*[set(t.keys()) for t in per_token_hits])

        if not target_keys:
            return [], {}

        results: list[tuple[int, float, set[str]]] = []
        word_freq: dict[str, int] = {}
        for corpus_idx in target_keys:
            h = self.bm25_corpus[corpus_idx]
            if collection is not None and h.collection != collection:
                continue
            matched_words: set[str] = set()
            for t in per_token_hits:
                matched_words |= t.get(corpus_idx, set())
            if not matched_words:
                continue
            score = 0.0
            for w in matched_words:
                df = self.arabic_word_doc_freq.get(w, 1)
                score += 1.0 / math.log(1 + df + 1)
                word_freq[w] = word_freq.get(w, 0) + 1
            results.append((corpus_idx, score, matched_words))

        results.sort(key=lambda t: t[1], reverse=True)
        return results[:limit], word_freq

    def search(
        self,
        query: str,
        collection: str | None = None,
        limit: int = 10,
    ) -> tuple[int, list[Hadith]]:
        """Returns (total_match_count, top-N hadiths) where total counts every
        hadith with BM25 score > 0 under the collection filter."""
        tokens = _tokenize(query)
        if not tokens or self.bm25 is None:
            return 0, []
        scores = self.bm25.get_scores(tokens)
        # ME-001: COLLECTION_TIER.get fallback so a future collection added
        # to COLLECTIONS_METADATA without a tier entry sorts last instead
        # of KeyError-ing at the first search query.
        last_tier = len(COLLECTION_TIER)
        ranked = sorted(
            (
                (score, h)
                for score, h in zip(scores, self.bm25_corpus)
                if score > 0 and (collection is None or h.collection == collection)
            ),
            key=lambda pair: (
                COLLECTION_TIER.get(pair[1].collection, last_tier),
                pair[1].grade_tier,
                -pair[0],
            ),
        )
        return len(ranked), [h for _, h in ranked[:limit]]

    def search_term(
        self,
        query: str,
        collection: str | None = None,
        limit: int = 20,
    ) -> tuple[int, dict[str, int], list[tuple[Hadith, set[str]]], str | None]:
        """Find hadiths whose Arabic text contains a word matching the query's
        consonant skeleton. Returns
        (total_match_count, {arabic_word: frequency},
         top-N (hadith, matched_words), match_logic).

        match_logic: "and" | "and_fallback_to_or" | None (no usable tokens).

        Backward-compat wrapper around retrieve_term: collects ALL matches,
        sorts by (collection, id_in_book) as before, then trims to `limit`.

        Issue #7: tuple grew from 3 to 4 elements. All in-tree callers
        (sunnah_toolkit.core.tools.search_hadith_term) are updated in the
        same change.
        """
        match_logic = self.term_match_logic(query, collection=collection)
        # Pull the full match set (limit = large) so we can produce the
        # legacy total/order.
        full, word_freq = self.retrieve_term(query, collection=collection, limit=10**9)
        if not full:
            return 0, {}, [], match_logic
        rows: list[tuple[Hadith, set[str]]] = [
            (self.bm25_corpus[idx], matched) for idx, _score, matched in full
        ]
        last_tier = len(COLLECTION_TIER)
        rows.sort(key=lambda pair: (
            COLLECTION_TIER.get(pair[0].collection, last_tier),
            pair[0].grade_tier,
            pair[0].id_in_book,
        ))
        return len(rows), word_freq, rows[:limit], match_logic


_MULTI_BLANK_LINES = re.compile(r"\n{3,}")
_PARA_TAG = re.compile(r"<p>")


def _clean_english_text(text: str) -> str:
    """Normalise sunnah.com englishText for clean display.

    Replaces ``<p>`` paragraph markers with a blank-line break, collapses
    runs of 3+ newlines down to a paragraph break, and trims surrounding
    whitespace. Preserves intentional indentation inside paragraphs.
    """
    if not text:
        return text
    s = _PARA_TAG.sub("\n", text)
    s = _MULTI_BLANK_LINES.sub("\n\n", s)
    return s.strip()


def _split_narrator(text: str) -> tuple[str, str]:
    """Split a leading 'Narrated X:' line off the english text.

    Sunnah.com bundles the narrator line into englishText (one block).
    AhmedBaset kept narrator and text separate. To preserve the existing tool
    output shape (separate narrator + english_text fields), we lift a short
    leading line ending with ':' into the narrator field, ignoring any
    leading ``<p>`` tags that sunnah.com sometimes prepends. The remaining
    body is normalised by ``_clean_english_text``.
    """
    if not text:
        return "", text
    work = text.lstrip()
    while work.startswith("<p>"):
        work = work[3:].lstrip()
    nl = work.find("\n")
    if nl == -1:
        return "", _clean_english_text(text)
    first_line = work[:nl].strip()
    if not first_line.endswith(":") or len(first_line) > 200:
        return "", _clean_english_text(text)
    rest = work[nl + 1 :]
    return first_line, _clean_english_text(rest)


@lru_cache(maxsize=1)
def load() -> Library:
    if not DB_PATH.exists():
        raise FileNotFoundError(
            f"SQLite dataset not found at {DB_PATH}. "
            "Run: python -m scripts.build_sqlite"
        )

    # ME-001: catch the "added a collection but forgot a tier entry" drift
    # at startup, not at the first user search query. Sort still tolerates
    # missing keys via COLLECTION_TIER.get(...) but we want loud feedback.
    missing_tier = sorted(set(COLLECTIONS_METADATA) - set(COLLECTION_TIER))
    if missing_tier:
        import warnings

        warnings.warn(
            f"COLLECTIONS_METADATA contains slugs missing from COLLECTION_TIER: "
            f"{missing_tier}. These will sort last in search results.",
            RuntimeWarning,
            stacklevel=2,
        )

    lib = Library()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        for slug in COLLECTIONS_METADATA:
            rows = conn.execute(
                """
                SELECT
                  bookNumber, babID, hadithNumber,
                  arabicURN, englishURN,
                  arabicBabName, arabicText, arabicgrade1,
                  englishBabName, englishText, englishgrade1
                FROM HadithTable
                WHERE collection = ?
                ORDER BY CAST(bookNumber AS INTEGER), bookNumber, babID, arabicURN
                """,
                (slug,),
            ).fetchall()

            if not rows:
                continue

            hadiths: list[Hadith] = []
            for idx, r in enumerate(rows, start=1):
                narrator, body = _split_narrator(r["englishText"] or "")
                english_grade = r["englishgrade1"] or ""
                hadiths.append(
                    Hadith(
                        collection=slug,
                        id_in_book=idx,
                        global_id=int(r["arabicURN"]),
                        chapter_id=int(r["babID"]) if r["babID"] is not None else None,
                        arabic=r["arabicText"] or "",
                        english_narrator=narrator,
                        english_text=body,
                        hadith_number=r["hadithNumber"] or "",
                        book_number=r["bookNumber"] or "",
                        urn_arabic=int(r["arabicURN"]),
                        urn_english=int(r["englishURN"]),
                        arabic_grade=r["arabicgrade1"] or "",
                        english_grade=english_grade,
                        grade_tier=GRADE_TIER[normalize_grade(english_grade)],
                    )
                )
            lib.hadiths[slug] = hadiths

            meta = COLLECTIONS_METADATA[slug]
            lib.collections[slug] = Collection(
                slug=slug,
                english_title=meta["english_title"],
                arabic_title=meta["arabic_title"],
                english_author=meta["english_author"],
                arabic_author=meta["arabic_author"],
                hadith_count=len(hadiths),
            )

            chapter_rows = conn.execute(
                """
                SELECT
                  bookNumber,
                  babID,
                  MAX(CASE WHEN trim(englishBabName) != '' THEN englishBabName END) AS englishBabName,
                  MAX(CASE WHEN trim(arabicBabName) != '' THEN arabicBabName END) AS arabicBabName
                FROM HadithTable
                WHERE collection = ?
                GROUP BY bookNumber, babID
                ORDER BY CAST(bookNumber AS INTEGER), bookNumber, babID
                """,
                (slug,),
            ).fetchall()
            lib.chapters[slug] = [
                Chapter(
                    id=int(cr["babID"]) if cr["babID"] is not None else None,
                    arabic_title=cr["arabicBabName"] or "",
                    english_title=cr["englishBabName"] or "",
                )
                for cr in chapter_rows
            ]
    finally:
        conn.close()

    corpus: list[Hadith] = []
    tokenized: list[list[str]] = []
    arabic_index: dict[str, list[tuple[int, str]]] = {}
    arabic_word_doc_freq: dict[str, int] = {}
    for hs in lib.hadiths.values():
        for h in hs:
            corpus_idx = len(corpus)
            corpus.append(h)
            tokenized.append(_tokenize(f"{h.english_narrator} {h.english_text}"))
            seen_words: set[str] = set()
            for word in arabic_words(h.arabic):
                if word in seen_words:
                    continue
                seen_words.add(word)
                arabic_word_doc_freq[word] = arabic_word_doc_freq.get(word, 0) + 1
                for skel in fold_index(word):
                    arabic_index.setdefault(skel, []).append((corpus_idx, word))
    lib.bm25_corpus = corpus
    lib.bm25 = BM25Okapi(tokenized)
    lib.arabic_index = arabic_index
    lib.arabic_word_doc_freq = arabic_word_doc_freq
    return lib
