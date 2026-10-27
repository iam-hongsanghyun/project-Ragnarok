# Ragnarok connector (Claude Desktop extension)

`dist/ragnarok.mcpb` is a one-click install of the Ragnarok MCP tools for Claude
Desktop (and Cowork, where it is enabled). User steps are in
[`docs/bifrost-agent.md`](../docs/bifrost-agent.md) §10.

## Files

| File | Role |
|---|---|
| `manifest.json` | Source manifest: identity, `user_config`, `mcp_config`. No `tools` list. |
| `server/index.js` | Launcher and relay (Node, stdlib only). |
| `icon.png` | 512×512, rendered from `build/favicon.svg`. |
| `.mcpbignore` | Excludes applied when packing the staged folder. |
| `../scripts/build_connector.sh` | Stages, validates and packs → `dist/ragnarok.mcpb`. |
| `../scripts/connector_manifest.py` | Fills `tools` from `backend.mcp.server` and writes the server instructions. |
| `../backend/mcp/autostart.py` | Backend start/reuse/stop, run by the Python MCP server. |

Build: `scripts/build_connector.sh` (needs Node.js and `.venv-pypsa`). It pins
`@anthropic-ai/mcpb@2.1.2`, runs `validate`, `pack` and `info`, and lists the archive.

## Design

**Thin bundle, not a code bundle.** The bundle carries only the launcher. The
checkout supplies the code, the committed `build/` GUI and the Python venv. The
PyPSA stack (highspy, netCDF4, tables, prophet) is native and per-architecture, so
it cannot be bundled once for arm64 macOS, x86 macOS and Windows. A bundled copy of
the code would also go stale as soon as the checkout moves. The cost is that a
checkout must exist; the manifest defaults to `~/github/ragnarok`.

**`server.type: "node"`.** Claude Desktop ships its own Node runtime (Anthropic
help article "Getting started with local MCP servers on Claude Desktop": "Claude
Desktop includes a built-in Node.js environment"). One stdlib launcher then runs
on both macOS and Windows, so there are no `.sh`/`.ps1` wrappers to keep in step.

**The handshake is answered at once.** The client's `initialize` and
`tools/list` are answered by the launcher from the manifest and the server
instructions. `tools/call` returns `isError` with "still starting" (and the log
path) or with the failure reason. The Python child is spawned only after the venv
is ready, and the launcher then performs the MCP handshake with it and relays
JSON-RPC. A first-run install of several minutes therefore never blocks `initialize`.

**Venv bootstrap.** The launcher probes absolute Python paths (Claude Desktop's
PATH is minimal) for Python 3.11+, preferring 3.13. It creates `.venv-pypsa` with
`python -m venv`, installs with `uv pip install` when uv exists and with pip
otherwise, and writes `.connector/deps.sha256`. A matching stamp skips the
install. A venv older than 3.11 is rebuilt, as `serve.command` does. The stamp is a
separate file, so `run.command`'s `.req_hash` is untouched.

**Backend lifecycle.** The Python child runs `backend/mcp/autostart.py` before
serving. If nothing answers on `RAGNAROK_API_BASE`, it starts
`python -m uvicorn backend.app.main:app --host 127.0.0.1 --port <port>`, the same
single worker as `serve.command local`, in its own process group, with
`RAGNAROK_FRONTEND_DIST` set to `build/`. It waits for `/api/health`. It stops the
backend on exit only if it started it. If something else holds the port, or a
Ragnarok checkout at another path does (`/api/identity` root), it refuses and names
the holder. A backend left behind by a killed launcher is adopted and stopped
later. The launcher also stops the backend if its child was killed hard.

**Session `default`.** The connector defaults to the session the web app opens, so
Claude's edits appear live in the browser. The cost is that Claude can overwrite
what is open there. Users who want isolation set a different session name.

**`RAGNAROK_DATA_DIR` is not set.** Setting it moves the working data, and the
bundled examples then disappear (`backend/app/routers/examples.py` resolves the
examples relative to the data dir). The connector leaves it unset.

**Autonomy and remote.** `autonomy` maps to `RAGNAROK_MCP_AUTONOMY`. A non-empty
`api_base` means "remote backend": autostart is off and only the client side runs.

## Where things live

Each checkout has its own `.connector/` (git-ignored):

- `logs/connector.log`: the launcher, the child's stderr, and autostart decisions.
- `logs/backend.log`: uvicorn's output.
- `logs/install.log`: pip/uv output.
- `backend.json`: the backend this checkout started, and its owner, for stopping and adoption.
- `deps.sha256`: the dependency stamp.

If the checkout is missing, logs go to `~/Library/Logs/Ragnarok/` (macOS) or
`%LOCALAPPDATA%\Ragnarok\Logs` (Windows).

## Failure messages

Shown as the tool result (one sentence, what to do, the log path):

| Situation | Message starts with |
|---|---|
| Folder not set or no checkout | `no Ragnarok checkout at …` |
| No Python 3.11+ | `Python 3.11 or newer was not found.` |
| Install failed | `python -m pip exited with code …` / `uv … exited with code …` |
| Port held by another program | `Port 8000 is in use by …` |
| Checkout at another path | `Port 8000 is served by the Ragnarok checkout at …` |
| Backend did not start | `The Ragnarok backend exited with code …` / `did not answer /api/health …` |

## Tests

`backend/tests/test_mcp_autostart.py` (decisions, spawn, stop, refusal) and
`backend/tests/test_connector_bundle.py` (manifest ↔ launcher ↔ registry agreement).
The end-to-end check is a smoke test: launch `server/index.js` as Claude Desktop does
(empty environment, `cwd=/`, `mcp_config` substituted), then send `initialize`,
`tools/list` and `tools/call get_world_state`.
