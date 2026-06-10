# Example plugins

Ragnarok ships **no active plugins** — plugins are purely 3rd-party. This folder
holds **reference examples** only; nothing here is auto-loaded. Install one from
the **Plugins** tab (the single "Install plugin…" button auto-detects the kind),
using the prebuilt archives in [`zips/`](./zips):

| Example | Kind | What it shows |
|---|---|---|
| [`dashboard-importer/`](./dashboard-importer) | **backend** (server-side) | Builds a PyPSA model from a dashboard workbook + GUI settings, **entirely in the Ragnarok backend** (imports the bundled PyPSA source). The model is written straight into the session — it never enters the browser. Demonstrates `transform`. |
| [`ragnarok-region-analyzer/`](./ragnarok-region-analyzer) | frontend (browser) | Aggregates a solved run by region/carrier and charts it. Read-only analytics. |
| [`ragnarok-scenario-analytics/`](./ragnarok-scenario-analytics) | frontend (browser) | System-level analytics for a solved run (mix, SMP, CO₂, LDC). |

## The plugin contract (both kinds)

A plugin exposes any of three hooks:

- `transform(model, config) -> model` — replace the working model.
- `contribute(model, config) -> {sheets, constraints}` — add sheets / constraints.
- `analyze(result, config) -> data` — read-only output for the Output tab.

**Frontend plugin** = a `.zip` of `module.json` + `index.js` (browser-evaluated JS;
may call its own local server). **Backend plugin** = a `.zip` of `manifest.json` +
`plugin.py` (runs in the Ragnarok backend; imports the bundled PyPSA source; no
separate server, nothing in `plugins.env`). Installed backend plugins live under
`backend/data/plugins/` (gitignored).

See `docs/plugin.md` for the full authoring guide.

## Rebuilding the install zips

```bash
cd example_plugins/dashboard-importer
zip -rqX ../zips/dashboard-importer.zip manifest.json plugin.py pipeline.py dashboard_lib \
  -x '*/__pycache__/*' '*.pyc'
```
(Frontend examples: `zip ../zips/<id>.zip module.json index.js README.md`.)
