# Dashboard Importer — backend (server-side) example plugin

Builds a Ragnarok workbook from a PyPSA **dashboard model** + GUI settings,
**entirely in the Ragnarok backend**. It imports the bundled PyPSA source
(`backend.pypsa`) to construct/validate the network, then writes the result
straight into the **session** — the model never enters the browser.

This is the server-side successor to the frontend dashboard importer (which ran
its own HTTP server and shuttled the whole model through the browser). Running
server-side removes that memory/disk pressure: uploaded model files are cached
content-addressed (one temp file per distinct model, reaped on a TTL) instead of
leaking a copy per request.

## Layout

```
manifest.json     # kind:"backend"; config GUI schema; action hook -> "transform"
plugin.py         # the backend hook: transform(model, config) -> model
pipeline.py       # the build engine (formerly main.py); loads dashboard_lib
                  #   via _lib() under a plugin-unique sys.modules alias —
                  #   never bare-named, never via sys.path (collision-proof)
dashboard_lib/    # topology, region, scaling, snapshots, carriers, …
```

## Install & use

1. **Plugins** tab → *Install plugin…* → choose `../zips/dashboard-importer.zip`.
   It appears under **Backend (server-side)**.
2. In its **Input** tab, set **Model workbook path** to an xlsx on the *server*,
   or upload a **model file**, plus the year / grid-mode / reference-table options.
3. Click **Build & load into Ragnarok (server-side)** → the backend builds the
   model and writes it into the session; the editor rehydrates from there.
4. Press the topbar **Run** to solve. *Uninstall* with the **x** in the rail.

**Energy storage (ESS).** Alongside generator replacement, the *Energy storage*
group can add a `StorageUnit` at every bus where a plant was replaced. Size it
as a **proportion of the replaced capacity** (e.g. 30%) or a **fixed MW** per
bus, with configurable duration (`max_hours`) and round-trip efficiency (split
√ into charge/discharge). Turn on **Capacity expansion** to make it
`p_nom_extendable` between a min/max with a capital cost. The carrier (default
`ESS`) is added to the model's carriers if absent. The per-bus ESS sizing is
previewed in the Output tab next to the reallocation plan.

Solve-time effects travel **as data** (Ragnarok runs no plugin code in-solve):
CF constraints are emitted as `RAGNAROK_CustomDSL` lines, and the carbon price
is folded into generator marginal costs at build time (so it also shows up in
marginal-cost-derived outputs like the merit order).

The hook is `transform(model, config)` — see `plugin.py`. No `plugins.env` entry
and no separate server are needed.
