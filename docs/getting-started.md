# Getting Started with Ragnarok

Ragnarok is a local web application for building and solving PyPSA energy-system models without writing Python. A React/TypeScript frontend communicates with a FastAPI backend that uses PyPSA and linopy to formulate and solve optimization problems with the HiGHS solver. Everything runs on your own machine; no data leaves your computer.

This guide gets you from a fresh clone to a solved model. For a full reference of every setting and view, see [docs/guides/USER_MANUAL.md](guides/USER_MANUAL.md).

---

## Prerequisites

| Requirement | Why |
|---|---|
| Node.js (includes npm) | Builds and serves the frontend |
| git | Required by the PyPSA pip dependency |
| Python 3.11 or later | Runs the FastAPI backend |

`run.command` checks all three on startup and prints a download URL if any are missing.

---

## Launch in one step

From the project root, run:

```bash
bash run.command
```

On macOS you can also double-click `run.command` in Finder.

The script does the following in order:

1. Checks that `npm`, `git`, and Python 3.11+ are available.
2. Creates a `.venv-pypsa` virtual environment (first run only).
3. Installs backend dependencies from `backend/requirements.txt` (skipped when the file has not changed since the last launch).
4. Installs frontend npm packages in `frontend/Ragnarok_default/node_modules/` (first run only).
5. Frees ports 3000 and 8000, killing any stale processes on those ports.
6. Starts the backend: `uvicorn backend.app.main:app` on `127.0.0.1:8000`.
7. Polls `http://127.0.0.1:8000/api/health` until the backend is ready.
8. Reads `plugins.env` (if present) and starts any registered plugin servers.
9. Starts the React frontend on port 3000 and opens it in your default browser.

The first launch is slower because it downloads Python and npm packages. Subsequent launches typically start in a few seconds.

All processes (backend, plugin servers, frontend) are shut down cleanly when you close the terminal or press Ctrl+C.

---

## First steps once the browser opens

The browser navigates to `http://localhost:3000` automatically. The top bar shows **Ready. Open a workbook or import a project.**

**To open an existing workbook** — click **M** in the left activity bar, then click **Open** in the file toolbar. Select an `.xlsx` PyPSA workbook.

**To import a previously exported project** — use **Import Project** instead of **Open**. This restores inputs, solved outputs, and all run settings from a file you previously saved with **Export Project**.

**To solve** — click the **Run** button in the top bar. A dialog summarizes the active configuration. Click **Run model** to submit. The backend solves with HiGHS and streams progress; the top bar shows an elapsed timer. When the solve completes, click **A** in the activity bar to open Analytics.

---

## Quick tour of the five views

The narrow activity bar on the far left switches between views. Each button shows a single letter.

### B — Build

A step-by-step wizard that guides you through authoring a model in dependency order: Network, Carriers, Buses, Generators, Loads, Storage, Lines/Links, Review. Each step shows a table editor on the left and an interactive map in the center. Click the map to place a bus; click two buses to draw a line or link.

### M — Model

A spreadsheet editor for all component sheets (buses, generators, loads, lines, links, storage units, stores, transformers, carriers, global constraints, and time-series profiles). A read-only topology map on the right reflects the live model. Use this view for detailed edits and for all file operations (Open, Save, Import/Export).

### S — Settings

All run configuration is here, grouped into four sections:

| Section | What you configure |
|---|---|
| **Setup** | Scenarios (named presets capturing the full run config), simulation window (snapshot range and resolution), multi-year pathway planning (investment periods), rolling-horizon dispatch |
| **Policy** | Carbon price (flat or year-indexed schedule), Standard Constraints (the `global_constraints` sheet — PyPSA-native system-wide constraints such as CO2 budgets), Advanced Constraints (custom DSL constraints added on top of the standard solve) |
| **Solve** | Stochastic scenario generation, security-constrained (SCLOPF) settings, HiGHS solver options (threads and algorithm) |
| **App** | Per-carrier color swatches, date format for parsing input workbooks, currency symbol, discount rate, load shedding |

### A — Analytics

Results appear here after a successful run. Four sub-tabs:

- **Validation** — structural issues (errors, warnings, notes) with click-to-navigate links back to the relevant row.
- **Result** — a fixed KPI strip (total cost, dispatch, average price, peak load, renewables share, emissions) plus an overview dashboard.
- **Analytics** — a free-form dashboard where you add, remove, resize, and rearrange chart cards. Fifteen built-in layout presets are available. Click any asset on the analytics map to switch charts to per-asset focus.
- **Comparison** — a side-by-side table of selected entries from the run history rail.

### P — Plugins

Shows installed plugins. Click **Install plugin** and select a `.zip` to add one; **Uninstall** removes it. There is no enable/disable — a plugin is simply installed or not. Each plugin renders its own GUI from its manifest and runs in the browser; a plugin may also drive its own local server (registered in `plugins.env`) for heavy work. See [Plugin authoring](guides/PLUGIN_AUTHORING.md).

---

## Plugins and plugin servers

A plugin is a `.zip` file you install in the Plugins tab. Plugins that need their own local server (for example, to run a custom data-import backend) can register that server in `plugins.env`.

Copy the example file to get started:

```bash
cp plugins.env.example plugins.env
```

Open `plugins.env` and add one line per plugin server in the format:

```
<absolute path to server directory>|<run command>
```

Example:

```
/Users/you/my-plugin/backend|python server.py --port 8765
```

Blank lines and lines starting with `#` are ignored. `run.command` launches each registered server automatically on startup, using the server directory's own `.venv` if one exists (so plugin dependencies stay isolated from Ragnarok's Python environment). Plugin servers communicate only with the frontend; they do not talk to the Ragnarok backend.

For details on writing your own plugin, see [docs/guides/PLUGIN_AUTHORING.md](guides/PLUGIN_AUTHORING.md).

---

## Where to go next

| Document | Read it for |
|---|---|
| [docs/guides/USER_MANUAL.md](guides/USER_MANUAL.md) | Complete reference for every view, setting, dialog, export format, and troubleshooting scenario |
| [docs/guides/PLUGIN_AUTHORING.md](guides/PLUGIN_AUTHORING.md) | How to write, package, and register a Ragnarok plugin |
| [docs/architecture/ARCHITECTURE.md](architecture/ARCHITECTURE.md) | System overview, tech stack, repo layout, and data flow between frontend and backend |
| [docs/CAPABILITIES.md](CAPABILITIES.md) | Detailed support matrix — what Ragnarok currently handles fully, partially, or not at all |
