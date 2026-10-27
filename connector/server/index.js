#!/usr/bin/env node
// Ragnarok connector for Claude Desktop (MCPB, server.type "node").
//
// Role: answer the MCP handshake at once, prepare the Python environment in the
// background, then relay stdio JSON-RPC to the real server (`python -m backend.mcp`
// in the Ragnarok checkout). Until that child is ready, tools/list is answered from
// the manifest and tools/call returns "still starting" (or the failure reason), so a
// first-run install never blocks the client's initialize past its timeout.
//
// Stdlib only: Claude Desktop ships Node, so nothing needs installing. Relies on
// nothing outside this file except the Ragnarok checkout and an installed Python 3.11+.
//
// stdout carries ONLY JSON-RPC. Everything else goes to stderr and to
// <repo>/.connector/logs/connector.log.
'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');
const cp = require('child_process');
const readline = require('readline');

const PROTOCOL_VERSION = '2025-06-18';
const SUPPORTED_PROTOCOLS = ['2025-11-25', '2025-06-18', '2025-03-26', '2024-11-05'];
const HANDSHAKE_ID = 'ragnarok-connector-init';
const HANDSHAKE_TIMEOUT_MS = 420000; // backend autostart waits up to 300 s, plus imports
const MAX_RESTARTS = 2;
const PROBE_TIMEOUT_MS = 15000;

const ROOT = path.join(__dirname, '..');
const MANIFEST = readJson(path.join(ROOT, 'manifest.json'), {});
const SERVER_INFO = readJson(path.join(__dirname, 'server_info.json'), {});
const VERSION = String(MANIFEST.version || '0.0.0');

// ── configuration (values come from mcp_config.env, i.e. user_config) ────────────
function setting(name, fallback) {
  const raw = (process.env[name] || '').trim();
  return raw === '' || raw.startsWith('${') ? fallback : raw;
}

const REPO = path.resolve(setting('RAGNAROK_REPO', path.join(os.homedir(), 'github', 'ragnarok')));
const PORT = parsePort(setting('RAGNAROK_PORT', '8000'));
const API_OVERRIDE = setting('RAGNAROK_API_BASE', '').replace(/\/+$/, '');
const REMOTE = API_OVERRIDE !== '';
const API_BASE = REMOTE ? API_OVERRIDE : `http://127.0.0.1:${PORT}`;
const SESSION_ID = setting('RAGNAROK_SESSION_ID', 'default');
const AUTONOMY_RAW = setting('RAGNAROK_MCP_AUTONOMY', 'guided').toLowerCase();
const AUTONOMY = ['guided', 'manual', 'auto'].includes(AUTONOMY_RAW) ? AUTONOMY_RAW : 'guided';

const IS_WIN = process.platform === 'win32';
const VENV_DIR = path.join(REPO, '.venv-pypsa');
const VENV_PY = IS_WIN ? path.join(VENV_DIR, 'Scripts', 'python.exe') : path.join(VENV_DIR, 'bin', 'python');
const CONNECTOR_DIR = path.join(REPO, '.connector');
const LOG_DIR = path.join(CONNECTOR_DIR, 'logs');
const CONNECTOR_LOG = path.join(LOG_DIR, 'connector.log');
const INSTALL_LOG = path.join(LOG_DIR, 'install.log');
const DEPS_STAMP = path.join(CONNECTOR_DIR, 'deps.sha256');
const REQ_FILES = ['backend/requirements.txt', 'backend/mcp/requirements-mcp.txt'];
const REQ_FILES_REMOTE = ['backend/mcp/requirements-mcp.txt'];

// ── logging (never stdout) ──────────────────────────────────────────────────────
function fallbackLogDir() {
  if (IS_WIN) return path.join(process.env.LOCALAPPDATA || os.homedir(), 'Ragnarok', 'Logs');
  if (process.platform === 'darwin') return path.join(os.homedir(), 'Library', 'Logs', 'Ragnarok');
  return path.join(os.homedir(), '.cache', 'ragnarok', 'logs');
}
const REPO_IS_CHECKOUT = fs.existsSync(path.join(REPO, 'backend', 'mcp', '__main__.py'));
const EFFECTIVE_LOG_DIR = REPO_IS_CHECKOUT ? LOG_DIR : fallbackLogDir();
const EFFECTIVE_CONNECTOR_LOG = path.join(EFFECTIVE_LOG_DIR, 'connector.log');

