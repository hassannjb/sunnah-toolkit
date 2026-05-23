"""FastAPI application factory. Serves REST under /v1 and MCP under /mcp.

Rate limiting is intentionally left to the edge (Cloudflare Rate Limiting
in front of the public instance, or whatever the self-hoster puts in
front). The app only handles auth + business logic.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ..core import reranker as _reranker_mod
from ..mcp.server import mcp
from . import auth
from .routes import router
from .ui import index as _ui_index


_log = logging.getLogger(__name__)


def _warm_reranker() -> None:
    """Eagerly load + run one dummy pair so the first user request doesn't
    pay the model-load and JIT-warmup cost. Best-effort: if the reranker is
    disabled or the model isn't available, log and continue."""
    if not _reranker_mod.reranker_enabled():
        _log.info("reranker disabled; skipping warm load")
        return
    name = _reranker_mod.default_reranker_name()
    try:
        r = _reranker_mod.get_reranker(name)
        r.score("warmup", ["A short warmup document."])
        _log.info("reranker %s warmed", name)
    except Exception as e:
        _log.warning("reranker %s warm load failed: %s", name, e)


def create_app(keys_file: str | Path | None = None) -> FastAPI:
    auth.load_keys(keys_file)
    mcp_app = mcp.streamable_http_app()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        _warm_reranker()
        async with mcp_app.router.lifespan_context(mcp_app):
            yield

    app = FastAPI(
        title="sunnah-toolkit",
        description="Hadith lookup over REST (/v1/...) and MCP (/mcp).",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    @app.get("/healthz")
    def healthz() -> dict:
        return {"ok": True}

    # Demo UI at /. Must be registered before the catch-all MCP mount below.
    app.get("/", include_in_schema=False)(_ui_index)

    app.include_router(router)
    app.mount("/", mcp_app)

    return app
