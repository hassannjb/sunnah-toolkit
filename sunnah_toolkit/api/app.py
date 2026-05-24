"""FastAPI application factory. Serves REST under /v1 and MCP under /mcp.

Rate limiting is intentionally left to the edge (Cloudflare Rate Limiting
in front of the public instance, or whatever the self-hoster puts in
front). The app only handles auth + business logic.
"""

from __future__ import annotations

import logging
import os
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


# ME-004: track the warm-load outcome so /healthz can surface degraded state
# instead of returning a flat `{"ok": True}` while every search silently
# falls back to the heuristic.
_warm_state: dict[str, str | bool] = {
    "reranker": "unknown",
    "reranker_status": "unknown",
}


def _warm_reranker() -> None:
    """Eagerly load + run one dummy pair so the first user request doesn't
    pay the model-load and JIT-warmup cost.

    Records the outcome in `_warm_state` so /healthz can surface it. If the
    operator sets RERANKER_REQUIRED=1 a warm-load failure is fatal (the
    lifespan re-raises, uvicorn exits non-zero) — this is the fail-fast
    path for deployments where degraded ranking is unacceptable.
    """
    if not _reranker_mod.reranker_enabled():
        _log.info("reranker disabled; skipping warm load")
        _warm_state["reranker"] = "none"
        _warm_state["reranker_status"] = "disabled"
        return
    name = _reranker_mod.default_reranker_name()
    _warm_state["reranker"] = name
    try:
        r = _reranker_mod.get_reranker(name)
        r.score("warmup", ["A short warmup document."])
        _log.info("reranker %s warmed", name)
        _warm_state["reranker_status"] = "ok"
    except Exception as e:
        _log.warning("reranker %s warm load failed: %s", name, e)
        _warm_state["reranker_status"] = f"fell_back: {type(e).__name__}"
        if os.environ.get("RERANKER_REQUIRED", "").strip() in ("1", "true", "yes"):
            # Fail-fast deployment mode: don't pretend healthy if the
            # configured reranker won't load.
            raise


def _cors_origins() -> list[str]:
    """ME-008: read allowed origins from CORS_ALLOW_ORIGINS (comma-separated).

    Defaults to ["*"] for unauthenticated demo usage. Once a deployment
    enables auth-in-browser, the operator should set CORS_ALLOW_ORIGINS to
    the actual UI origin(s) so combining `*` with Authorization headers
    cannot leak bearer tokens to malicious pages.
    """
    raw = os.environ.get("CORS_ALLOW_ORIGINS", "").strip()
    if not raw:
        return ["*"]
    return [o.strip() for o in raw.split(",") if o.strip()]


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

    origins = _cors_origins()
    # ME-008: when CORS_ALLOW_ORIGINS is "*" we strip Authorization from
    # allow_headers — a star-origin policy + Authorization is a token-leak
    # vector once the UI ships auth. Operators who want cross-origin auth
    # must set explicit origins.
    allow_headers = ["*"] if origins != ["*"] else ["Content-Type", "Accept"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_methods=["GET", "POST"],
        allow_headers=allow_headers,
    )

    @app.get("/healthz")
    def healthz() -> dict:
        # ME-004: include the warm-load outcome so an ops dashboard polling
        # /healthz sees the difference between "fresh reranker" and
        # "running on the heuristic fallback".
        return {
            "ok": True,
            "reranker": _warm_state["reranker"],
            "reranker_status": _warm_state["reranker_status"],
        }

    # Demo UI at /. Must be registered before the catch-all MCP mount below.
    app.get("/", include_in_schema=False)(_ui_index)

    app.include_router(router)
    app.mount("/", mcp_app)

    return app
