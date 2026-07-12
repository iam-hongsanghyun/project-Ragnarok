#!/bin/bash
# Ragnarok — run the app as ONE process (API + web UI on a single port).
#
# Usage:  ./serve.command [server|local]
#   server (default) → binds 0.0.0.0   : any machine on your LAN (see warning)
#   local            → binds 127.0.0.1 : only this machine can open it
#
# This is the deployment / "just use it" launcher. Contrast with run.command,
# which is DEV mode (live-reload dev servers on :3000 + :8000). Here a single
# uvicorn worker serves the committed web build at ./build together with the API
# — no reload (a reload mid-solve kills the worker), single worker (the SQLite
# stores are single-writer). The web build is committed, so no Node.js is needed.
set -euo pipefail
cd "$(dirname "$0")"
ROOT="$PWD"

MODE="${1:-server}"
case "$MODE" in
  local)  HOST="127.0.0.1" ;;
  server) HOST="0.0.0.0" ;;
  *) echo "Usage: $(basename "$0") [local|server]"; exit 2 ;;
esac

VENV="$ROOT/.venv-pypsa"
PY="$VENV/bin/python"
PORT="${RAGNAROK_PORT:-8000}"
FRONTEND="$ROOT/frontend/Ragnarok_default"

# Free a TCP port held by a stale previous run, so a restart doesn't fail to bind.
free_port() { local pids; pids=$(lsof -ti tcp:"$1" 2>/dev/null || true); [ -n "$pids" ] && kill $pids 2>/dev/null || true; }

# ── Python env ────────────────────────────────────────────────────────────────
if [ ! -x "$PY" ]; then
  echo "Creating Python virtual environment..."
  PYBIN=""
  for c in python3.13 python3.12 python3.11 python3; do
    if command -v "$c" >/dev/null 2>&1 && "$c" -c "import sys; sys.exit(0 if sys.version_info>=(3,11) else 1)" 2>/dev/null; then
      PYBIN="$c"; break
    fi
  done
  [ -n "$PYBIN" ] || { echo "ERROR: Python 3.11+ required (https://www.python.org/downloads/)"; exit 1; }
  "$PYBIN" -m venv "$VENV"
fi
REQ="$ROOT/backend/requirements.txt"
REQ_HASH=$(md5 -q "$REQ" 2>/dev/null || md5sum "$REQ" | cut -d' ' -f1)
STORED=$(cat "$VENV/.req_hash" 2>/dev/null || true)
if [ "$REQ_HASH" != "$STORED" ]; then
  echo "Installing backend dependencies..."
  "$VENV/bin/pip" install --upgrade pip --quiet
  "$VENV/bin/pip" install -r "$REQ"
  echo "$REQ_HASH" > "$VENV/.req_hash"
fi

# ── Web build (committed at ./build; rebuilt on start when missing OR stale) ──
# Staleness: scripts/frontend_src_hash.sh hashes the frontend sources; the
# stamp inside the build (.src_hash, written by scripts/refresh_build.sh)
# records what the build was made from. A mismatch means the checkout moved
# past the committed build — rebuild so the served GUI matches the code.
DIST="${RAGNAROK_FRONTEND_DIST:-$ROOT/build}"
BUILD_STATE="ok"
if [ ! -d "$DIST" ]; then
  BUILD_STATE="missing"
elif [ -d "$FRONTEND/src" ]; then
  SRC_HASH="$("$ROOT/scripts/frontend_src_hash.sh" 2>/dev/null || true)"
  if [ -n "$SRC_HASH" ] && [ "$SRC_HASH" != "$(cat "$DIST/.src_hash" 2>/dev/null || true)" ]; then
    BUILD_STATE="stale"
  fi
fi
if [ "$BUILD_STATE" != "ok" ]; then
  if command -v npm >/dev/null 2>&1; then
    echo "Web build at $DIST is $BUILD_STATE — building it now..."
    "$ROOT/scripts/refresh_build.sh"
    if [ "$DIST" != "$ROOT/build" ]; then rm -rf "$DIST"; cp -R "$ROOT/build" "$DIST"; fi
  elif [ "$BUILD_STATE" = "stale" ]; then
    echo "NOTE: web build at $DIST is stale but npm was not found — serving it as-is."
    echo "      Install Node.js, or refresh ./build on a machine that has npm and pull."
  else
    echo "NOTE: no web build at $DIST and npm not found — starting API-only."
    echo "      Install Node.js and re-run, or fetch a repo with ./build committed."
  fi
fi
export RAGNAROK_FRONTEND_DIST="$DIST"

# ── MCP server (Bifrost) — same-box HTTP bridge on its own port, so remote
# agents (LM Studio, Claude Desktop, …) connect by URL with NOTHING installed
# client-side. Set RAGNAROK_MCP=off to skip it. ───────────────────────────────
MCP_PORT="${RAGNAROK_MCP_PORT:-8765}"
MCP_PID=""
if [ "${RAGNAROK_MCP:-on}" != "off" ]; then
  if ! "$PY" -c "import mcp" >/dev/null 2>&1; then
    echo "Installing MCP server dependencies..."
    "$VENV/bin/pip" install -r "$ROOT/backend/mcp/requirements-mcp.txt" --quiet || true
  fi
  if "$PY" -c "import mcp" >/dev/null 2>&1; then
    free_port "$MCP_PORT"
    RAGNAROK_MCP_TRANSPORT=streamable-http RAGNAROK_MCP_HOST="$HOST" RAGNAROK_MCP_PORT="$MCP_PORT" \
      RAGNAROK_API_BASE="http://127.0.0.1:$PORT" PYTHONPATH="$ROOT" \
      "$PY" -m backend.mcp &
    MCP_PID=$!
    # Stop the MCP child when this script exits (Ctrl+C / terminal close).
    trap '[ -n "$MCP_PID" ] && kill "$MCP_PID" 2>/dev/null' EXIT INT TERM
  else
    echo "NOTE: MCP deps unavailable — starting the app without the agent bridge."
  fi
fi

# ── Announce URL(s) ───────────────────────────────────────────────────────────
echo ""
if [ "$MODE" = "server" ]; then
  echo "Server mode — open from any machine on this network:"
  for IF in en0 en1 en2; do
    IP=$(ipconfig getifaddr "$IF" 2>/dev/null || true)
    [ -z "$IP" ] && continue
    echo "  app:  http://$IP:$PORT"
    [ -n "$MCP_PID" ] && echo "  mcp:  http://$IP:$MCP_PORT/mcp   (point LM Studio / agents here)"
  done
  echo "  app:  http://$(hostname -s).local:$PORT"
  echo ""
  echo "WARNING: no authentication — trusted networks only (plugin install runs"
  echo "uploaded Python by design; the mcp port drives the model too). Do not"
  echo "expose to the internet. Open TCP $PORT${MCP_PID:+ and $MCP_PORT} on the firewall."
else
  echo "Local mode — open on this machine:"
  echo "  app:  http://127.0.0.1:$PORT"
  [ -n "$MCP_PID" ] && echo "  mcp:  http://127.0.0.1:$MCP_PORT/mcp"
fi
echo ""

# Foreground (not exec) so the trap can stop the MCP child on exit.
free_port "$PORT"
"$PY" -m uvicorn backend.app.main:app --host "$HOST" --port "$PORT"
