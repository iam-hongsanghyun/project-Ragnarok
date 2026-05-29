# Function Reference — Index

Per-module function reference for the Ragnarok backend and frontend.

Each file documents every public and important internal function in its module group: signature, one-line purpose, parameters (with units where physical), return value, and a note on logic and role.

---

## Backend reference files

| File | Covers |
|---|---|
| [backend-host.md](backend-host.md) | `backend/app/main.py` (all HTTP endpoints, job store, worker/poll helpers), `module_host.py` (module discovery, installation, plugin execution), `config.py`, `models.py` (RunPayload), `backends/base.py` (Backend protocol, BackendError), `backends/registry.py` (register/get/list backends) |
| [backend-adapter.md](backend-adapter.md) | `backend/pypsa/adapter.py` (PypsaBackend: capabilities, run) |
| [backend-network.md](backend-network.md) | `backend/pypsa/network/__init__.py` (build_network, validate_model), `components.py`, `network_sheet.py`, `snapshots.py`, `custom_constraints.py`, `load_shedding.py`, `validators.py` |
| [backend-results.md](backend-results.md) | `backend/pypsa/results/__init__.py` (run_pypsa and pipeline helpers), `full_outputs.py`, `dispatch.py`, `emissions.py`, `expansion.py`, `market.py`, `summaries.py` |
| [backend-modes.md](backend-modes.md) | `backend/pypsa/pathway.py`, `rolling.py`, `stochastic.py`, `carbon_price.py` |
| [backend-utils.md](backend-utils.md) | `backend/pypsa/utils/coerce.py`, `workbook.py`, `series.py`, `annuity.py`, and `backend/pypsa/constants.py` + `pypsa_schema.py` |

---

## Frontend reference files

The following files are authored by the frontend documentation team. They are listed here so the index is complete.

| File | Covers |
|---|---|
| [frontend-app.md](frontend-app.md) | App entry point, routing, global providers |
| [frontend-utils.md](frontend-utils.md) | Utility hooks, formatters, and shared helper functions |
| [frontend-features.md](frontend-features.md) | Feature-slice modules (build, run, results, modules panel) |
| [frontend-views.md](frontend-views.md) | Page-level view components and layout |

---

## Notes on scope

- This reference covers the backend only. Research-level derivations and algorithm explanations are in `docs/ALGORITHM.md`. Architecture overview is in `docs/ARCHITECTURE.md`.
- The solver used throughout is HiGHS. The only supported study mode is `"optimize"`.
- All monetary values in function signatures are in the currency configured by `options["currencySymbol"]` (default `"$"`); physical power is in MW; energy in MWh; emissions in tCO2e unless stated otherwise.
