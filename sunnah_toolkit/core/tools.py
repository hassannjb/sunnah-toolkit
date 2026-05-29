"""Protocol-agnostic hadith tools. Each function returns a dict.

The MCP server (sunnah_toolkit.mcp.server) renders these dicts to text via
sunnah_toolkit.core.text_format. The REST API (sunnah_toolkit.api) returns
them as JSON directly.

Error shape: {"error": str, "kind": "unknown_collection" | "not_found" | "unavailable"}.

Issue #2: search functions now route through `search_with_rerank` by
default. The response is additive — it gains `results_weak`, `threshold`,
`reranker`, and `reranker_status` alongside the existing `results` /
`total` fields. Setting `rerank=False` (or env $RERANKER_DISABLED=1)
falls back to the legacy single-retriever path so the eval harness can
baseline.
"""

from __future__ import annotations

import logging
import math
import random
from functools import lru_cache
from typing import Any, Literal

from . import llm_router
from . import reranker as reranker_mod
from . import semantic
from .data import Hadith, Library, load, parse_narrators, strip_narrator_markup
from .retrieval import Candidate, retrieve_union, retrieve_union_multi

logger = logging.getLogger(__name__)


# HI-005: explicit literal type + module-level weights table so unknown
# mode_hint values fail loudly instead of falling through to neutral.
Mode = Literal["concept", "keyword", "term"]

_MODE_WEIGHTS: dict[Mode, tuple[float, float, float]] = {
    # (bm25_weight, semantic_weight, term_weight)
    "concept": (0.2, 1.0, 0.4),
    "keyword": (1.0, 0.4, 0.4),
    "term": (0.2, 0.4, 1.0),
}


def _assert_mode(mode_hint: str) -> Mode:
    if mode_hint not in _MODE_WEIGHTS:
        raise ValueError(
            f"Unknown mode_hint {mode_hint!r}. Choices: {sorted(_MODE_WEIGHTS)}"
        )
    return mode_hint  # type: ignore[return-value]


# ME-009 (and HI-003): narrow exception classes that we accept as a
# "reranker failed; fall back to heuristic" signal. Anything else
# (KeyboardInterrupt, SystemExit, AssertionError, etc.) propagates as a
# genuine bug rather than being silently demoted to a warning.
_RERANKER_FALLBACK_EXC = (RuntimeError, OSError, ValueError, AttributeError)


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
    # sunnah.com serves the row under that primary URL. Sunnah.com URLs also
    # strip whitespace from letter-suffixed numbers (the dump stores "375 a"
    # but the URL is `/muslim:375a`), so squash any internal whitespace.
    raw_num = h.hadith_number or str(h.id_in_book)
    cite_id = "".join(raw_num.split(",", 1)[0].split())
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


def get_hadith(collection: str, number: int | str) -> dict[str, Any]:
    library = load()
    if collection not in library.collections:
        return {"error": f"Unknown collection: {collection!r}", "kind": "unknown_collection"}

    h = library.get_hadith(collection, number)
    if not h:
        total = len(library.hadiths[collection])
        return {
            "error": f"No hadith #{number} in {collection}. Try a sunnah.com number "
                     f"(e.g. '6312', '402b'); id_in_book range is 1..{total}.",
            "kind": "not_found",
        }
    return _hadith_dict(library, h)


@lru_cache(maxsize=8192)
def _doc_text_by_urn(urn: int, collection: str, english_title: str) -> str:
    """ME-003 helper: cached cross-encoder doc template keyed by hadith URN.

    The Arabic strip-markup pass and the title lookup are otherwise repeated
    per query for the same hadith. Cache size 8 192 comfortably covers
    realistic working sets (300 candidates × a few concurrent sessions).
    """
    library = load()
    # `urn` is globally unique. Scan the collection's list once per cache
    # miss; subsequent same-urn queries are O(1) lookups against the lru.
    target: Hadith | None = None
    for cand in library.hadiths.get(collection, ()):
        if cand.urn_arabic == urn:
            target = cand
            break
    if target is None:
        return ""
    return (
        f"{english_title}\n"
        f"{target.english_narrator}\n"
        f"{target.english_text}\n"
        f"{strip_narrator_markup(target.arabic)}"
    )


