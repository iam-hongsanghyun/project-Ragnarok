#!/bin/bash
# Rebuild the committed web app at ./build (the copy serve.* and the backend
# serve to npm-less machines). Run this after frontend changes, then commit
# the updated ./build. run.command and serve.command invoke it automatically
# on start when the frontend sources changed since ./build was last refreshed.
set -euo pipefail
cd "$(dirname "$0")/.."
FE="frontend/Ragnarok_default"

# Stamp the sources that go INTO this build; the launchers compare the stamp
# against scripts/frontend_src_hash.sh to detect a stale ./build.
SRC_HASH="$(scripts/frontend_src_hash.sh)"

(cd "$FE" && { [ -d node_modules ] || npm install --no-audit --no-fund; } && GENERATE_SOURCEMAP=false npm run build)

# Stage the new build next to the old one and swap, so an interrupt can never
# leave ./build half-deleted (a missing ./build self-heals on the next start).
rm -rf ./build.tmp
cp -R "$FE/build" ./build.tmp
printf '%s\n' "$SRC_HASH" > ./build.tmp/.src_hash
rm -rf ./build
mv ./build.tmp ./build
echo "Refreshed ./build — commit it to update the deployed web app."
