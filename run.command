#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT_DIR"

VENV_DIR=".venv-pypsa"
REQ_HASH_FILE="$VENV_DIR/.req_hash"
# Frontend lives in its own package (pluggable frontend seam). The npm project
# root — package.json, public/, src/, node_modules/ — is here, not the repo root.
FRONTEND_DIR="frontend/Ragnarok_default"

# ── Helpers ───────────────────────────────────────────────────────────────────

die() { echo "ERROR: $1" >&2; exit 1; }
need_cmd() { command -v "$1" >/dev/null 2>&1 || die "$1 not found. $2"; }

# ── Dependency checks ─────────────────────────────────────────────────────────

need_cmd npm "Install Node.js (includes npm) from https://nodejs.org"
need_cmd git "Install Git from https://git-scm.com (required for the PyPSA dependency)"

# Find Python 3.11+
PREFERRED_PYTHON=""
for candidate in python3.13 python3.12 python3.11 python3; do
  if command -v "$candidate" >/dev/null 2>&1; then
    if "$candidate" -c "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)" 2>/dev/null; then
      PREFERRED_PYTHON="$candidate"
      break
    fi
  fi
done

[ -n "$PREFERRED_PYTHON" ] || die "Python 3.11 or later is required. Download from https://www.python.org/downloads/"

# ── Virtual environment ───────────────────────────────────────────────────────

if [ -d "$VENV_DIR" ]; then
  # Rebuild if the venv Python is broken or below 3.11
  if ! "$VENV_DIR/bin/python" -c "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)" >/dev/null 2>&1; then
    echo "Rebuilding virtual environment (Python version changed)..."
    rm -rf "$VENV_DIR"
  fi
fi

if [ ! -d "$VENV_DIR" ]; then
  echo "Creating Python virtual environment..."
  "$PREFERRED_PYTHON" -m venv "$VENV_DIR"
fi

source "$VENV_DIR/bin/activate"

export MPLCONFIGDIR="$ROOT_DIR/.matplotlib"
mkdir -p "$MPLCONFIGDIR"

# ── Install backend dependencies (skipped when requirements.txt is unchanged) ─

REQ_HASH="$(md5 -q backend/requirements.txt 2>/dev/null \
           || md5sum backend/requirements.txt 2>/dev/null | cut -d' ' -f1)"
STORED_HASH="$(cat "$REQ_HASH_FILE" 2>/dev/null || echo '')"

if [ "$REQ_HASH" != "$STORED_HASH" ]; then
  echo "Installing backend dependencies..."
  python -m pip install --upgrade pip -q
  python -m pip install -r backend/requirements.txt
  echo "$REQ_HASH" > "$REQ_HASH_FILE"
else
  echo "Backend dependencies are up to date."
fi

# ── Install frontend dependencies ─────────────────────────────────────────────

if [ ! -d "$FRONTEND_DIR/node_modules" ]; then
  echo "Installing Node.js packages..."
  (cd "$FRONTEND_DIR" && npm install)
fi

# ── Clear stale build caches when dependencies change ────────────────────────
# CRA's webpack cache survives across `npm start` invocations. A dependency
# upgrade can leave cached transformed sources stale, but the everyday "just
# launch the app" case doesn't need a wipe — and an unconditional wipe forces
# a cold compile of the whole bundle on every launch (slow). Hash package.json
# + package-lock.json (mirrors the REQ_HASH pattern above) and only wipe when
# they actually change.

NPM_HASH_FILE="$FRONTEND_DIR/node_modules/.npm_hash"
NPM_HASH="$(cat "$FRONTEND_DIR/package.json" "$FRONTEND_DIR/package-lock.json" 2>/dev/null \
            | { md5 -q 2>/dev/null || md5sum 2>/dev/null | cut -d' ' -f1; })"
STORED_NPM_HASH="$(cat "$NPM_HASH_FILE" 2>/dev/null || echo '')"

if [ "$NPM_HASH" != "$STORED_NPM_HASH" ]; then
  if [ -d "$FRONTEND_DIR/node_modules/.cache" ] || [ -d "$FRONTEND_DIR/build" ]; then
    echo "Clearing build caches (dependencies changed)..."
    rm -rf "$FRONTEND_DIR/node_modules/.cache" "$FRONTEND_DIR/build"
  fi
  echo "$NPM_HASH" > "$NPM_HASH_FILE"
else
  echo "Frontend build cache is up to date."
fi

# ── Free ports 3000 + 8000 (kill stale frontend / backend) ────────────────────

free_port() {
  local port="$1"
  local pids
  pids="$(lsof -ti tcp:"$port" 2>/dev/null || true)"
  if [ -n "$pids" ]; then
    echo "Port $port busy — killing PID(s): $pids"
    kill $pids >/dev/null 2>&1 || true
    sleep 1
    pids="$(lsof -ti tcp:"$port" 2>/dev/null || true)"
    [ -n "$pids" ] && kill -9 $pids >/dev/null 2>&1 || true
  fi
}

free_port 3000
free_port 8000

# ── Launch ────────────────────────────────────────────────────────────────────

PLUGIN_PIDS=()
cleanup() {
  [ -n "${BACKEND_PID:-}" ] && kill "$BACKEND_PID" >/dev/null 2>&1 || true
  for pid in "${PLUGIN_PIDS[@]:-}"; do
    [ -n "$pid" ] && kill "$pid" >/dev/null 2>&1 || true
  done
}
trap cleanup EXIT INT TERM

echo "Starting backend..."
"$VENV_DIR/bin/python" -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 &
BACKEND_PID=$!

echo "Waiting for backend to be ready..."
until curl -sf http://127.0.0.1:8000/api/health >/dev/null 2>&1; do
  sleep 1
done

# ── Launch registered plugin servers (from plugins.env) ───────────────────────
# Each non-comment line is "<absolute server dir>|<run command>". The server can
# live anywhere on disk (e.g. another repo). Plugins never talk to the Ragnarok
# backend — this just starts the local servers the frontend plugins connect to.
PLUGIN_ENV_FILE="${RAGNAROK_PLUGINS_ENV:-$ROOT_DIR/plugins.env}"
if [ -f "$PLUGIN_ENV_FILE" ]; then
  while IFS='|' read -r pdir pcmd; do
    pdir="$(echo "$pdir" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
    pcmd="$(echo "$pcmd" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
    case "$pdir" in ''|\#*) continue ;; esac
    [ -n "$pcmd" ] || continue
    if [ -d "$pdir" ]; then
      echo "Starting plugin server: $pdir -> $pcmd"
      # Run each plugin server in ITS OWN environment: if the server dir ships a
      # .venv, use it (so the plugin's deps win); otherwise fall back to the
      # Ragnarok venv that's active here. An explicit interpreter in the command
      # (e.g. ".venv/bin/python …") always takes precedence via PATH/exec.
      (
        cd "$pdir" || exit 1
        if [ -f ".venv/bin/activate" ]; then
          type deactivate >/dev/null 2>&1 && deactivate || true
          # shellcheck disable=SC1091
          source ".venv/bin/activate"
        fi
        eval "exec $pcmd"
      ) &
      PLUGIN_PIDS+=("$!")
    else
      echo "Skip plugin server (directory not found): $pdir"
    fi
  done < "$PLUGIN_ENV_FILE"
fi

echo "Backend ready. Opening app in browser..."
(cd "$FRONTEND_DIR" && npm run start:frontend)
