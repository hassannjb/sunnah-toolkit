"""In-memory hadith library loaded from data/by_book/*.json at startup."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Iterable

from rank_bm25 import BM25Okapi

from .translit import arabic_words, fold_index, fold_query

DATA_ROOT = Path(__file__).resolve().parent.parent / "data" / "by_book"

_TOKEN_RE = re.compile(r"[A-Za-z0-9']+")


def _tokenize(text: str) -> list[str]:
    return [tok for tok in _TOKEN_RE.findall(text.lower()) if len(tok) >= 2]


@dataclass(frozen=True, slots=True)
class Hadith:
    collection: str
    id_in_book: int
    global_id: int
    chapter_id: int | None
    arabic: str
    english_narrator: str
    english_text: str


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
        ranked = sorted(
            (
                (score, h)
                for score, h in zip(scores, self.bm25_corpus)
                if score > 0 and (collection is None or h.collection == collection)
            ),
            key=lambda pair: pair[0],
            reverse=True,
        )
        return len(ranked), [h for _, h in ranked[:limit]]

    def search_term(
        self,
        query: str,
        collection: str | None = None,
        limit: int = 20,
    ) -> tuple[int, dict[str, int], list[tuple[Hadith, set[str]]]]:
        """Find hadiths whose Arabic text contains a word matching the query's
        consonant skeleton. Returns
        (total_match_count, {arabic_word: frequency}, top-N (hadith, matched_words))."""
        query_skeletons = fold_query(query)
        if not query_skeletons:
            return 0, {}, []

        matched_by_hadith: dict[int, set[str]] = {}
        for skel in query_skeletons:
            for corpus_idx, arabic_word in self.arabic_index.get(skel, ()):
                matched_by_hadith.setdefault(corpus_idx, set()).add(arabic_word)

        results: list[tuple[Hadith, set[str]]] = []
        word_freq: dict[str, int] = {}
        for corpus_idx, matched_words in matched_by_hadith.items():
            h = self.bm25_corpus[corpus_idx]
            if collection is not None and h.collection != collection:
                continue
            results.append((h, matched_words))
            for w in matched_words:
                word_freq[w] = word_freq.get(w, 0) + 1

        results.sort(key=lambda pair: (pair[0].collection, pair[0].id_in_book))
        return len(results), word_freq, results[:limit]


def _english_title(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return str(value.get("title", "") or value.get("text", ""))
    return ""


def _load_file(path: Path, slug: str) -> tuple[Collection, list[Chapter], list[Hadith]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    meta = raw["metadata"]
    collection = Collection(
        slug=slug,
        english_title=_english_title(meta.get("english", {}).get("title", "")),
        arabic_title=str(meta.get("arabic", {}).get("title", "")),
        english_author=str(meta.get("english", {}).get("author", "")),
        arabic_author=str(meta.get("arabic", {}).get("author", "")),
        hadith_count=int(meta.get("length", len(raw["hadiths"]))),
    )
    chapters = [
        Chapter(
            id=int(c["id"]) if c.get("id") is not None else None,
            arabic_title=str(c.get("arabic", "")),
            english_title=_english_title(c.get("english", "")),
        )
        for c in raw.get("chapters", [])
    ]
    hadiths = [
        Hadith(
            collection=slug,
            id_in_book=int(h["idInBook"]),
            global_id=int(h["id"]),
            chapter_id=int(h["chapterId"]) if h.get("chapterId") is not None else None,
            arabic=str(h.get("arabic", "")),
            english_narrator=str(h.get("english", {}).get("narrator", "")),
            english_text=str(h.get("english", {}).get("text", "")),
        )
        for h in raw.get("hadiths", [])
    ]
    return collection, chapters, hadiths


@lru_cache(maxsize=1)
def load() -> Library:
    if not DATA_ROOT.exists():
        raise FileNotFoundError(
            f"Dataset not found at {DATA_ROOT}. "
            "Run: python -m scripts.fetch_data"
        )
    lib = Library()
    for category_dir in sorted(DATA_ROOT.iterdir()):
        if not category_dir.is_dir():
            continue
        for json_file in sorted(category_dir.glob("*.json")):
            slug = json_file.stem
            collection, chapters, hadiths = _load_file(json_file, slug)
            lib.collections[slug] = collection
            lib.chapters[slug] = chapters
            lib.hadiths[slug] = hadiths

    corpus: list[Hadith] = []
    tokenized: list[list[str]] = []
    arabic_index: dict[str, list[tuple[int, str]]] = {}
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
                for skel in fold_index(word):
                    arabic_index.setdefault(skel, []).append((corpus_idx, word))
    lib.bm25_corpus = corpus
    lib.bm25 = BM25Okapi(tokenized)
    lib.arabic_index = arabic_index
    return lib
