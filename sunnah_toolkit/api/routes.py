"""REST endpoints for the hadith library. Mounted under /v1 by app.py."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from ..core import tools

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


@router.get("/collections")
def list_collections() -> dict:
    return _unwrap(tools.list_collections())


@router.get("/collections/{collection}/books")
def list_books(collection: str) -> dict:
    return _unwrap(tools.list_books(collection))


@router.get("/hadith/{collection}/{number}")
def get_hadith(collection: str, number: int) -> dict:
    return _unwrap(tools.get_hadith(collection, number))


@router.get("/search")
def search_hadith(
    query: str = Query(..., description="English keyword(s)"),
    collection: str | None = None,
    limit: int = Query(10, ge=1, le=50),
) -> dict:
    return _unwrap(tools.search_hadith(query, collection=collection, limit=limit))


@router.get("/search/term")
def search_hadith_term(
    term: str = Query(..., description="English transliteration of an Arabic term"),
    collection: str | None = None,
    limit: int = Query(20, ge=1, le=100),
) -> dict:
    return _unwrap(tools.search_hadith_term(term, collection=collection, limit=limit))


@router.get("/search/semantic")
def search_hadith_semantic(
    query: str = Query(..., description="Natural-language query (concept or keyword)"),
    collection: str | None = None,
    limit: int = Query(10, ge=1, le=50),
) -> dict:
    return _unwrap(tools.search_hadith_semantic(query, collection=collection, limit=limit))


@router.get("/random")
def random_hadith(collection: str | None = None) -> dict:
    return _unwrap(tools.random_hadith(collection))
