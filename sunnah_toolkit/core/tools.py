"""Pure-Python implementations of the hadith tools.

These functions return human-readable text and are called from the MCP
server (sunnah_toolkit.mcp.server) and the REST API (sunnah_toolkit.api).
Keep them dependency-free of any protocol layer.
"""

from __future__ import annotations

import random

from . import semantic
from .data import load
from .format import (
    format_collection_summary,
    format_hadith,
    format_search_result,
    format_semantic_result,
    format_term_results,
)


def list_collections() -> str:
    library = load()
    lines = ["Available hadith collections:", ""]
    for slug in sorted(library.collections.keys()):
        col = library.collections[slug]
        count = len(library.hadiths[slug])
        lines.append(format_collection_summary(col, count))
    return "\n".join(lines)


def list_books(collection: str) -> str:
    library = load()
    col = library.get_collection(collection)
    if not col:
        return f"Unknown collection: {collection!r}. Try `list_collections` for valid slugs."

    chapters = library.chapters.get(collection, [])
    lines = [f"{col.english_title} ({col.arabic_title}) — {len(chapters)} chapters:", ""]
    for ch in chapters:
        idx = f"{ch.id}" if ch.id is not None else "—"
        lines.append(f"  {idx:>4}  {ch.english_title}")
    return "\n".join(lines)


def get_hadith(collection: str, number: int) -> str:
    library = load()
    if collection not in library.collections:
        return f"Unknown collection: {collection!r}. Try `list_collections` for valid slugs."

    h = library.get_hadith(collection, number)
    if not h:
        total = len(library.hadiths[collection])
        return (
            f"No hadith #{number} in {collection}. "
            f"Valid range: 1..{total}."
        )
    return format_hadith(h, library)


def search_hadith(query: str, collection: str | None = None, limit: int = 10) -> str:
    library = load()
    limit = max(1, min(limit, 50))

    if collection and collection not in library.collections:
        return f"Unknown collection: {collection!r}. Try `list_collections`."

    total, results = library.search(query, collection=collection, limit=limit)
    if not results:
        scope = f" in {collection}" if collection else ""
        return f"No matches for {query!r}{scope}."

    scope = f" in {collection}" if collection else ""
    lines = [f"Found {total} hadith(s){scope} matching {query!r}."]
    if total > len(results):
        lines.append(f"Showing first {len(results)}:")
    lines.append("")
    for h in results:
        lines.append(format_search_result(h, library, query))
    return "\n".join(lines)


def search_hadith_term(term: str, collection: str | None = None, limit: int = 20) -> str:
    library = load()
    limit = max(1, min(limit, 100))

    if collection and collection not in library.collections:
        return f"Unknown collection: {collection!r}. Try `list_collections`."

    total, word_freq, results = library.search_term(term, collection=collection, limit=limit)
    return format_term_results(term, total, word_freq, results, library, collection)


def search_hadith_semantic(query: str, collection: str | None = None, limit: int = 10) -> str:
    library = load()
    limit = max(1, min(limit, 50))

    if collection and collection not in library.collections:
        return f"Unknown collection: {collection!r}. Try `list_collections`."

    try:
        results = semantic.search(query, collection=collection, limit=limit)
    except FileNotFoundError as e:
        return f"Semantic search unavailable: {e}"

    if not results:
        scope = f" in {collection}" if collection else ""
        return f"No semantic matches for {query!r}{scope}."

    scope = f" in {collection}" if collection else ""
    lines = [
        f"Top {len(results)} semantic match(es) for {query!r}{scope}:",
        "(Semantic search ranks the whole corpus by similarity; "
        "there is no 'total matches' count — use the similarity scores to "
        "judge how good each hit is.)",
        "",
    ]
    for h, score in results:
        lines.append(format_semantic_result(h, library, score))
    return "\n".join(lines)


def random_hadith(collection: str | None = None) -> str:
    library = load()
    if collection and collection not in library.collections:
        return f"Unknown collection: {collection!r}. Try `list_collections`."

    pool = library.hadiths[collection] if collection else list(library.iter_hadiths())
    if not pool:
        return "No hadiths available."
    return format_hadith(random.choice(pool), library)
