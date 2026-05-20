"""Render core.tools dict results to LLM-friendly text for the MCP layer."""

from __future__ import annotations

from typing import Any


def _err(result: dict[str, Any]) -> str | None:
    if "error" in result:
        return result["error"]
    return None


def list_collections(result: dict[str, Any]) -> str:
    if msg := _err(result):
        return msg
    lines = ["Available hadith collections:", ""]
    for col in result["collections"]:
        lines.append(
            f"- {col['slug']}: {col['english_title']} ({col['arabic_title']}) — "
            f"{col['hadith_count']:,} hadiths"
        )
    return "\n".join(lines)


def list_books(result: dict[str, Any]) -> str:
    if msg := _err(result):
        return msg
    chapters = result["chapters"]
    lines = [
        f"{result['english_title']} ({result['arabic_title']}) — {len(chapters)} chapters:",
        "",
    ]
    for ch in chapters:
        idx = f"{ch['id']}" if ch["id"] is not None else "—"
        lines.append(f"  {idx:>4}  {ch['english_title']}")
    return "\n".join(lines)


def hadith(result: dict[str, Any]) -> str:
    if msg := _err(result):
        return msg
    lines = [f"{result['english_title']} #{result['number']}", ""]
    if result["narrator"]:
        lines.append(result["narrator"])
    if result["english_text"]:
        lines.append(result["english_text"])
    if result["arabic"]:
        lines += ["", f"Arabic: {result['arabic']}"]
    lines += ["", f"Reference: {result['reference']}"]
    return "\n".join(lines)


def search_hadith(result: dict[str, Any]) -> str:
    if msg := _err(result):
        return msg
    query = result["query"]
    collection = result["collection"]
    total = result["total"]
    results = result["results"]
    scope = f" in {collection}" if collection else ""
    if not results:
        return f"No matches for {query!r}{scope}."
    lines = [f"Found {total} hadith(s){scope} matching {query!r}."]
    if total > len(results):
        lines.append(f"Showing first {len(results)}:")
    lines.append("")
    for h in results:
        lines.append(f"- {h['english_title']} #{h['number']} — {h['snippet']}")
    return "\n".join(lines)


def search_hadith_term(result: dict[str, Any]) -> str:
    if msg := _err(result):
        return msg
    query = result["query"]
    collection = result["collection"]
    total = result["total"]
    matched_words = result["matched_words"]
    results = result["results"]
    scope = f" in {collection}" if collection else ""

    if total == 0:
        return f"No hadiths found containing a word matching {query!r}{scope}."

    lines = [f"Found {total} hadith(s){scope} matching the term {query!r}."]
    if matched_words:
        top = matched_words[:8]
        summary = ", ".join(f"{w['word']} ({w['count']})" for w in top)
        lines.append(f"Matched Arabic words: {summary}")
        if len(matched_words) > 8:
            lines.append(f"  …and {len(matched_words) - 8} more distinct words.")

    if len(results) < total:
        lines.append(f"Showing first {len(results)}:")
    lines.append("")
    for h in results:
        words_str = " | ".join(h["matched_words"])
        lines.append(f"- {h['english_title']} #{h['number']}  [{words_str}]")
        lines.append(f"    {h['snippet']}")
    return "\n".join(lines)


def search_hadith_semantic(result: dict[str, Any]) -> str:
    if msg := _err(result):
        return msg
    query = result["query"]
    collection = result["collection"]
    results = result["results"]
    scope = f" in {collection}" if collection else ""
    if not results:
        return f"No semantic matches for {query!r}{scope}."
    lines = [
        f"Top {len(results)} semantic match(es) for {query!r}{scope}:",
        "(Semantic search ranks the whole corpus by similarity; "
        "there is no 'total matches' count — use the similarity scores to "
        "judge how good each hit is.)",
        "",
    ]
    for h in results:
        lines.append(f"- {h['english_title']} #{h['number']}  (similarity {h['similarity']:.2f})")
        lines.append(f"    {h['snippet']}")
    return "\n".join(lines)
