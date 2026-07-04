"""Entrypoint for the Bifrost MCP server: ``python -m backend.mcp``.

Transport is chosen by ``RAGNAROK_MCP_TRANSPORT``:

* ``stdio`` (default) — the server is launched as a subprocess by the client
  (Claude Code, Claude Desktop, Codex CLI, Gemini CLI, Goose, …).
* ``streamable-http`` — the server listens on a URL for networked clients
  (LibreChat-in-Docker, remote agents). Host/port/path from
  ``RAGNAROK_MCP_HOST`` / ``RAGNAROK_MCP_PORT`` / ``RAGNAROK_MCP_PATH``.
  Defaults to ``127.0.0.1:8765/mcp`` — **not** 8000, which the Ragnarok backend
  already uses.

Backend connection + guard config (see :mod:`backend.mcp.client` /
:mod:`backend.mcp.server`): ``RAGNAROK_API_BASE``, ``RAGNAROK_SESSION_ID``,
``RAGNAROK_MCP_AUTONOMY``.
"""

from __future__ import annotations

import os

from .server import mcp

_HTTP_ALIASES = {"http", "streamable-http", "streamable_http", "shttp"}


def main() -> None:
    transport = os.environ.get("RAGNAROK_MCP_TRANSPORT", "stdio").strip().lower()
    if transport in _HTTP_ALIASES:
        mcp.settings.host = os.environ.get("RAGNAROK_MCP_HOST", "127.0.0.1")
        mcp.settings.port = int(os.environ.get("RAGNAROK_MCP_PORT", "8765"))
        mcp.settings.streamable_http_path = os.environ.get("RAGNAROK_MCP_PATH", "/mcp")
        mcp.run(transport="streamable-http")
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