function ensureDir(dir) {
  try {
    fs.mkdirSync(dir, { recursive: true });
  } catch (_) {
    /* reported when written */
  }
}

function log(level, message) {
  const line = `${new Date().toISOString()} ${level.padEnd(5)} ${message}\n`;
  process.stderr.write(line);
  try {
    ensureDir(EFFECTIVE_LOG_DIR);
    fs.appendFileSync(EFFECTIVE_CONNECTOR_LOG, line);
  } catch (_) {
    /* stderr still has it */
  }
}

// ── state shown to the user while not ready ────────────────────────────────────
let state = 'starting'; // starting | installing | launching | ready | failed | stopped
let stageText = `Ragnarok is starting. Checking the Ragnarok folder at ${REPO}.`;
let failureText = '';
let child = null;
let childReady = false;
let shuttingDown = false;
let restarts = 0;
let handshakeTimer = null;
const pendingHandshake = { resolve: null, reject: null };

function notReadyText() {
  if (state === 'failed') {
    return `Ragnarok could not start: ${failureText} Details: ${EFFECTIVE_CONNECTOR_LOG}`;
  }
  return `${stageText} Try this tool again in a minute or two. Details: ${EFFECTIVE_CONNECTOR_LOG}`;
}

// ── JSON-RPC output ─────────────────────────────────────────────────────────────
function writeClient(obj) {
  process.stdout.write(JSON.stringify(obj) + '\n');
}

function reply(id, result) {
  writeClient({ jsonrpc: '2.0', id, result });
}

function replyError(id, code, message) {
  writeClient({ jsonrpc: '2.0', id, error: { code, message } });
}

function manifestTools() {
  return Array.isArray(MANIFEST.tools) ? MANIFEST.tools : [];
}

function initializeResult(params) {
  const requested = params && params.protocolVersion;
  const result = {
    protocolVersion: SUPPORTED_PROTOCOLS.includes(requested) ? requested : PROTOCOL_VERSION,
    capabilities: { tools: {} },
    serverInfo: { name: SERVER_INFO.name || 'ragnarok', version: VERSION },
  };
  if (SERVER_INFO.instructions) result.instructions = SERVER_INFO.instructions;
  return result;
}

// ── requests from the client ────────────────────────────────────────────────────
function handleClientMessage(msg) {
  if (Array.isArray(msg)) {
    // JSON-RPC batching was removed in 2025-06-18; forward when ready, else refuse.
    if (state === 'ready') return forwardToChild(msg);
    return writeClient({ jsonrpc: '2.0', id: null, error: { code: -32600, message: 'batch not supported yet' } });
  }
  if (msg === null || typeof msg !== 'object') return undefined;

  const hasMethod = typeof msg.method === 'string';
  const isRequest = hasMethod && msg.id !== undefined;

  if (!hasMethod) {
    // A response to a server->client request (e.g. roots/list): relay when ready.
    return state === 'ready' ? forwardToChild(msg) : undefined;
  }

  if (msg.method === 'initialize') return reply(msg.id, initializeResult(msg.params));
  if (msg.method === 'ping' && isRequest) return reply(msg.id, {});
  if (msg.method === 'notifications/initialized') return undefined; // the relay did the child's handshake

  if (state === 'ready') return forwardToChild(msg);
  if (!isRequest) return undefined; // notifications are dropped until ready

  switch (msg.method) {
    case 'tools/list':
      return reply(msg.id, { tools: manifestTools() });
    case 'tools/call':
      return reply(msg.id, { content: [{ type: 'text', text: notReadyText() }], isError: true });
    case 'resources/list':
      return reply(msg.id, { resources: [] });
    case 'resources/templates/list':
      return reply(msg.id, { resourceTemplates: [] });
    case 'prompts/list':
      return reply(msg.id, { prompts: [] });
    default:
      return replyError(msg.id, -32002, notReadyText());
  }
}

function forwardToChild(msg) {
  if (!child || !child.stdin || !child.stdin.writable) {
    if (msg.id !== undefined && msg.method) replyError(msg.id, -32002, notReadyText());
    return;
  }
  child.stdin.write(JSON.stringify(msg) + '\n');
}

