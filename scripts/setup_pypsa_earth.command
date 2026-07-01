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
# that's committed. It's a macOS .command file: double-click it in Finder, or run
# it from a terminal:
#
#   scripts/setup_pypsa_earth.command [TARGET_DIR] [--no-env]
#   # or: bash scripts/setup_pypsa_earth.command [TARGET_DIR] [--no-env]
#
# It also prompts (interactively) for a CDS API key and writes ~/.cdsapirc so
# ERA5 cutouts work. You still have to create the key yourself at
# https://cds.climate.copernicus.eu (and accept the ERA5 licence once); the
# script just saves it. An existing ~/.cdsapirc is left untouched.
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

# ── 5. CDS API key for ERA5 cutouts (~/.cdsapirc) ────────────────────────────
# atlite/cdsapi read this file; PyPSA-Earth can't fetch weather cutouts without
# it. Prompt for it here (interactive only) so setup is one flow. Never printed
# back, written 0600, and an existing file is left untouched.
CDSAPIRC="$HOME/.cdsapirc"
CDS_DONE=0
if [ -f "$CDSAPIRC" ]; then
  echo "✓ CDS API key already present at $CDSAPIRC (keeping it)"
  CDS_DONE=1
elif [ -t 0 ]; then
  echo
  echo "CDS API key for ERA5 cutouts (from https://cds.climate.copernicus.eu → your"
  echo "profile → 'API'; copy the url + key/token it shows). Press Enter to skip."
  DEFAULT_URL="https://cds.climate.copernicus.eu/api"
  read -r -p "  CDS url [$DEFAULT_URL]: " CDS_URL || true
  CDS_URL="${CDS_URL:-$DEFAULT_URL}"
  read -rs -p "  CDS key/token: " CDS_KEY || true
  echo
  if [ -n "${CDS_KEY:-}" ]; then
    printf 'url: %s\nkey: %s\n' "$CDS_URL" "$CDS_KEY" > "$CDSAPIRC"
    chmod 600 "$CDSAPIRC"
    echo "✓ wrote $CDSAPIRC"
    echo "  (also accept the ERA5 dataset licence once on the CDS website)"
    CDS_DONE=1
  else
    echo "! no key entered — skipped."
  fi
else
  echo "! non-interactive shell — skipping CDS key prompt."
fi

# ── Done ─────────────────────────────────────────────────────────────────────
echo
if [ "$CDS_DONE" -eq 0 ]; then
  echo "NEXT — add a CDS API key for ERA5 cutouts (one-time, free):"
  echo "  1. register at https://cds.climate.copernicus.eu"
  echo "  2. copy the url + key from your profile's 'API' page into ~/.cdsapirc"
  echo "  3. accept the ERA5 dataset licence on the CDS website"
  echo
fi
echo "Done. In Ragnarok → Data → \"PyPSA-Earth — whole-country build\" the build"
echo "form should be available. Full guide: docs/pypsa-earth-integration.md"
