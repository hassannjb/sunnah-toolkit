"""sunnah-mcp FastMCP server: exposes hadith tools over stdio."""

from __future__ import annotations

import random

from mcp.server.fastmcp import FastMCP

from .data import load
from .format import (
    format_collection_summary,
    format_hadith,
    format_search_result,
    format_semantic_result,
    format_term_results,
)
from . import semantic

mcp = FastMCP("sunnah-mcp")


@mcp.tool()
def list_collections() -> str:
    """List every hadith collection available in this server.

    Use this first when the user asks "which books do you have" or before
    using `get_hadith`, so you know the valid collection slugs (e.g.
    `bukhari`, `muslim`, `nawawi40`).
    """
    library = load()
    lines = ["Available hadith collections:", ""]
    for slug in sorted(library.collections.keys()):
        col = library.collections[slug]
        count = len(library.hadiths[slug])
        lines.append(format_collection_summary(col, count))
    return "\n".join(lines)


@mcp.tool()
def list_books(collection: str) -> str:
    """List the chapters (books) within a hadith collection.

    A "collection" here is e.g. `bukhari` or `muslim`. Each collection is
    organised into chapters (also called books). Use this when the user asks
    for a table of contents, or before navigating to a specific area of a
    collection.

    Args:
        collection: slug of the collection, e.g. `bukhari`. See
            `list_collections` for valid slugs.
    """
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


@mcp.tool()
def get_hadith(collection: str, number: int) -> str:
    """Fetch a single hadith by its collection and number.

    Returns the narrator, English translation, Arabic text, and a
    sunnah.com reference URL.

    QUOTING POLICY: This is the authoritative source for any hadith quote.
    Reproduce the returned English text and Arabic verbatim — never
    paraphrase, summarise, or reword. Always cite as
    `{collection english title} #{number}` (e.g. "Sahih al-Bukhari #1").
    Include the Arabic when the user asks for it; do not fabricate Arabic.

    Args:
        collection: slug of the collection, e.g. `bukhari`.
        number: the hadith number within that collection (1-indexed).
    """
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


@mcp.tool()
def search_hadith(query: str, collection: str | None = None, limit: int = 10) -> str:
    """Search hadiths by English keyword or phrase using BM25 ranking.

    Tokenises and ranks against the English translation and narrator fields.
    Returns up to `limit` matches with reference and a snippet of the text.

    QUOTING POLICY: The text shown is a TRUNCATED SNIPPET intended for
    ranking and selection, not for quoting. To quote a hadith, first call
    `get_hadith(collection, number)` for the verbatim text. Never quote
    from a snippet, and never paraphrase. Always cite as
    `{collection english title} #{number}`.

    Args:
        query: English keyword(s) to search for.
        collection: optional slug to restrict search to one collection.
        limit: max number of results (1..50).
    """
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


@mcp.tool()
def search_hadith_term(term: str, collection: str | None = None, limit: int = 20) -> str:
    """Find hadiths containing a specific Arabic Islamic term, accepting any
    English transliteration spelling.

    Use this when the user asks for hadiths mentioning a specific term that
    transliterates from Arabic — `qunut`, `qunoot`, `qonot`, `qoonoot` all
    match the same Arabic word قنوت. Also tolerates dialect substitutions
    (`azan`↔`adhan`, `ramazan`↔`ramadan`).

    The result shows the actual Arabic words matched along with frequencies,
    so the user can see if the search caught the intended term or related
    words with similar consonant skeletons.

    Do NOT use this for English-to-Arabic translation queries like "prayer"
    or "fasting" — use `search_hadith_semantic` for those. Do NOT use this
    for English keyword searches like "intentions" or "patience" — use
    `search_hadith` for those.

    QUOTING POLICY: The text shown is a TRUNCATED SNIPPET intended for
    ranking and selection, not for quoting. To quote a hadith, first call
    `get_hadith(collection, number)` for the verbatim text. Never quote
    from a snippet, and never paraphrase. Always cite as
    `{collection english title} #{number}`.

    Args:
        term: an English transliteration of an Arabic term (e.g. `qunut`).
        collection: optional slug to restrict the search.
        limit: max number of hadiths to return (1..100).
    """
    library = load()
    limit = max(1, min(limit, 100))

    if collection and collection not in library.collections:
        return f"Unknown collection: {collection!r}. Try `list_collections`."

    total, word_freq, results = library.search_term(term, collection=collection, limit=limit)
    return format_term_results(term, total, word_freq, results, library, collection)


@mcp.tool()
def search_hadith_semantic(query: str, collection: str | None = None, limit: int = 10) -> str:
    """Find hadiths by meaning, using multilingual sentence embeddings.

    Use this for conceptual / meaning-based questions where the right hadith
    might not contain the user's exact words. Examples:
      - "what does the Prophet say about anger?"
      - "humility in prayer"
      - "fasting"  (will surface hadiths about صيام/صوم)
      - "kindness to neighbours"

    Returns hadiths ranked by semantic similarity (cosine distance over
    sentence-embeddings), with a similarity score so the LLM can judge
    confidence.

    Prefer `search_hadith` for literal English keyword matches. Prefer
    `search_hadith_term` for finding hadiths containing a specific Arabic
    term (qunut/qunoot/qonot etc.).

    QUOTING POLICY: The text shown is a TRUNCATED SNIPPET intended for
    ranking and selection, not for quoting. To quote a hadith, first call
    `get_hadith(collection, number)` for the verbatim text. Never quote
    from a snippet, and never paraphrase. Always cite as
    `{collection english title} #{number}`.

    Args:
        query: any natural-language query; concept or keyword.
        collection: optional slug to restrict to one collection.
        limit: max number of hadiths to return (1..50).
    """
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


@mcp.tool()
def random_hadith(collection: str | None = None) -> str:
    """Return a randomly selected hadith.

    QUOTING POLICY: Like `get_hadith`, this is an authoritative source.
    Reproduce the returned English text and Arabic verbatim — never
    paraphrase, summarise, or reword. Always cite as
    `{collection english title} #{number}`.

    Args:
        collection: optional slug to restrict to one collection. If omitted,
            picks from any of the 17 collections, weighted by their size.
    """
    library = load()
    if collection and collection not in library.collections:
        return f"Unknown collection: {collection!r}. Try `list_collections`."

    pool = library.hadiths[collection] if collection else list(library.iter_hadiths())
    if not pool:
        return "No hadiths available."
    return format_hadith(random.choice(pool), library)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
