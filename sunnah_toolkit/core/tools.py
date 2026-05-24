"""Protocol-agnostic hadith tools. Each function returns a dict.

The MCP server (sunnah_toolkit.mcp.server) renders these dicts to text via
sunnah_toolkit.core.text_format. The REST API (sunnah_toolkit.api) returns
them as JSON directly.

Error shape: {"error": str, "kind": "unknown_collection" | "not_found" | "unavailable"}.

Issue #2: search functions now route through `_search_with_rerank` by
default. The response is additive — it gains `results_weak`, `threshold`,
and `reranker` alongside the existing `results` / `total` fields. Setting
`rerank=False` (or env $RERANKER_DISABLED=1) falls back to the legacy
single-retriever path so the eval harness can baseline.
"""

from __future__ import annotations

import logging
import random
from typing import Any

from . import llm_router
from . import reranker as reranker_mod
from . import semantic
from .data import Hadith, Library, load, parse_narrators
from .retrieval import Candidate, retrieve_union, retrieve_union_multi

logger = logging.getLogger(__name__)


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


def _doc_text(library: Library, c: Candidate) -> str:
    """Per-candidate document template for the cross-encoder.

    Stripped Arabic (no [narrator] markup) is appended so the reranker has
    the matn — important for Arabic-term queries where the English text
    may not contain the user's transliterated word at all.
    """
    from .data import strip_narrator_markup

    h = c.hadith
    col = library.get_collection(h.collection)
    title = col.english_title if col else h.collection
    return (
        f"{title}\n"
        f"{h.english_narrator}\n"
        f"{h.english_text}\n"
        f"{strip_narrator_markup(h.arabic)}"
    )


def _search_with_rerank(
    query: str,
    mode_hint: str = "concept",
    collection: str | None = None,
    limit: int = 10,
    k_per_retriever: int = 100,
) -> dict[str, Any]:
    """Run the union retriever + cross-encoder reranker, split by threshold.

    Thin wrapper: builds the candidate pool with `retrieve_union(query)` and
    delegates the rerank/threshold logic to `_rerank_and_split` so the NL
    search path can reuse it with a pool built by `retrieve_union_multi`.
    """
    library = load()
    candidates = retrieve_union(query, collection=collection, k_per_retriever=k_per_retriever)
    return _rerank_and_split(
        library=library,
        query=query,
        candidates=candidates,
        mode_hint=mode_hint,
        collection=collection,
        limit=limit,
    )


