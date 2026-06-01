#!/usr/bin/env bash
#
# Build a HiPO-enabled `highspy` and install it into the project venv — safely.
#
# HiPO is HiGHS's factorisation-based interior-point solver (HiGHS >= 1.12,
# built with -DHIPO=ON). It is excellent on large energy-system LPs but ships
# only in special builds; the stock pip/conda `highspy` rejects solver="hipo".
#
# Ragnarok treats HiPO as an OPT-IN CAPABILITY: the backend probes the installed
# HiGHS and falls back to IPM where HiPO is absent (backend/pypsa/results
# `_highs_has_hipo`). So this script is OPTIONAL — run it only on a machine
# where you want HiPO; every other machine keeps working unchanged.
#
# Safety: the new wheel is built, then HiPO is verified in a *throwaway* venv,
# and only if that succeeds is the project venv's highspy replaced. A failed,
# HiPO-less, or non-importable build therefore never touches the working solver.
#
# KNOWN STATUS (as of highspy 1.14.0, the latest on PyPI): the sdist builds with
# -DHIPO=ON but the Python extension does not fully link HiPO — `import highspy`
# then fails with an unresolved `hipo::LogHighs` symbol. So this script will
# build the wheel, fail the verify step, and correctly leave the venv untouched.
# Re-run it once a highspy with working HiPO Python bindings ships — the backend
# probe (_highs_has_hipo) and the "HiPO" UI option will then light up
# automatically, no code change needed.
#
# Usage:  scripts/build-hipo-highspy.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$ROOT/.venv-pypsa"
PYBIN="$VENV/bin/python"
PIPBIN="$VENV/bin/pip"
HIGHS_VERSION="$("$PIPBIN" show highspy 2>/dev/null | awk '/^Version:/{print $2}')"
HIGHS_VERSION="${HIGHS_VERSION:-1.14.0}"

echo "==> Target: HiPO-enabled highspy==$HIGHS_VERSION into $VENV"

# 1. Toolchain (Homebrew on macOS). cmake + metis + BLAS are HiPO's build deps.
if ! command -v cmake >/dev/null 2>&1; then
  echo "==> Installing cmake (brew)…"; brew install cmake
fi
if ! brew list metis >/dev/null 2>&1; then
  echo "==> Installing metis (brew)…"; brew install metis
fi
METIS_PREFIX="$(brew --prefix metis)"
echo "==> metis at $METIS_PREFIX"

# 2. Build a HiPO-enabled wheel from source into a temp dir.
WHEELDIR="$(mktemp -d)"
echo "==> Building highspy wheel from source with HiPO (this can take 10-20 min)…"
# scikit-build-core forwards cmake.define.* to the HiGHS CMake. HIPO=ON +
# FAST_BUILD=ON are the documented switches. METIS is supplied via the *env*
# CMAKE_PREFIX_PATH (cmake merges env + cache) — NOT via cmake.define, which
# would clobber the cache prefix scikit-build-core sets for pybind11 and break
# the binding build. BLAS is Accelerate on macOS (found automatically).
export CMAKE_PREFIX_PATH="$METIS_PREFIX${CMAKE_PREFIX_PATH:+:$CMAKE_PREFIX_PATH}"
"$PIPBIN" wheel --no-binary highspy "highspy==$HIGHS_VERSION" -w "$WHEELDIR" \
  --config-settings=cmake.define.HIPO=ON \
  --config-settings=cmake.define.FAST_BUILD=ON

WHEEL="$(ls -1 "$WHEELDIR"/highspy-*.whl | head -1)"
echo "==> Built $WHEEL"

# 3. Verify HiPO in a throwaway venv BEFORE touching the project venv.
#    Use the PROJECT interpreter ($PYBIN) so the cp-tag matches the wheel —
#    a system python of a different minor version would reject it.
CHECK="$(mktemp -d)/check-venv"
"$PYBIN" -m venv "$CHECK"
"$CHECK/bin/pip" install -q "$WHEEL"
if ! "$CHECK/bin/python" - <<'PY'
import sys, highspy
h = highspy.Highs(); h.setOptionValue("output_flag", False)
ok = h.setOptionValue("solver", "hipo") == highspy.HighsStatus.kOk
print("HiPO present:", ok)
sys.exit(0 if ok else 1)
PY
then
  echo "!! Built wheel does NOT have HiPO — the project venv was left untouched."
  echo "   The HiGHS pip sdist may not support -DHIPO=ON; build HiGHS from the"
  echo "   ERGO-Code repo with -DHIPO=ON -DFAST_BUILD=ON and its python bindings,"
  echo "   or wait for a PyPI highspy that bundles HiPO."
  exit 1
fi

# 4. HiPO verified — swap it into the project venv.
echo "==> HiPO verified. Installing into $VENV…"
"$PIPBIN" install --force-reinstall --no-deps "$WHEEL"
"$PYBIN" - <<'PY'
import highspy
h = highspy.Highs(); h.setOptionValue("output_flag", False)
assert h.setOptionValue("solver", "hipo") == highspy.HighsStatus.kOk, "HiPO missing after install"
print("==> HiPO enabled in the project venv. Select 'HiPO' in Settings -> Solver -> Method.")
PY
