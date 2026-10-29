"""Regenerate the tool catalogue block in docs/bifrost-agent.md from the MCP area registry.

Usage: ``.venv-pypsa/bin/python scripts/gen_mcp_catalogue_doc.py`` (writes), ``--check`` (exit 1 if stale).
The block sits between the two marker comments; everything outside them is hand-written and untouched.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.mcp import server
from backend.mcp.catalogue import DOC_END, DOC_START, render_doc_block

DOC = ROOT / "docs" / "bifrost-agent.md"


def main(argv: list[str]) -> int:
    text = DOC.read_text(encoding="utf-8")
    block = render_doc_block(server.mcp._tool_manager.list_tools())
    if DOC_START in text and DOC_END in text:
        head, rest = text.split(DOC_START, 1)
        new = head + block + rest.split(DOC_END, 1)[1]
    else:
        raise SystemExit(
            f"markers not found in {DOC}; add {DOC_START!r} and {DOC_END!r} where the block belongs"
        )
    if "--check" in argv:
        if new != text:
            print(
                "docs/bifrost-agent.md tool catalogue is stale; run scripts/gen_mcp_catalogue_doc.py"
            )
            return 1
        return 0
    DOC.write_text(new, encoding="utf-8")
    print(f"updated {DOC}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