// ── child stdout: handshake answer or relay ────────────────────────────────────
function onChildLine(line) {
  const text = line.trim();
  if (!text) return;
  let msg;
  try {
    msg = JSON.parse(text);
  } catch (_) {
    log('WARN', `child wrote a non-JSON line on stdout (not relayed): ${text.slice(0, 200)}`);
    return;
  }
  if (msg && msg.id === HANDSHAKE_ID && (msg.result !== undefined || msg.error !== undefined)) {
    if (pendingHandshake.resolve) pendingHandshake.resolve(msg);
    return;
  }
  writeClient(msg);
}

// ── Python discovery and venv bootstrap ────────────────────────────────────────
function run(cmd, args, opts = {}) {
  return new Promise((resolve) => {
    let out = '';
    let proc;
    try {
      proc = cp.spawn(cmd, args, { ...opts, stdio: ['ignore', 'pipe', 'pipe'] });
    } catch (err) {
      return resolve({ code: -1, out: String(err) });
    }
    const timer = opts.timeoutMs ? setTimeout(() => proc.kill(), opts.timeoutMs) : null;
    proc.stdout.on('data', (d) => (out += d));
    proc.stderr.on('data', (d) => (out += d));
    proc.on('error', (err) => {
      if (timer) clearTimeout(timer);
      resolve({ code: -1, out: String(err) });
    });
    proc.on('close', (code) => {
      if (timer) clearTimeout(timer);
      resolve({ code, out });
    });
  });
}

// Run a long command with its output appended to the install log (never stdout).
function runLogged(cmd, args, opts = {}) {
  return new Promise((resolve, reject) => {
    ensureDir(LOG_DIR);
    const fd = fs.openSync(INSTALL_LOG, 'a');
    fs.writeSync(fd, `\n$ ${cmd} ${args.join(' ')}\n`);
    let proc;
    try {
      proc = cp.spawn(cmd, args, { ...opts, stdio: ['ignore', fd, fd] });
    } catch (err) {
      fs.closeSync(fd);
      return reject(err);
    }
    proc.on('error', (err) => {
      fs.closeSync(fd);
      reject(err);
    });
    proc.on('close', (code) => {
      fs.closeSync(fd);
      code === 0 ? resolve() : reject(new Error(`${path.basename(cmd)} exited with code ${code}`));
    });
  });
}

function candidatePythons() {
  const list = [];
  const home = os.homedir();
  if (IS_WIN) {
    const local = process.env.LOCALAPPDATA || path.join(home, 'AppData', 'Local');
    for (const v of ['3.13', '3.12', '3.11']) {
      list.push({ cmd: 'py', args: [`-${v}`] });
      list.push({ cmd: path.join(local, 'Programs', 'Python', `Python${v.replace('.', '')}`, 'python.exe'), args: [] });
    }
    list.push({ cmd: 'python', args: [] }, { cmd: 'python3', args: [] });
  } else {
    for (const v of ['3.13', '3.12', '3.11']) {
      list.push({ cmd: `/opt/homebrew/bin/python${v}`, args: [] });
      list.push({ cmd: `/usr/local/bin/python${v}`, args: [] });
      list.push({ cmd: `python${v}`, args: [] });
    }
    list.push(
      { cmd: '/Library/Frameworks/Python.framework/Versions/3.13/bin/python3', args: [] },
      { cmd: '/Library/Frameworks/Python.framework/Versions/3.12/bin/python3', args: [] },
      { cmd: path.join(home, 'miniforge3', 'bin', 'python3'), args: [] },
      { cmd: path.join(home, 'miniconda3', 'bin', 'python3'), args: [] },
      { cmd: path.join(home, '.pyenv', 'shims', 'python3'), args: [] },
      { cmd: '/opt/homebrew/bin/python3', args: [] },
      { cmd: '/usr/local/bin/python3', args: [] },
    );
  }
  return list;
}

const PY_PROBE = 'import sys;print(sys.executable);print("%d.%d"%sys.version_info[:2])';