def _doc_text(library: Library, c: Candidate) -> str:
    """Per-candidate document template for the cross-encoder.

    Stripped Arabic (no [narrator] markup) is appended so the reranker has
    the matn — important for Arabic-term queries where the English text
    may not contain the user's transliterated word at all.
    """
    h = c.hadith
    col = library.get_collection(h.collection)
    title = col.english_title if col else h.collection
    return _doc_text_by_urn(h.urn_arabic, h.collection, title)


def _heuristic_scores(
    candidates: list[Candidate],
    mode_hint: Mode,
) -> list[tuple[Candidate, float]]:
    """Fallback first-stage scorer when the reranker is off or failed.

    Returns (candidate, score) pairs sorted descending by the per-mode
    weighted sum of the three normalised retriever signals.
    """
    wb, ws, wt = _MODE_WEIGHTS[mode_hint]
    scored = [
        (c, wb * c.bm25_norm + ws * c.semantic_norm + wt * c.term_norm)
        for c in candidates
    ]
    scored.sort(key=lambda p: p[1], reverse=True)
    return scored


def _score_candidates(
    library: Library,
    query: str,
    candidates: list[Candidate],
    mode_hint: Mode,
) -> tuple[list[tuple[Candidate, float]], str, str, float]:
    """Score `candidates` with the active reranker, falling back on error.

    Returns (scored, reranker_name, reranker_status, threshold).
    `reranker_status` is one of "ok", "disabled", "fell_back: <ExcClass>".
    When the reranker is off (disabled or fell back) the threshold is
    `-inf` so every candidate lands in the strong bucket.
    """
    if not reranker_mod.reranker_enabled():
        return _heuristic_scores(candidates, mode_hint), "none", "disabled", -math.inf

    name = reranker_mod.default_reranker_name()
    threshold = reranker_mod.default_threshold()
    try:
        r = reranker_mod.get_reranker(name)
        docs = [_doc_text(library, c) for c in candidates]
        scores = r.score(query, docs)
        scored = list(zip(candidates, scores))
        scored.sort(key=lambda p: p[1], reverse=True)
        return scored, name, "ok", threshold
    except _RERANKER_FALLBACK_EXC as e:
        # HI-003 / ME-009: surface the failure class in the response so
        # the caller (UI, eval harness, /healthz) can distinguish
        # "disabled by config" from "the reranker exploded".
        logger.warning(
            "reranker %s failed (%s: %s); falling back to first-stage order",
            name, type(e).__name__, e,
        )
        status = f"fell_back: {type(e).__name__}"
        return _heuristic_scores(candidates, mode_hint), "none", status, -math.inf


def _split_strong_weak(
    scored: list[tuple[Candidate, float]],
    threshold: float,
    limit: int,
) -> tuple[
    list[tuple[Candidate, float]],
    list[tuple[Candidate, float]],
]:
    """Partition `scored` into strong (≥ threshold, capped at `limit`) and weak."""
    strong: list[tuple[Candidate, float]] = []
    weak: list[tuple[Candidate, float]] = []
    for cand, score in scored:
        if score >= threshold and len(strong) < limit:
            strong.append((cand, score))
        else:
            weak.append((cand, score))
    return strong, weak


def _row_from_candidate(
    library: Library,
    cand: Candidate,
    score: float,
    query: str,
) -> dict[str, Any]:
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
    # LO-007: `similarity` is the raw bi-encoder dot product when semantic
    # retrieval contributed. Present iff the bi-encoder fired — documented
    # as a per-retriever signal, not a top-level rank score. The frontend
    # and eval harness key off `score` (the cross-encoder logit) instead.
    if "semantic" in cand.sources:
        row["similarity"] = cand.semantic
    return row


