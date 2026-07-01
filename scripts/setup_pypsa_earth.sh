#!/usr/bin/env bash
#
# Set up PyPSA-Earth for Ragnarok's whole-country network builder (I9).
#
#   • clones pypsa-earth into the project (default: <repo>/pypsa-earth)
#   • optionally builds its conda env (the slow part — skip with --no-env)
#   • points Ragnarok at it by writing the runtime override the Data-view
#     "PyPSA-Earth — whole-country build" panel reads
#
# The clone and the override file are gitignored — this script is the only part
# that's committed. Run it once from anywhere:
#
#   bash scripts/setup_pypsa_earth.sh [TARGET_DIR] [--no-env]
#
# NOTE: the CDS API key for ERA5 cutouts is a credential you must create
# yourself (register at https://cds.climate.copernicus.eu) — it can't be
# automated. This script reminds you at the end.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET="${1:-$REPO_ROOT/pypsa-earth}"
NO_ENV="${2:-}"
PE_REPO="https://github.com/pypsa-meets-earth/pypsa-earth.git"

echo "Ragnarok · PyPSA-Earth setup"
echo "  repo:   $REPO_ROOT"
echo "  target: $TARGET"
echo

# ── 1. Prerequisites ─────────────────────────────────────────────────────────
command -v git >/dev/null 2>&1 || { echo "ERROR: git is required but not found."; exit 1; }

# ── 2. Clone (idempotent) ────────────────────────────────────────────────────
if [ -f "$TARGET/Snakefile" ]; then
  echo "✓ pypsa-earth already present at $TARGET (skipping clone)"
else
  echo "→ cloning pypsa-earth into $TARGET …"
  git clone --depth 1 "$PE_REPO" "$TARGET"
  echo "✓ cloned"
fi

# ── 3. Conda environment (heavy; optional) ───────────────────────────────────
CONDA_BIN=""
if command -v mamba >/dev/null 2>&1; then CONDA_BIN="mamba"
elif command -v conda >/dev/null 2>&1; then CONDA_BIN="conda"; fi

if [ "$NO_ENV" = "--no-env" ]; then
  echo "! skipping conda env (--no-env). Create it later with:"
  echo "    conda env create -f \"$TARGET/envs/environment.yaml\""
elif [ -z "$CONDA_BIN" ]; then
  echo "! conda/mamba not found — skipping env. Install miniforge, then run:"
  echo "    conda env create -f \"$TARGET/envs/environment.yaml\""
elif conda env list 2>/dev/null | grep -qE '^pypsa-earth[[:space:]]'; then
  echo "✓ conda env 'pypsa-earth' already exists"
else
  echo "→ creating conda env 'pypsa-earth' with $CONDA_BIN (this takes ~20–30 min) …"
  "$CONDA_BIN" env create -f "$TARGET/envs/environment.yaml"
  echo "✓ conda env created"
fi

# ── 4. Point Ragnarok at the checkout ────────────────────────────────────────
# Same override file the /api/pypsa-earth/configure endpoint + UI button write,
# so the builder shows up as configured with no env var and no restart.
STATE_FILE="$REPO_ROOT/backend/data/pypsa_earth.json"
mkdir -p "$(dirname "$STATE_FILE")"
printf '{"dir": "%s"}\n' "$TARGET" > "$STATE_FILE"
echo "✓ pointed Ragnarok at $TARGET"
echo "  (wrote $STATE_FILE — restart the backend if it's already running)"

# ── 5. CDS API key reminder (credential — can't be automated) ────────────────
cat <<EOF

NEXT — add a CDS API key for ERA5 cutouts (one-time, free):
  1. register at https://cds.climate.copernicus.eu
  2. save your key to ~/.cdsapirc  (see the PyPSA-Earth docs)

Then in Ragnarok → Data → "PyPSA-Earth — whole-country build" the build form
should be available. Full guide: docs/pypsa-earth-integration.md
EOF
