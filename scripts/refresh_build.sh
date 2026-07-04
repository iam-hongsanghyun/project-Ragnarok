#!/bin/bash
# Rebuild the committed web app at ./build (the copy serve.* and the backend
# serve to npm-less machines). Run this after frontend changes, then commit
# the updated ./build.
set -euo pipefail
cd "$(dirname "$0")/.."
FE="frontend/Ragnarok_default"

(cd "$FE" && { [ -d node_modules ] || npm install --no-audit --no-fund; } && GENERATE_SOURCEMAP=false npm run build)
rm -rf ./build
cp -R "$FE/build" ./build
echo "Refreshed ./build — commit it to update the deployed web app."