def search_with_rerank(
    query: str,
    mode_hint: str = "concept",
    collection: str | None = None,
    limit: int = 10,
    k_per_retriever: int = 100,
) -> dict[str, Any]:
    """Run the union retriever + cross-encoder reranker, split by threshold.

    LO-004: renamed from `_search_with_rerank` (which is kept below as a
    back-compat alias) since this is the canonical pipeline called by
    every public search wrapper plus the eval and threshold-tuning scripts.

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


# Back-compat alias for callers that imported the underscore-prefixed name.
_search_with_rerank = search_with_rerank


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
        "reranker_active", # bool — True iff a cross-encoder actually scored
        "reranker_status", # "ok" | "disabled" | "fell_back: <ExcClass>"
        "threshold",       # float used for the split (None when reranker off)
        "results":      [...]  # strong matches, len ≤ limit
        "results_weak": [...]  # weak matches (below threshold), reranker order
        "matched_words": [...] # only present if `term` retriever fired
      }

    `limit` is clamped at `pool_size` server-side so callers requesting more
    than the union pool no longer pretend to honour the value (CR-003).
    """
    mode = _assert_mode(mode_hint)
    # Issue #7: surface AND/OR-fallback flag for term-mode queries only.
    # Other modes don't tokenise this way, so the field is omitted.
    term_match_logic = (
        library.term_match_logic(query, collection=collection)
        if mode == "term"
        else None
    )

    if not candidates:
        empty: dict[str, Any] = {
            "query": query,
            "collection": collection,
            "mode_hint": mode,
            "total": 0,
            "limit": limit,
            "pool_size": 0,
            "reranker": "none",
            "reranker_active": False,
            "reranker_status": "disabled" if not reranker_mod.reranker_enabled() else "ok",
            "threshold": None,
            "results": [],
            "results_weak": [],
            "matched_words": [],
        }
        if mode == "term":
            empty["match_logic"] = term_match_logic
        return empty

    scored, name, status, threshold = _score_candidates(library, query, candidates, mode)
    reranker_active = status == "ok"

    # CR-003: clamp limit at the actual union pool size — a caller asking
    # for limit=1000 when only 173 candidates exist should not pretend.
    pool_size = len(scored)
    limit = min(limit, pool_size)

    strong_pairs, weak_pairs = _split_strong_weak(scored, threshold, limit)
    strong = [_row_from_candidate(library, c, s, query) for c, s in strong_pairs]
    weak = [_row_from_candidate(library, c, s, query) for c, s in weak_pairs]

    # Issue #3: aggregate matched_words from the STRONG result set only so
    # the chip strip reflects what the user actually sees. Fall back to
    # weak ONLY when the strong list is literally empty — not merely when
    # strong rows have no matched_words.
    def _count_words(rows: list[dict[str, Any]]) -> dict[str, int]:
        freq: dict[str, int] = {}
        for r in rows:
            for w in r.get("matched_words", ()) or ():
                freq[w] = freq.get(w, 0) + 1
        return freq

    strong_word_freq = _count_words(strong)
    weak_word_freq = _count_words(weak) if not strong else {}
    chip_source = strong_word_freq if strong else weak_word_freq
    matched_words = sorted(
        ({"word": w, "count": n} for w, n in chip_source.items()),
        key=lambda x: (-x["count"], x["word"]),
    )

    # LO-012 / ME-007: keep the legacy `threshold: null` shape when the
    # reranker isn't active (UI + eval depend on it), but add an explicit
    # `reranker_active` boolean so consumers don't have to disambiguate
    # "calibrated threshold" from "no threshold applied" by reading null.
    threshold_field: float | None = float(threshold) if math.isfinite(threshold) else None

    response: dict[str, Any] = {
        "query": query,
        "collection": collection,
        "mode_hint": mode,
        "total": len(strong) + len(weak),
        "limit": limit,
        "pool_size": pool_size,
        "reranker": name,
        "reranker_active": reranker_active,
        "reranker_status": status,
        "threshold": threshold_field,
        "results": strong,
        "results_weak": weak,
        "matched_words": matched_words,
    }
    if mode == "term":
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
        return search_with_rerank(query, mode_hint="keyword", collection=collection, limit=limit)

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
        return search_with_rerank(term, mode_hint="term", collection=collection, limit=limit)

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
            return search_with_rerank(query, mode_hint="concept", collection=collection, limit=limit)
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
