"""Protocol-agnostic hadith tools. Each function returns a dict.

The MCP server (sunnah_toolkit.mcp.server) renders these dicts to text via
sunnah_toolkit.core.text_format. The REST API (sunnah_toolkit.api) returns
them as JSON directly.

Error shape: {"error": str, "kind": "unknown_collection" | "not_found" | "unavailable"}.
"""

from __future__ import annotations

import random
from typing import Any

from . import semantic
from .data import Hadith, Library, load, parse_narrators


def _collection_meta(library: Library, slug: str) -> dict[str, Any]:
    col = library.get_collection(slug)
    return {
        "slug": slug,
        "english_title": col.english_title if col else slug,
        "arabic_title": col.arabic_title if col else "",
    }


def _hadith_dict(library: Library, h: Hadith) -> dict[str, Any]:
    col = library.get_collection(h.collection)
    # Reference URL uses the canonical citation number sunnah.com serves on.
    # For paired/range hadithNumbers like "272, 273", use the first number —
    # sunnah.com serves the row under that primary URL.
    raw_num = h.hadith_number or str(h.id_in_book)
    cite_id = raw_num.split(",", 1)[0].strip()
    return {
        "collection": h.collection,
        "number": h.id_in_book,
        "hadith_number": h.hadith_number,
        "english_title": col.english_title if col else h.collection,
        "narrator": h.english_narrator,
        "english_text": h.english_text,
        "arabic": h.arabic,
        "english_grade": h.english_grade,
        "arabic_grade": h.arabic_grade,
        "chain": parse_narrators(h.arabic),
        "urn": h.urn_english,
        "reference": f"sunnah.com/{h.collection}:{cite_id}",
    }


def _snippet(text: str, query: str, radius: int = 80) -> str:
    if not text:
        return ""
    idx = text.casefold().find(query.casefold())
    if idx == -1:
        return text[: radius * 2] + ("…" if len(text) > radius * 2 else "")
    start = max(0, idx - radius)
    end = min(len(text), idx + len(query) + radius)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(text) else ""
    return f"{prefix}{text[start:end]}{suffix}"


def list_collections() -> dict[str, Any]:
    library = load()
    collections = []
    for slug in sorted(library.collections.keys()):
        col = library.collections[slug]
        collections.append({
            "slug": slug,
            "english_title": col.english_title,
            "arabic_title": col.arabic_title,
            "english_author": col.english_author,
            "arabic_author": col.arabic_author,
            "hadith_count": len(library.hadiths[slug]),
        })
    return {"collections": collections}


def list_books(collection: str) -> dict[str, Any]:
    library = load()
    col = library.get_collection(collection)
    if not col:
        return {"error": f"Unknown collection: {collection!r}", "kind": "unknown_collection"}

    chapters = library.chapters.get(collection, [])
    return {
        "collection": collection,
        "english_title": col.english_title,
        "arabic_title": col.arabic_title,
        "chapters": [
            {"id": ch.id, "english_title": ch.english_title, "arabic_title": ch.arabic_title}
            for ch in chapters
        ],
    }


def get_hadith(collection: str, number: int) -> dict[str, Any]:
    library = load()
    if collection not in library.collections:
        return {"error": f"Unknown collection: {collection!r}", "kind": "unknown_collection"}

    h = library.get_hadith(collection, number)
    if not h:
        total = len(library.hadiths[collection])
        return {
            "error": f"No hadith #{number} in {collection}. Valid range: 1..{total}.",
            "kind": "not_found",
        }
    return _hadith_dict(library, h)


def search_hadith(query: str, collection: str | None = None, limit: int = 10) -> dict[str, Any]:
    library = load()
    limit = max(1, min(limit, 50))

    if collection and collection not in library.collections:
        return {"error": f"Unknown collection: {collection!r}", "kind": "unknown_collection"}

    total, hits = library.search(query, collection=collection, limit=limit)
    return {
        "query": query,
        "collection": collection,
        "total": total,
        "limit": limit,
        "results": [
            {**_collection_meta(library, h.collection),
             "number": h.id_in_book,
             "hadith_number": h.hadith_number,
             "english_grade": h.english_grade,
             "snippet": _snippet(h.english_text, query)}
            for h in hits
        ],
    }


def search_hadith_term(term: str, collection: str | None = None, limit: int = 20) -> dict[str, Any]:
    library = load()
    limit = max(1, min(limit, 100))

    if collection and collection not in library.collections:
        return {"error": f"Unknown collection: {collection!r}", "kind": "unknown_collection"}

    total, word_freq, hits = library.search_term(term, collection=collection, limit=limit)
    matched_words = sorted(
        ({"word": w, "count": n} for w, n in word_freq.items()),
        key=lambda x: (-x["count"], x["word"]),
    )
    return {
        "query": term,
        "collection": collection,
        "total": total,
        "limit": limit,
        "matched_words": matched_words,
        "results": [
            {**_collection_meta(library, h.collection),
             "number": h.id_in_book,
             "hadith_number": h.hadith_number,
             "english_grade": h.english_grade,
             "matched_words": sorted(matched),
             "snippet": (h.english_text[:140] + "…") if len(h.english_text) > 140 else h.english_text}
            for h, matched in hits
        ],
    }


def search_hadith_semantic(query: str, collection: str | None = None, limit: int = 10) -> dict[str, Any]:
    library = load()
    limit = max(1, min(limit, 50))

    if collection and collection not in library.collections:
        return {"error": f"Unknown collection: {collection!r}", "kind": "unknown_collection"}

    try:
        results = semantic.search(query, collection=collection, limit=limit)
    except FileNotFoundError as e:
        return {"error": f"Semantic search unavailable: {e}", "kind": "unavailable"}

    return {
        "query": query,
        "collection": collection,
        "limit": limit,
        "results": [
            {**_collection_meta(library, h.collection),
             "number": h.id_in_book,
             "hadith_number": h.hadith_number,
             "english_grade": h.english_grade,
             "similarity": float(score),
             "snippet": (h.english_text[:200] + "…") if len(h.english_text) > 200 else h.english_text}
            for h, score in results
        ],
    }


def random_hadith(collection: str | None = None) -> dict[str, Any]:
    library = load()
    if collection and collection not in library.collections:
        return {"error": f"Unknown collection: {collection!r}", "kind": "unknown_collection"}

    pool = library.hadiths[collection] if collection else list(library.iter_hadiths())
    if not pool:
        return {"error": "No hadiths available.", "kind": "not_found"}
    return _hadith_dict(library, random.choice(pool))
