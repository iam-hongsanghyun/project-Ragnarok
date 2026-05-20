#!/usr/bin/env bash
# pack.sh — zip each sample plugin for installation via the Ragnarok UI
#
# Usage:
#   cd sample-plugins
#   ./pack.sh
#
# Output: one .zip per plugin in sample-plugins/dist/

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DIST="$SCRIPT_DIR/dist"
mkdir -p "$DIST"

plugins=(
  ragnarok-log-importer
  ragnarok-network-patcher
  ragnarok-renewable-floor
  ragnarok-cost-reporter
)

for plugin in "${plugins[@]}"; do
  src="$SCRIPT_DIR/$plugin"
  out="$DIST/${plugin}.zip"
  if [[ ! -d "$src" ]]; then
    echo "  SKIP  $plugin (directory not found)"
    continue
  fi
  rm -f "$out"
  (cd "$SCRIPT_DIR" && zip -r "$out" "$plugin" -x "*.pyc" -x "*/__pycache__/*" -x "*/.DS_Store")
  echo "  PACK  $out"
done

echo ""
echo "Done. Install each .zip via the Modules panel in Ragnarok."