async function findBasePython() {
  for (const cand of candidatePythons()) {
    const res = await run(cand.cmd, [...cand.args, '-c', PY_PROBE], { timeoutMs: PROBE_TIMEOUT_MS });
    if (res.code !== 0) continue;
    const [exe, ver] = res.out.trim().split(/\r?\n/).slice(-2);
    const [major, minor] = (ver || '0.0').split('.').map(Number);
    if (major === 3 && minor >= 11 && exe) return { exe: exe.trim(), version: ver.trim() };
  }
  return null;
}

function findUv() {
  const names = IS_WIN ? ['uv.exe'] : ['uv'];
  const home = os.homedir();
  const fixed = IS_WIN
    ? [path.join(home, '.local', 'bin', 'uv.exe'), path.join(home, '.cargo', 'bin', 'uv.exe')]
    : [path.join(home, '.local', 'bin', 'uv'), '/opt/homebrew/bin/uv', '/usr/local/bin/uv', path.join(home, '.cargo', 'bin', 'uv')];
  const onPath = (process.env.PATH || '').split(path.delimiter).filter(Boolean).map((d) => path.join(d, names[0]));
  return [...fixed, ...onPath].find((p) => fs.existsSync(p)) || null;
}

async function venvVersionOk() {
  if (!fs.existsSync(VENV_PY)) return null;
  const res = await run(VENV_PY, ['-c', 'import sys;print("%d.%d"%sys.version_info[:2])'], { timeoutMs: PROBE_TIMEOUT_MS });
  if (res.code !== 0) return null;
  const ver = res.out.trim();
  const [major, minor] = ver.split('.').map(Number);
  return major === 3 && minor >= 11 ? ver : 'old';
}

function requirementsHash(remote, pythonVersion) {
  const crypto = require('crypto');
  const h = crypto.createHash('sha256');
  h.update(`python=${pythonVersion};mode=${remote ? 'remote' : 'local'}\n`);
  for (const rel of remote ? REQ_FILES_REMOTE : REQ_FILES) {
    h.update(fs.readFileSync(path.join(REPO, rel)));
  }
  return h.digest('hex');
}

async function ensureVenv() {
  let version = await venvVersionOk();
  if (version === 'old') {
    log('INFO', `existing ${VENV_DIR} is older than Python 3.11; rebuilding it`);
    fs.rmSync(VENV_DIR, { recursive: true, force: true });
    version = null;
  }
  if (version === null) {
    stageText = 'Ragnarok is installing: creating its Python environment.';
    state = 'installing';
    const base = await findBasePython();
    if (!base) {
      throw new Failure(
        'Python 3.11 or newer was not found. Install Python 3.13 from https://www.python.org/downloads/ (on macOS, `brew install python@3.13` also works), then restart this connector.',
      );
    }
    log('INFO', `creating ${VENV_DIR} with ${base.exe} (Python ${base.version})`);
    await runLogged(base.exe, ['-m', 'venv', VENV_DIR]);
    version = await venvVersionOk();
    if (!version || version === 'old') throw new Failure(`the new virtual environment at ${VENV_DIR} did not start.`);
  }

  const remote = REMOTE;
  const want = requirementsHash(remote, version);
  const have = fs.existsSync(DEPS_STAMP) ? fs.readFileSync(DEPS_STAMP, 'utf8').trim() : '';
  if (want === have) {
    log('INFO', 'Python dependencies are up to date');
    return;
  }

  state = 'installing';
  stageText = `Ragnarok is installing its Python packages into ${VENV_DIR}. The first install takes about 5 to 15 minutes.`;
  log('INFO', `installing ${remote ? 'remote-client' : 'full'} dependencies (see ${INSTALL_LOG})`);
  const reqArgs = (remote ? REQ_FILES_REMOTE : REQ_FILES).flatMap((rel) => ['-r', path.join(REPO, rel)]);
  const uv = findUv();
  if (uv) {
    await runLogged(uv, ['pip', 'install', '--python', VENV_PY, ...reqArgs], { cwd: REPO });
  } else {
    await runLogged(VENV_PY, ['-m', 'pip', 'install', ...reqArgs], { cwd: REPO });
  }
  ensureDir(CONNECTOR_DIR);
  fs.writeFileSync(DEPS_STAMP, want + '\n');
  log('INFO', 'Python dependencies installed');
}

