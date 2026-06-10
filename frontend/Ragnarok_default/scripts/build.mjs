#!/usr/bin/env node
/**
 * Windows-portable production build.
 *
 * The old npm script set REACT_APP_BUILD_ID with POSIX shell substitution
 * (`v$npm_package_version-$(date +%s)`), which Windows cmd cannot parse — the
 * cause of the run.bat "Host"-style script failures. This wrapper computes the
 * same id in Node and spawns react-scripts build, so `npm run build` works
 * identically on macOS, Linux and Windows.
 */
import { spawnSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const pkg = JSON.parse(readFileSync(path.join(root, 'package.json'), 'utf-8'));
const buildId = `v${pkg.version}-${Math.floor(Date.now() / 1000)}`;

const result = spawnSync(
  process.platform === 'win32' ? 'npx.cmd' : 'npx',
  ['react-scripts', 'build'],
  {
    cwd: root,
    stdio: 'inherit',
    env: { ...process.env, REACT_APP_BUILD_ID: buildId },
    shell: process.platform === 'win32',
  },
);
process.exit(result.status ?? 1);
