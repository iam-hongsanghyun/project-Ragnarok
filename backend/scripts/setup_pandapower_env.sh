#!/usr/bin/env sh
# Creates the isolated pandapower environment used by POST /api/import/pandapower.
# pandapower 3.x pins pandas~=2.3, which conflicts with PyPSA 1.4 (pandas 3), so it
# lives in its own venv at <repo>/.venv-pandapower and is driven through a subprocess.
set -eu
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
uv venv "$ROOT/.venv-pandapower" --python 3.13
uv pip install --python "$ROOT/.venv-pandapower/bin/python" "pandapower>=3.5,<4"
echo "pandapower env ready: $ROOT/.venv-pandapower"
