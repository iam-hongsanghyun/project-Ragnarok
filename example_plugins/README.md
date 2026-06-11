# Example plugins

Ragnarok ships **no active plugins** — plugins are purely 3rd-party. This folder
holds **reference examples** only; nothing here is auto-loaded. Install one from
the **Plugins** tab (the single "Install plugin…" button auto-detects the kind),
using the prebuilt archives in [`zips/`](./zips):

| Example | Kind | What it shows |
|---|---|---|
| [`dashboard-importer/`](./dashboard-importer) | **backend** (server-side) | Builds a PyPSA model from a dashboard workbook + GUI settings, **entirely in the Ragnarok backend** (imports the bundled PyPSA source). The model is written straight into the session — it never enters the browser. Demonstrates `transform`. |
| [`ragnarok-region-analyzer/`](./ragnarok-region-analyzer) | **backend** (server-side) | Aggregates a **stored run** by region/carrier (read straight from the backend run store — works on "View result" runs whose series never reach the browser) and charts it, including an inter-region flow map. Demonstrates `analyze` + `options`. |
| [`ragnarok-scenario-analytics/`](./ragnarok-scenario-analytics) | frontend (browser) | System-level analytics for a solved run (mix, SMP, CO₂, LDC). |

## The plugin contract (both kinds)

A plugin exposes any of these hooks:

- `transform(model, config) -> model` — replace the working model.
- `contribute(model, config) -> {sheets, constraints}` — add sheets / constraints.
- `analyze(result, config) -> data` — read-only output for the Output tab.
- `options(name, config, ctx) -> [rows]` — on-demand dropdown values (backend).
- `<action>(config) -> {ok, message, config?}` — named form-action hooks
  (e.g. a "Fill table" button); a returned `config` patch updates the form.

**Frontend plugin** = a `.zip` of `module.json` + `index.js` (browser-evaluated JS;
may call its own local server). **Backend plugin** = a `.zip` of `manifest.json` +
`plugin.py` (runs in the Ragnarok backend; imports the bundled PyPSA source; no
separate server, nothing in `plugins.env`). Installed backend plugins live under
`backend/data/plugins/` (gitignored).

Two backend-plugin rules worth knowing before copying an example:

- **Return-value only.** `transform`/`contribute` get a defensive *copy* of the
  session model — mutating the argument in place never persists anything; only
  the returned dict/fragment is saved.
- **No bare vendored imports.** A plugin that ships its own package (like the
  importer's `dashboard_lib/`) must load it under a plugin-unique module alias —
  never via `sys.path` + a bare `import` — so two installed plugins can't swap
  each other's same-named libraries. See `dashboard-importer/pipeline.py`'s
  `_lib()` loader and `docs/plugin.md` §16.3.

See `docs/plugin.md` for the full authoring guide.

## Rebuilding the install zips

```bash
cd example_plugins/dashboard-importer
zip -rqX ../zips/dashboard-importer.zip manifest.json plugin.py pipeline.py dashboard_lib \
  -x '*/__pycache__/*' '*.pyc'
```
(Frontend examples: `zip ../zips/<id>.zip module.json index.js README.md`.)
