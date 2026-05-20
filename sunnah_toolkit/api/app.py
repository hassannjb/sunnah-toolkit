"""FastAPI application factory. Serves REST under /v1 and MCP under /mcp.

Rate limiting is intentionally left to the edge (Cloudflare Rate Limiting
in front of the public instance, or whatever the self-hoster puts in
front). The app only handles auth + business logic.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ..mcp.server import mcp
from . import auth
from .routes import router


def create_app(keys_file: str | Path | None = None) -> FastAPI:
    auth.load_keys(keys_file)
    mcp_app = mcp.streamable_http_app()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
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

    app.include_router(router)
    app.mount("/", mcp_app)

    return app