// ── the child: python -m backend.mcp ───────────────────────────────────────────
function childEnv() {
  const mpl = path.join(REPO, '.matplotlib');
  ensureDir(mpl);
  const env = {
    ...process.env,
    PYTHONPATH: REPO,
    PYTHONNOUSERSITE: '1',
    PYTHONUNBUFFERED: '1',
    PYTHONIOENCODING: 'utf-8',
    MPLCONFIGDIR: mpl,
    RAGNAROK_MCP_TRANSPORT: 'stdio',
    RAGNAROK_API_BASE: API_BASE,
    RAGNAROK_SESSION_ID: SESSION_ID,
    RAGNAROK_MCP_AUTONOMY: AUTONOMY,
    RAGNAROK_MCP_AUTOSTART: REMOTE ? '0' : '1',
    RAGNAROK_REPO_ROOT: REPO,
    RAGNAROK_CONNECTOR_DIR: CONNECTOR_DIR,
  };
  const build = path.join(REPO, 'build');
  if (!process.env.RAGNAROK_FRONTEND_DIST && fs.existsSync(build)) env.RAGNAROK_FRONTEND_DIST = build;
  return env;
}

const AUTOSTART_FAILED = 'RAGNAROK_AUTOSTART_FAILED:';

function startChild() {
  state = 'launching';
  stageText = `Ragnarok is starting the backend on ${API_BASE}. The first launch can take a few minutes.`;
  childReady = false;
  let autostartFailure = null;
  const proc = cp.spawn(VENV_PY, ['-m', 'backend.mcp'], {
    cwd: REPO,
    env: childEnv(),
    stdio: ['pipe', 'pipe', 'pipe'],
  });
  child = proc;
  log('INFO', `started MCP child pid=${proc.pid} (${VENV_PY} -m backend.mcp)`);

  readline.createInterface({ input: proc.stdout }).on('line', onChildLine);
  readline.createInterface({ input: proc.stderr }).on('line', (line) => {
    log('CHILD', line);
    if (line.startsWith(AUTOSTART_FAILED)) autostartFailure = line.slice(AUTOSTART_FAILED.length).trim();
  });

  proc.stdin.on('error', () => {
    /* child already gone; the 'close' handler reports it */
  });
  proc.on('error', (err) => log('ERROR', `could not start the MCP child: ${err.message}`));
  // 'close' (not 'exit') so the stderr lines that carry the failure reason have all arrived.
  proc.on('close', (code, signal) => {
    clearTimeout(handshakeTimer);
    childReady = false;
    if (child === proc) child = null;
    pendingHandshake.resolve = null;
    pendingHandshake.reject = null;
    stopOwnedBackendLeftBehind(proc.pid);
    if (shuttingDown) return;
    if (autostartFailure) {
      return fail(autostartFailure);
    }
    log('ERROR', `MCP child exited (code=${code} signal=${signal})`);
    if (state === 'ready' && restarts < MAX_RESTARTS) {
      restarts += 1;
      state = 'installing';
      stageText = `Ragnarok stopped unexpectedly and is restarting (attempt ${restarts} of ${MAX_RESTARTS}).`;
      setTimeout(() => supervise(), 3000);
      return;
    }
    fail(`the Ragnarok server stopped (exit code ${code}).`);
  });

  // Handshake with the child, as a client would. Client messages are not forwarded until it succeeds.
  const init = new Promise((resolve, reject) => {
    pendingHandshake.resolve = resolve;
    pendingHandshake.reject = reject;
  });
  proc.stdin.write(
    JSON.stringify({
      jsonrpc: '2.0',
      id: HANDSHAKE_ID,
      method: 'initialize',
      params: { protocolVersion: PROTOCOL_VERSION, capabilities: {}, clientInfo: { name: 'ragnarok-connector', version: VERSION } },
    }) + '\n',
  );
  handshakeTimer = setTimeout(() => {
    log('ERROR', 'the MCP child did not answer initialize in time; stopping it');
    proc.kill();
  }, HANDSHAKE_TIMEOUT_MS);
  init
    .then((msg) => {
      clearTimeout(handshakeTimer);
      if (msg.error) throw new Failure(`the Ragnarok server refused to start: ${msg.error.message}`);
      proc.stdin.write(JSON.stringify({ jsonrpc: '2.0', method: 'notifications/initialized' }) + '\n');
      childReady = true;
      state = 'ready';
      restarts = 0;
      log('INFO', 'Ragnarok is ready: the MCP server answers tool calls');
    })
    .catch((err) => {
      clearTimeout(handshakeTimer);
      if (!shuttingDown) fail(err instanceof Failure ? err.message : String(err.message || err));
    });
}

