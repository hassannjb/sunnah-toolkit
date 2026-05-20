"""Text formatters that produce LLM-friendly output from hadith records."""

from __future__ import annotations

from .data import Collection, Hadith, Library


def format_hadith(h: Hadith, library: Library) -> str:
    col = library.get_collection(h.collection)
    title = col.english_title if col else h.collection
    lines = [
        f"{title} #{h.id_in_book}",
        "",
    ]
    if h.english_narrator:
        lines.append(h.english_narrator)
    if h.english_text:
        lines.append(h.english_text)
    if h.arabic:
        lines += ["", f"Arabic: {h.arabic}"]
    lines += ["", f"Reference: sunnah.com/{h.collection}:{h.id_in_book}"]
    return "\n".join(lines)


def format_collection_summary(col: Collection, hadith_count: int) -> str:
    return (
        f"- {col.slug}: {col.english_title} ({col.arabic_title}) — "
        f"{hadith_count:,} hadiths"
    )


def format_search_result(h: Hadith, library: Library, query: str) -> str:
    col = library.get_collection(h.collection)
    title = col.english_title if col else h.collection
    snippet = _snippet(h.english_text, query)
    return f"- {title} #{h.id_in_book} — {snippet}"


def format_semantic_result(h: Hadith, library: Library, score: float) -> str:
    col = library.get_collection(h.collection)
    title = col.english_title if col else h.collection
    snippet = h.english_text[:200] + ("…" if len(h.english_text) > 200 else "")
    return f"- {title} #{h.id_in_book}  (similarity {score:.2f})\n    {snippet}"


def format_term_results(
    query: str,
    total: int,
    word_freq: dict[str, int],
    results: list[tuple[Hadith, set[str]]],
    library: Library,
    collection: str | None,
) -> str:
    if total == 0:
        scope = f" in {collection}" if collection else ""
        return f"No hadiths found containing a word matching {query!r}{scope}."

    scope = f" in {collection}" if collection else ""
    lines = [f"Found {total} hadith(s){scope} matching the term {query!r}."]

    if word_freq:
        top_words = sorted(word_freq.items(), key=lambda kv: kv[1], reverse=True)[:8]
        summary = ", ".join(f"{w} ({n})" for w, n in top_words)
        lines.append(f"Matched Arabic words: {summary}")
        if len(word_freq) > 8:
            lines.append(f"  …and {len(word_freq) - 8} more distinct words.")

    if len(results) < total:
        lines.append(f"Showing first {len(results)}:")
    lines.append("")

    for h, matched_words in results:
        col = library.get_collection(h.collection)
        title = col.english_title if col else h.collection
        words_str = " | ".join(sorted(matched_words))
        snippet = (h.english_text[:140] + "…") if len(h.english_text) > 140 else h.english_text
        lines.append(f"- {title} #{h.id_in_book}  [{words_str}]")
        lines.append(f"    {snippet}")
    return "\n".join(lines)


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
