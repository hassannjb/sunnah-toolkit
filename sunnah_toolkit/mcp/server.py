"""sunnah-toolkit MCP server: exposes hadith tools via FastMCP.

Thin wrappers around sunnah_toolkit.core.tools — the docstrings here are
the LLM-facing tool descriptions that FastMCP surfaces.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from ..core import tools

mcp = FastMCP("sunnah-toolkit")


@mcp.tool()
def list_collections() -> str:
    """List every hadith collection available in this server.

    Use this first when the user asks "which books do you have" or before
    using `get_hadith`, so you know the valid collection slugs (e.g.
    `bukhari`, `muslim`, `nawawi40`).
    """
    return tools.list_collections()


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
    return tools.list_books(collection)


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
    return tools.get_hadith(collection, number)


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
    return tools.search_hadith(query, collection=collection, limit=limit)


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
    return tools.search_hadith_term(term, collection=collection, limit=limit)


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
    return tools.search_hadith_semantic(query, collection=collection, limit=limit)


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
    return tools.random_hadith(collection)


def run(transport: str = "stdio", host: str = "127.0.0.1", port: int = 8000) -> None:
    if transport == "http":
        mcp.settings.host = host
        mcp.settings.port = port
        mcp.run(transport="streamable-http")
    elif transport == "stdio":
        mcp.run()
    else:
        raise ValueError(f"Unknown transport: {transport!r}")
