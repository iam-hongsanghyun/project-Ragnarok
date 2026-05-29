# backend-adapter — Function Reference

Covers: `backend/pypsa/adapter.py`.

---

## backend/pypsa/adapter.py

The PyPSA reference backend adapter. Wraps `run_pypsa` (see `backend-results.md`) behind the `Backend` protocol defined in `backend/app/backends/base.py`. No solve logic lives in this file — it is purely a named adapter that reports what PyPSA can do and forwards `run()` calls.

### `class PypsaBackend`

The default Ragnarok backend. Registered automatically in `backend/app/backends/registry.py` on import.

Attributes:
- `name = "pypsa"` — the key used in `options["backend"]` to select this adapter.
- `label = "PyPSA"` — human-readable display string.

#### `capabilities(self) -> dict[str, Any]`

Returns a JSON-serialisable capabilities descriptor used by `GET /api/backends` and consumed by the frontend to gate UI affordances.

Returns a dict with:
- `name` — `"pypsa"`
- `label` — `"PyPSA"`
- `solver` — `"HiGHS"`
- `studyModes` — `["optimize"]` (the only supported study mode; power-flow-only modes are roadmapped, not yet implemented)
- `features` — dict of boolean flags:
  - `singlePeriod`: True
  - `pathway`: True
  - `rollingHorizon`: True
  - `stochastic`: True
  - `securityConstrained`: True
  - `customConstraints`: True
  - `globalConstraints`: True
  - `carbonPrice`: True
  - `loadShedding`: True
  - `unitCommitment`: True

#### `run(self, model: dict[str, list[dict[str, Any]]], scenario: dict[str, Any], options: dict[str, Any] | None = None) -> dict[str, Any]`

Build, solve, and extract results for one case.
Params: `model` — workbook as `{sheet: rows[]}`; `scenario` — `carbonPrice`, `discountRate`, `constraints`, etc.; `options` — run metadata (mode flags, solver tuning, enabled modules). `options` defaults to `{}` when `None`.
Returns: the full Ragnarok result dict produced by `run_pypsa`. See `backend-results.md` for the complete return structure.
Notes: this method is the single handoff point between the backend registry and the PyPSA pipeline. All logic lives in `run_pypsa`.