def _rerank_and_split(
    library: Library,
    query: str,
    candidates: list[Candidate],
    mode_hint: str,
    collection: str | None,
    limit: int,
) -> dict[str, Any]:
    """Rerank a candidate pool and split into strong/weak by threshold.

    Returns a dict shaped:
      {
        "query", "collection", "mode_hint", "limit",
        "pool_size",       # len(candidates) — the universe we ranked
        "total",           # strong + weak count
        "reranker",        # model name (or "none")
        "threshold",       # float used for the split
        "results":      [...]  # strong matches, len ≤ limit
        "results_weak": [...]  # weak matches (below threshold), reranker order
        "matched_words": [...] # only present if `term` retriever fired
      }

    `limit` is clamped at `pool_size` server-side so callers requesting more
    than the union pool no longer pretend to honour the value. See review
    finding CR-003.
    """
    # Issue #7: surface AND/OR-fallback flag for term-mode queries only.
    # Other modes don't tokenise this way, so the field is omitted.
    term_match_logic = (
        library.term_match_logic(query, collection=collection)
        if mode_hint == "term"
        else None
    )

    if not candidates:
        empty: dict[str, Any] = {
            "query": query,
            "collection": collection,
            "mode_hint": mode_hint,
            "total": 0,
            "limit": limit,
            "pool_size": 0,
            "reranker": "none",
            "threshold": 0.0,
            "results": [],
            "results_weak": [],
            "matched_words": [],
        }
        if mode_hint == "term":
            empty["match_logic"] = term_match_logic
        return empty

    rerank_on = reranker_mod.reranker_enabled()
    name = reranker_mod.default_reranker_name()
    threshold = reranker_mod.default_threshold()

    scored: list[tuple[Candidate, float]]
    if rerank_on:
        try:
            r = reranker_mod.get_reranker(name)
            docs = [_doc_text(library, c) for c in candidates]
            scores = r.score(query, docs)
            scored = list(zip(candidates, scores))
            scored.sort(key=lambda p: p[1], reverse=True)
        except Exception as e:
            logger.warning("reranker %s failed (%s); falling back to first-stage order", name, e)
            rerank_on = False
            name = "none"

    if not rerank_on:
        # Fallback ordering: max of normalised first-stage signals weighted
        # by mode_hint. Concept favours semantic, keyword favours bm25,
        # term favours the Arabic-skeleton score.
        weights = {
            "concept": (0.2, 1.0, 0.4),
            "keyword": (1.0, 0.4, 0.4),
            "term": (0.2, 0.4, 1.0),
        }.get(mode_hint, (0.5, 0.5, 0.5))
        wb, ws, wt = weights

        def _heuristic(c: Candidate) -> float:
            return wb * c.bm25_norm + ws * c.semantic_norm + wt * c.term_norm

        scored = [(c, _heuristic(c)) for c in candidates]
        scored.sort(key=lambda p: p[1], reverse=True)
        # When the reranker is off, threshold doesn't carry calibrated
        # meaning — push everything into the strong bucket so the API stays
        # backward-compatible with prior expectations.
        threshold = -float("inf")

    # CR-003: clamp limit at the actual union pool size — a caller asking
    # for limit=1000 when only 173 candidates exist should not pretend.
    pool_size = len(scored)
    limit = min(limit, pool_size)

    strong: list[dict[str, Any]] = []
    weak: list[dict[str, Any]] = []
    # Issue #3: aggregate matched_words from the STRONG result set only so
    # the chip strip reflects what the user actually sees. Fall back to weak
    # if strong is empty (rare — only when no above-threshold hits exist).
    strong_word_freq: dict[str, int] = {}
    weak_word_freq: dict[str, int] = {}

    for cand, score in scored:
        h = cand.hadith
        row: dict[str, Any] = {
            **_collection_meta(library, h.collection),
            "number": h.id_in_book,
            "hadith_number": h.hadith_number,
            "english_grade": h.english_grade,
            "snippet": _snippet(h.english_text, query),
            "score": float(score),
            "sources": sorted(cand.sources),
        }
        if cand.matched_words:
            row["matched_words"] = sorted(cand.matched_words)
        # Per-mode legacy field preservation: keep `similarity` when semantic
        # contributed, so existing API consumers don't break.
        if "semantic" in cand.sources:
            row["similarity"] = cand.semantic

        if score >= threshold and len(strong) < limit:
            strong.append(row)
            if cand.matched_words:
                for w in cand.matched_words:
                    strong_word_freq[w] = strong_word_freq.get(w, 0) + 1
        else:
            weak.append(row)
            if cand.matched_words:
                for w in cand.matched_words:
                    weak_word_freq[w] = weak_word_freq.get(w, 0) + 1

    # Issue #3: aggregate matched_words from the STRONG result set only.
    # Fallback to weak ONLY when the strong list is literally empty — not
    # merely when strong rows have no matched_words. A strong bucket with
    # non-term hits (semantic/BM25 only, no matched_words) should still
    # suppress the chip strip because there's nothing for the user to filter.
    chip_source = strong_word_freq if strong else weak_word_freq
    matched_words = sorted(
        ({"word": w, "count": n} for w, n in chip_source.items()),
        key=lambda x: (-x["count"], x["word"]),
    )

    response: dict[str, Any] = {
        "query": query,
        "collection": collection,
        "mode_hint": mode_hint,
        "total": len(strong) + len(weak),
        "limit": limit,
        "pool_size": pool_size,
        "reranker": name,
        "threshold": float(threshold) if threshold != -float("inf") else None,
        "results": strong,
        "results_weak": weak,
        "matched_words": matched_words,
    }
    if mode_hint == "term":
        response["match_logic"] = term_match_logic
    return response


