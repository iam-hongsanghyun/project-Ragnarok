#!/usr/bin/env bash
# Build dist/ragnarok.mcpb: the one-click Claude Desktop connector for Ragnarok.
#
# Steps: stage connector/ + the manifest generated from the live MCP server
# (scripts/connector_manifest.py), check the launcher parses, then validate and
# pack with the pinned @anthropic-ai/mcpb CLI. Output: dist/ragnarok.mcpb (git-ignored).
#
# Usage:  scripts/build_connector.sh
# Needs:  Node.js (npx) and a Python with the Ragnarok deps (default ./.venv-pypsa;
#         override with RAGNAROK_BUILD_PYTHON=/path/to/python).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

MCPB_CLI="@anthropic-ai/mcpb@2.1.2"   # pinned: the bundle format and validator
PY="${RAGNAROK_BUILD_PYTHON:-$ROOT/.venv-pypsa/bin/python}"
STAGE="$ROOT/dist/stage/ragnarok"
OUT="$ROOT/dist/ragnarok.mcpb"

command -v npx >/dev/null 2>&1 || { echo "ERROR: npx (Node.js) is required for the mcpb CLI. Install Node.js from https://nodejs.org"; exit 1; }
[ -x "$PY" ] || { echo "ERROR: no Python at $PY. Run ./serve.command once, or set RAGNAROK_BUILD_PYTHON."; exit 1; }

rm -rf "$STAGE"
mkdir -p "$STAGE/server" "$(dirname "$OUT")"

# 1. Manifest with the tools list generated from the server, plus server instructions.
PYTHONPATH="$ROOT" "$PY" scripts/connector_manifest.py connector/manifest.json "$STAGE"

# 2. Launcher and assets.
cp connector/server/index.js "$STAGE/server/index.js"
cp connector/icon.png connector/.mcpbignore "$STAGE/"
node --check "$STAGE/server/index.js"

# 3. Validate, pack, inspect.
npx --yes "$MCPB_CLI" validate "$STAGE/manifest.json"
rm -f "$OUT"
npx --yes "$MCPB_CLI" pack "$STAGE" "$OUT"
npx --yes "$MCPB_CLI" info "$OUT" || true

echo ""
echo "Built: $OUT ($(du -h "$OUT" | cut -f1))"
echo "Archive contents:"
unzip -l "$OUT"