// If the child was killed hard, its owned backend could outlive it. Stop it here.
function stopOwnedBackendLeftBehind(childPid) {
  const file = path.join(CONNECTOR_DIR, 'backend.json');
  let st;
  try {
    st = JSON.parse(fs.readFileSync(file, 'utf8'));
  } catch (_) {
    return;
  }
  if (!st || st.owner !== childPid || typeof st.pid !== 'number') return;
  log('WARN', `the MCP child exited while owning backend pid=${st.pid}; stopping that backend`);
  killTree(st.pid);
  try {
    fs.unlinkSync(file);
  } catch (_) {
    /* already gone */
  }
}

function killTree(pid) {
  try {
    if (IS_WIN) {
      cp.spawnSync('taskkill', ['/T', '/F', '/PID', String(pid)], { stdio: 'ignore' });
    } else {
      process.kill(-pid, 'SIGTERM');
    }
  } catch (_) {
    /* not running */
  }
}

// ── supervision ────────────────────────────────────────────────────────────────
class Failure extends Error {}

function fail(reason) {
  state = 'failed';
  failureText = reason;
  log('ERROR', `Ragnarok could not start: ${reason}`);
}

async function supervise() {
  try {
    stageText = `Ragnarok is starting (checking the Ragnarok folder at ${REPO}).`;
    if (!REPO_IS_CHECKOUT) {
      throw new Failure(
        `no Ragnarok checkout at ${REPO}. Clone Ragnarok there or set the "Ragnarok folder" setting to the folder that contains backend/ and build/.`,
      );
    }
    await ensureVenv();
    startChild();
  } catch (err) {
    fail(err instanceof Failure ? err.message : `unexpected error: ${err.message || err}`);
  }
}

// ── lifecycle ──────────────────────────────────────────────────────────────────
function shutdown(reason) {
  if (shuttingDown) return;
  shuttingDown = true;
  log('INFO', `stopping (${reason})`);
  state = 'stopped';
  const proc = child;
  if (!proc) return process.exit(0);
  try {
    proc.stdin.end();
  } catch (_) {
    /* closed */
  }
  const forceAt = setTimeout(() => proc.kill('SIGKILL'), 8000);
  proc.on('exit', () => {
    clearTimeout(forceAt);
    process.exit(0);
  });
  setTimeout(() => proc.kill('SIGTERM'), 3000);
}

function readJson(file, fallback) {
  try {
    return JSON.parse(fs.readFileSync(file, 'utf8'));
  } catch (_) {
    return fallback;
  }
}

function parsePort(text) {
  const n = Number(text);
  if (!Number.isInteger(n) || n < 1 || n > 65535) return 8000;
  return n;
}

// ── entry ──────────────────────────────────────────────────────────────────────
process.stdin.on('end', () => shutdown('client closed stdin'));
process.on('SIGTERM', () => shutdown('SIGTERM'));
process.on('SIGINT', () => shutdown('SIGINT'));
process.on('SIGHUP', () => shutdown('SIGHUP'));

readline.createInterface({ input: process.stdin }).on('line', (line) => {
  const text = line.trim();
  if (!text) return;
  let msg;
  try {
    msg = JSON.parse(text);
  } catch (_) {
    return writeClient({ jsonrpc: '2.0', id: null, error: { code: -32700, message: 'parse error' } });
  }
  try {
    handleClientMessage(msg);
  } catch (err) {
    log('ERROR', `while handling a client message: ${err.stack || err}`);
  }
});

log('INFO', `Ragnarok connector ${VERSION} starting: repo=${REPO} api=${API_BASE} session=${SESSION_ID} autonomy=${AUTONOMY} remote=${REMOTE}`);
if (!REPO_IS_CHECKOUT) log('WARN', `no Ragnarok checkout at ${REPO}; logs go to ${EFFECTIVE_LOG_DIR}`);
supervise();
