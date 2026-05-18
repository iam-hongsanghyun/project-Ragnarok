#!/bin/zsh
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT_DIR"

VENV_DIR=".venv-pypsa"
PREFERRED_PYTHON=""
CONDA_BASE=""

if command -v conda >/dev/null 2>&1; then
  CONDA_BASE="$(conda info --base 2>/dev/null || true)"

  for candidate in \
    "$CONDA_BASE/envs/pypsa_alternative/bin/python" \
    "$CONDA_BASE/bin/python"; do
    if [ -n "$candidate" ] && [ -x "$candidate" ]; then
      PREFERRED_PYTHON="$candidate"
      break
    fi
  done
fi

for candidate in python3.13 python3.12 python3.11 python3.10 python3; do
  if [ -n "$PREFERRED_PYTHON" ]; then
    break
  fi

  if command -v "$candidate" >/dev/null 2>&1; then
    PREFERRED_PYTHON="$candidate"
    break
  fi
done

if [ -z "$PREFERRED_PYTHON" ]; then
  echo "No suitable Python 3 interpreter found." >&2
  exit 1
fi

if [ -d "$VENV_DIR" ]; then
  if ! "$VENV_DIR/bin/python" -c "import pyexpat" >/dev/null 2>&1; then
    rm -rf "$VENV_DIR"
  elif [ -n "$CONDA_BASE" ] && [ -x "$CONDA_BASE/bin/python" ] && ! grep -Fq "/opt/miniconda3/" "$VENV_DIR/pyvenv.cfg"; then
    rm -rf "$VENV_DIR"
  elif ! "$VENV_DIR/bin/python" -c "import sys; assert sys.version_info[:2] >= (3, 12)" >/dev/null 2>&1; then
    rm -rf "$VENV_DIR"
  fi
fi

if [ ! -d "$VENV_DIR" ]; then
  "$PREFERRED_PYTHON" -m venv "$VENV_DIR"
fi

source "$VENV_DIR/bin/activate"

export MPLCONFIGDIR="$ROOT_DIR/.matplotlib"
mkdir -p "$MPLCONFIGDIR"

python -m pip install --upgrade pip
python -m pip install -r backend/requirements.txt

if [ ! -d "node_modules" ]; then
  npm install
fi

cleanup() {
  if [ -n "${BACKEND_PID:-}" ]; then
    kill "$BACKEND_PID" >/dev/null 2>&1 || true
  fi
}

trap cleanup EXIT INT TERM

"$VENV_DIR/bin/python" -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 &
BACKEND_PID=$!

until curl -sf http://127.0.0.1:8000/api/health >/dev/null 2>&1; do
  sleep 1
done

npm run start:frontend
