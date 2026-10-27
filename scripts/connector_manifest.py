"""Stage the Claude Desktop connector: fill its manifest from the live MCP server.

Run by ``scripts/build_connector.sh`` with ``PYTHONPATH`` set to the checkout. It
imports the server registry (``backend.mcp.server``) so the manifest's ``tools``
list is generated, never hand-copied. It also writes ``server/server_info.json``
(the server instructions), which the connector relays to the client before the
Python server is up.

Usage:  python scripts/connector_manifest.py <connector/manifest.json> <stage dir>

Output (inside <stage dir>):
    manifest.json                 source manifest + ``tools`` from the registry
    server/server_info.json       {"name", "instructions"} from the server
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path
from typing import Any

_MAX_DESCRIPTION_CHARS = 400


def one_line(text: str | None) -> str:
    """Collapse whitespace and cut to the manifest's description length."""
    flat = re.sub(r"\s+", " ", text or "").strip()
    if len(flat) <= _MAX_DESCRIPTION_CHARS:
        return flat
    return flat[: _MAX_DESCRIPTION_CHARS - 1].rstrip() + "…"


def registry_tools() -> list[dict[str, str]]:
    """Return ``[{name, description}]`` for every tool registered on the server."""
    from backend.mcp.server import mcp  # imported late: needs PYTHONPATH=<checkout>

    tools = asyncio.run(mcp.list_tools())
    if not tools:
        raise SystemExit("connector_manifest: the server registered no tools")
    seen: set[str] = set()
    result: list[dict[str, str]] = []
    for tool in sorted(tools, key=lambda t: t.name):
        if tool.name in seen:
            raise SystemExit(f"connector_manifest: duplicate tool name {tool.name!r}")
        seen.add(tool.name)
        result.append({"name": tool.name, "description": one_line(tool.description)})
    return result


def server_instructions() -> str:
    from backend.mcp.server import mcp

    return mcp._mcp_server.instructions or ""  # noqa: SLF001 - FastMCP exposes no public accessor


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    source, stage = Path(argv[1]), Path(argv[2])
    manifest: dict[str, Any] = json.loads(source.read_text(encoding="utf-8"))
    manifest["tools"] = registry_tools()
    manifest["tools_generated"] = False

    (stage / "server").mkdir(parents=True, exist_ok=True)
    (stage / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    info = {"name": "ragnarok", "instructions": server_instructions()}
    (stage / "server" / "server_info.json").write_text(json.dumps(info, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"connector_manifest: {len(manifest['tools'])} tools -> {stage / 'manifest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
