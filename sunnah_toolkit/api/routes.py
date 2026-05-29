"""REST endpoints for the hadith library. Mounted under /v1 by app.py.

Each route depends on auth.authenticate (returns the tier so handlers can
specialise if they ever need to; rate limiting itself lives at the edge,
e.g. Cloudflare Rate Limiting in front of the public instance).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from ..core import tools
from .auth import authenticate

router = APIRouter(prefix="/v1")


_ERROR_STATUS = {
    "unknown_collection": 404,
    "not_found": 404,
    "unavailable": 503,
}


def _unwrap(result: dict) -> dict:
    if "error" in result:
        status = _ERROR_STATUS.get(result.get("kind", ""), 400)
        raise HTTPException(status_code=status, detail=result["error"])
    return result


Auth = Annotated[tuple[str, str | None], Depends(authenticate)]


@router.get("/collections")
def list_collections(_: Auth) -> dict:
    return _unwrap(tools.list_collections())


@router.get("/collections/{collection}/books")
def list_books(collection: str, _: Auth) -> dict:
    return _unwrap(tools.list_books(collection))


@router.get("/hadith/{collection}/{number}")
def get_hadith(collection: str, number: str, _: Auth) -> dict:
    # `number` is a string so sunnah.com hadith_numbers with letter suffixes
    # ("402b", "1134b") resolve correctly. tools.get_hadith → library.get_hadith
    # tries hadith_number first and falls back to id_in_book if the input is
    # a plain integer.
    return _unwrap(tools.get_hadith(collection, number))


@router.get("/search")
def search_hadith(
    _: Auth,
    query: str = Query(..., description="English keyword(s)"),
    collection: str | None = None,
    limit: int = Query(10, ge=1, le=50000),
) -> dict:
    return _unwrap(tools.search_hadith(query, collection=collection, limit=limit))


@router.get("/search/term")
def search_hadith_term(
    _: Auth,
    term: str = Query(..., description="English transliteration of an Arabic term"),
    collection: str | None = None,
    limit: int = Query(20, ge=1, le=50000),
) -> dict:
    return _unwrap(tools.search_hadith_term(term, collection=collection, limit=limit))


@router.get("/search/semantic")
def search_hadith_semantic(
    _: Auth,
    query: str = Query(..., description="Natural-language query (concept or keyword)"),
    collection: str | None = None,
    limit: int = Query(10, ge=1, le=50000),
) -> dict:
    return _unwrap(tools.search_hadith_semantic(query, collection=collection, limit=limit))


@router.get("/search/natural")
def search_hadith_natural(
    _: Auth,
    query: str = Query(..., description="Free-form natural-language query"),
    collection: str | None = None,
    limit: int = Query(10, ge=1, le=50000),
) -> dict:
    return _unwrap(tools.search_hadith_natural(query, collection=collection, limit=limit))


@router.get("/random")
def random_hadith(_: Auth, collection: str | None = None) -> dict:
    return _unwrap(tools.random_hadith(collection))
