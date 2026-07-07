#!/usr/bin/env bash
# Double-clickable macOS installer for the CLIMADA worker env.
# Thin bootstrap around setup_climada_worker.sh (same pattern as climaterisk's
# run.command): resolves the repo from this file's location, runs the real
# installer, and keeps the Terminal window open so the outcome is readable.
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
bash "$HERE/setup_climada_worker.sh"
CODE=$?

echo
if [ "$CODE" -ne 0 ]; then
  echo "Setup FAILED with exit code $CODE. See messages above."
else
  echo "Setup finished successfully."
fi
read -r -p "Press Return to close this window... " _ || true
exit "$CODE"
