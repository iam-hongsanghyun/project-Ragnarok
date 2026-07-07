#!/usr/bin/env bash
# Build the CLIMADA worker's PROJECT-LOCAL conda env (./.climada-env by default).
#
# The physical-risk worker (backend/physical_risk_worker/, vendored from the
# standalone climaterisk project) needs CLIMADA's conda-forge geospatial stack
# (GDAL/PROJ/rasterio/geopandas + Python 3.11 / older numpy+pandas), which cannot
# share an interpreter with .venv-pypsa (Python 3.13, numpy 2.4, pandas 3.0) and
# is not pip-installable. It is therefore a separate PREFIX env inside the repo —
# never a global/named conda env. See docs/physical-risk-worker.md.
#
# Usage:
#   scripts/setup_climada_worker.sh              # build into ./.climada-env
#   RAGNAROK_CLIMADA_WORKER_ENV=/path scripts/setup_climada_worker.sh
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
ENV_DIR="${RAGNAROK_CLIMADA_WORKER_ENV:-$REPO/.climada-env}"
ENV_YML="$REPO/backend/physical_risk_worker/env_climada.yml"

if command -v mamba >/dev/null 2>&1; then
  CONDA=mamba
elif command -v conda >/dev/null 2>&1; then
  CONDA=conda
else
  echo "error: neither conda nor mamba found on PATH." >&2
  echo "Install miniforge (https://conda-forge.org/download/) and re-run." >&2
  exit 1
fi

if [ -x "$ENV_DIR/bin/python" ]; then
  echo "worker env already exists at $ENV_DIR — updating from env_climada.yml"
  "$CONDA" env update -f "$ENV_YML" --prefix "$ENV_DIR"
else
  echo "creating the CLIMADA worker env at $ENV_DIR (this downloads ~2 GB, be patient)"
  "$CONDA" env create -f "$ENV_YML" --prefix "$ENV_DIR"
fi

echo "sanity check: importing climada in the worker env..."
"$ENV_DIR/bin/python" -c "import climada; print('climada ok:', climada.__version__)"

echo
echo "Done. Ragnarok auto-detects the env (RAGNAROK_CLIMADA_WORKER defaults to 'auto');"
echo "restart the backend and physical-risk runs will use the real CLIMADA worker."
echo "Seed offline hazard data with: $ENV_DIR/bin/python scripts/physical_risk_build_hazard.py list"
