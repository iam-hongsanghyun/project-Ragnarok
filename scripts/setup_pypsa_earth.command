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
#   scripts/setup_pypsa_earth.command [TARGET_DIR] [--no-env] [--recreate]
#   # or: bash scripts/setup_pypsa_earth.command [TARGET_DIR] [--no-env]
#
#   --no-env     clone + configure only; don't build the conda env
#   --recreate   remove and rebuild the conda env (use if a previous run was
#                interrupted and left a broken/partial env)
#
# It also prompts (interactively) for a CDS API key and writes ~/.cdsapirc so
# ERA5 cutouts work. You still have to create the key yourself at
# https://cds.climate.copernicus.eu (and accept the ERA5 licence once); the
# script just saves it. An existing ~/.cdsapirc is left untouched.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PE_REPO="https://github.com/pypsa-meets-earth/pypsa-earth.git"
ENV_NAME="pypsa-earth"

# ── Args (flags accepted in any order; first non-flag is the target dir) ──────
TARGET=""
NO_ENV=0
RECREATE=0
for arg in "$@"; do
  case "$arg" in
    --no-env)   NO_ENV=1 ;;
    --recreate) RECREATE=1 ;;
    -h|--help)
      echo "Usage: setup_pypsa_earth.command [TARGET_DIR] [--no-env] [--recreate]"
      exit 0 ;;
    -*) echo "ERROR: unknown option: $arg" >&2; exit 2 ;;
    *)  [ -z "$TARGET" ] && TARGET="$arg" ;;
  esac
done
TARGET="${TARGET:-$REPO_ROOT/pypsa-earth}"

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

# True if an env named $ENV_NAME is listed; and if snakemake actually runs in it
# (the check Ragnarok itself does before a build — catches partial/broken envs).
env_exists() { "$CONDA_BIN" env list 2>/dev/null | awk 'NF && $1 !~ /^#/ {print $1}' | grep -qx "$ENV_NAME"; }
env_usable() { "$CONDA_BIN" run -n "$ENV_NAME" snakemake --version >/dev/null 2>&1; }

create_env() {
  # The classic conda solver can sit on "Collecting package metadata" for 10–30
  # min (looks frozen — it isn't). Use libmamba when available so it's minutes.
  SOLVER_FLAG=""
  if [ "$CONDA_BIN" = "conda" ] && conda env create --help 2>/dev/null | grep -q -- '--solver'; then
    SOLVER_FLAG="--solver=libmamba"
    echo "  (using the fast libmamba solver)"
  fi
  echo "→ creating conda env '$ENV_NAME' with $CONDA_BIN …"
  echo "  (the classic solver may sit silently on 'Collecting package metadata' for"
  echo "   10–30 min — that is normal, not stuck; libmamba/mamba take a few minutes)"
  if [ -n "$SOLVER_FLAG" ]; then
    "$CONDA_BIN" env create "$SOLVER_FLAG" -f "$TARGET/envs/environment.yaml"
  else
    "$CONDA_BIN" env create -f "$TARGET/envs/environment.yaml"
  fi
}

if [ "$NO_ENV" -eq 1 ]; then
  echo "! skipping conda env (--no-env). Create it later with:"
  echo "    conda env create -f \"$TARGET/envs/environment.yaml\""
elif [ -z "$CONDA_BIN" ]; then
  echo "! conda/mamba not found — skipping env. Install miniforge, then re-run this."
  echo "    (or: conda env create -f \"$TARGET/envs/environment.yaml\")"
else
  if [ "$RECREATE" -eq 1 ] && env_exists; then
    echo "→ removing existing '$ENV_NAME' env (--recreate) …"
    "$CONDA_BIN" env remove -n "$ENV_NAME" -y >/dev/null
  fi
  if env_exists; then
    if env_usable; then
      echo "✓ conda env '$ENV_NAME' already exists and runs snakemake"
    else
      echo "! conda env '$ENV_NAME' exists but snakemake won't run in it — likely a"
      echo "  partial/interrupted install. Rebuild it with:"
      echo "    bash \"$0\" --recreate"
    fi
  else
    create_env
    if env_usable; then
      echo "✓ conda env created and verified (snakemake runs)"
    else
      echo "! conda env created, but snakemake didn't run — check the output above,"
      echo "  or rebuild with:  bash \"$0\" --recreate"
    fi
  fi
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
