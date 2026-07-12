#!/bin/bash
# Content hash of everything that feeds the web build: frontend src/, public/,
# and the npm/tsc config. scripts/refresh_build.sh stamps this hash into
# ./build/.src_hash; run.command and serve.command recompute it on start and
# rebuild ./build when the stamp no longer matches (i.e. the committed build
# is stale relative to the sources in this checkout).
set -euo pipefail
cd "$(dirname "$0")/../frontend/Ragnarok_default"
{
  find src public -type f -print0 2>/dev/null | sort -z | xargs -0 cat 2>/dev/null
  cat package.json package-lock.json tsconfig.json 2>/dev/null
} | { md5 -q 2>/dev/null || md5sum 2>/dev/null | cut -d' ' -f1; }