def search_hadith(
    query: str,
    collection: str | None = None,
    limit: int = 10,
    rerank: bool = True,
) -> dict[str, Any]:
    library = load()
    limit = max(1, min(limit, 50000))

    if collection and collection not in library.collections:
        return {"error": f"Unknown collection: {collection!r}", "kind": "unknown_collection"}

    if rerank:
        return _search_with_rerank(query, mode_hint="keyword", collection=collection, limit=limit)

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


def search_hadith_term(
    term: str,
    collection: str | None = None,
    limit: int = 20,
    rerank: bool = True,
) -> dict[str, Any]:
    library = load()
    limit = max(1, min(limit, 50000))

    if collection and collection not in library.collections:
        return {"error": f"Unknown collection: {collection!r}", "kind": "unknown_collection"}

    if rerank:
        return _search_with_rerank(term, mode_hint="term", collection=collection, limit=limit)

    total, word_freq, hits, match_logic = library.search_term(
        term, collection=collection, limit=limit
    )
    matched_words = sorted(
        ({"word": w, "count": n} for w, n in word_freq.items()),
        key=lambda x: (-x["count"], x["word"]),
    )
    return {
        "query": term,
        "collection": collection,
        "total": total,
        "limit": limit,
        "match_logic": match_logic,
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


def search_hadith_semantic(
    query: str,
    collection: str | None = None,
    limit: int = 10,
    rerank: bool = True,
) -> dict[str, Any]:
    library = load()
    limit = max(1, min(limit, 50000))

    if collection and collection not in library.collections:
        return {"error": f"Unknown collection: {collection!r}", "kind": "unknown_collection"}

    if rerank:
        try:
            return _search_with_rerank(query, mode_hint="concept", collection=collection, limit=limit)
        except FileNotFoundError as e:
            return {"error": f"Semantic search unavailable: {e}", "kind": "unavailable"}

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


def search_hadith_natural(
    query: str,
    collection: str | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    """Natural-language search: LLM-routed variants → RRF-merged retrieval → rerank.

    Fallback semantics (per Issue #4 AC #8): if the LLM router is unavailable
    or returns None, behave like /v1/search/semantic but annotate the response
    with a `fallback` field so the UI can surface a soft warning.
    """
    library = load()
    limit = max(1, min(limit, 50000))

    if collection and collection not in library.collections:
        return {"error": f"Unknown collection: {collection!r}", "kind": "unknown_collection"}

    router = llm_router.get_router()
    if router is None:
        fallback = search_hadith_semantic(query, collection=collection, limit=limit)
        if "error" not in fallback:
            fallback["fallback"] = "llm_unavailable"
            fallback["variants"] = []
        return fallback

    routed = router.route(query)
    if routed is None:
        fallback = search_hadith_semantic(query, collection=collection, limit=limit)
        if "error" not in fallback:
            fallback["fallback"] = "router_failed"
            fallback["variants"] = []
        return fallback

    try:
        candidates = retrieve_union_multi(routed.variants, collection=collection)
    except FileNotFoundError as e:
        return {"error": f"Semantic search unavailable: {e}", "kind": "unavailable"}

    response = _rerank_and_split(
        library=library,
        query=query,
        candidates=candidates,
        mode_hint=routed.mode_hint,
        collection=collection,
        limit=limit,
    )
    response["variants"] = list(routed.variants)
    return response


def random_hadith(collection: str | None = None) -> dict[str, Any]:
    library = load()
    if collection and collection not in library.collections:
        return {"error": f"Unknown collection: {collection!r}", "kind": "unknown_collection"}

    pool = library.hadiths[collection] if collection else list(library.iter_hadiths())
    if not pool:
        return {"error": "No hadiths available.", "kind": "not_found"}
    return _hadith_dict(library, random.choice(pool))
