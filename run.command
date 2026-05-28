#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT_DIR"

VENV_DIR=".venv-pypsa"
REQ_HASH_FILE="$VENV_DIR/.req_hash"

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

if [ ! -d "node_modules" ]; then
  echo "Installing Node.js packages..."
  npm install
fi

# ── Clear stale build caches ──────────────────────────────────────────────────
# The CRA webpack cache survives across `npm start` invocations and has caused
# users to keep seeing pre-fix bundles after a code change. Always wipe it on
# launch so the dev server compiles a fresh bundle.

if [ -d "node_modules/.cache" ] || [ -d "build" ]; then
  echo "Clearing build caches (node_modules/.cache, build/)..."
  rm -rf node_modules/.cache build
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

cleanup() {
  [ -n "${BACKEND_PID:-}" ] && kill "$BACKEND_PID" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

echo "Starting backend..."
"$VENV_DIR/bin/python" -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 &
BACKEND_PID=$!

echo "Waiting for backend to be ready..."
until curl -sf http://127.0.0.1:8000/api/health >/dev/null 2>&1; do
  sleep 1
done

echo "Backend ready. Opening app in browser..."
npm run start:frontend
