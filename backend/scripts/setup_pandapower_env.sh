#!/bin/sh
# Builds the isolated pandapower environment (<repo>/.venv-pandapower) in the foreground,
# with the build output in this terminal. Optional: the app builds the same environment
# in the background on the first pandapower import (backend/pypsa/network/pandapower_env.py).
# Use this to build it ahead of time. Full log: <repo>/logs/pandapower-setup.log
#
# Exit codes: 0 ready, 1 failed, 2 another build is running.
set -eu
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

# The build module is stdlib-only, so any Python 3.11+ will do; prefer the app's own venv.
PY=""
for c in "$ROOT/.venv-pypsa/bin/python" python3.13 python3.12 python3.11 python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)" 2>/dev/null; then
    PY="$c"
    break
  fi
done
[ -n "$PY" ] || { echo "ERROR: Python 3.11 or later is required (https://www.python.org/downloads/)" >&2; exit 1; }

exec "$PY" "$ROOT/backend/pypsa/network/pandapower_env.py"
