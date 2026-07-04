#!/bin/bash
# Ragnarok — run the app as ONE process (API + web UI on a single port).
#
# Usage:  ./serve.command [local|server]
#   local  (default) → binds 127.0.0.1 : only this machine can open it
#   server           → binds 0.0.0.0   : any machine on your LAN (see warning)
#
# This is the deployment / "just use it" launcher. Contrast with run.command,
# which is DEV mode (live-reload dev servers on :3000 + :8000). Here a single
# uvicorn worker serves the committed web build at ./build together with the API
# — no reload (a reload mid-solve kills the worker), single worker (the SQLite
# stores are single-writer). The web build is committed, so no Node.js is needed.
set -euo pipefail
cd "$(dirname "$0")"
ROOT="$PWD"

MODE="${1:-local}"
case "$MODE" in
  local)  HOST="127.0.0.1" ;;
  server) HOST="0.0.0.0" ;;
  *) echo "Usage: $(basename "$0") [local|server]"; exit 2 ;;
esac

VENV="$ROOT/.venv-pypsa"
PY="$VENV/bin/python"
PORT="${RAGNAROK_PORT:-8000}"
FRONTEND="$ROOT/frontend/Ragnarok_default"

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

# ── Web build (committed at ./build; rebuilt only if missing + npm present) ────
DIST="${RAGNAROK_FRONTEND_DIST:-$ROOT/build}"
if [ ! -d "$DIST" ]; then
  if command -v npm >/dev/null 2>&1; then
    echo "No web build at $DIST — building it now (one-time)..."
    (cd "$FRONTEND" && { [ -d node_modules ] || npm install --no-audit --no-fund; } && GENERATE_SOURCEMAP=false npm run build)
    [ "$DIST" = "$ROOT/build" ] && cp -R "$FRONTEND/build" "$DIST"
  else
    echo "NOTE: no web build at $DIST and npm not found — starting API-only."
    echo "      Install Node.js and re-run, or fetch a repo with ./build committed."
  fi
fi
export RAGNAROK_FRONTEND_DIST="$DIST"

# ── Announce URL(s) ───────────────────────────────────────────────────────────
echo ""
if [ "$MODE" = "server" ]; then
  echo "Server mode — open from any machine on this network:"
  for IF in en0 en1 en2; do
    IP=$(ipconfig getifaddr "$IF" 2>/dev/null || true)
    [ -n "$IP" ] && echo "  http://$IP:$PORT"
  done
  echo "  http://$(hostname -s).local:$PORT"
  echo ""
  echo "WARNING: no authentication — trusted networks only (plugin install runs"
  echo "uploaded Python by design). Do not expose to the internet. For remote"
  echo "access use a VPN overlay (e.g. Tailscale) or an authenticated tunnel."
else
  echo "Local mode — open on this machine:"
  echo "  http://127.0.0.1:$PORT"
fi
echo ""

exec "$PY" -m uvicorn backend.app.main:app --host "$HOST" --port "$PORT"
