"""sunnah-toolkit command-line entry point.

By default runs the MCP server over stdio (compatible with Claude
Desktop, Claude Code, Cursor, etc. via .mcp.json).

HTTP mode:
    python -m sunnah_toolkit --transport http
    python -m sunnah_toolkit --transport http --host 0.0.0.0 --port 8080
"""

from __future__ import annotations

import argparse

from .mcp import server


def main() -> None:
    parser = argparse.ArgumentParser(prog="sunnah-toolkit")
    parser.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default="stdio",
        help="MCP transport (default: stdio).",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="HTTP bind host (only used with --transport http).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="HTTP bind port (only used with --transport http).",
    )
    args = parser.parse_args()
    server.run(transport=args.transport, host=args.host, port=args.port)
