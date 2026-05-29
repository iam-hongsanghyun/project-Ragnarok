# backend-utils — Function Reference

Covers: `backend/pypsa/utils/coerce.py`, `backend/pypsa/utils/workbook.py`, `backend/pypsa/utils/series.py`, `backend/pypsa/utils/annuity.py`, `backend/pypsa/constants.py`, `backend/pypsa/pypsa_schema.py`.

---

## backend/pypsa/utils/coerce.py

Safe type-coercion utilities used throughout the network and results layers.

### `number(value: Any, default: float = 0.0) -> float`

Converts any scalar to a float, returning `default` on failure.

Params: `value` — raw input (str, int, float, bool, None, etc.); `default` — value to return when conversion fails or the result is NaN or Inf.

Behaviour:
- `None` and `""` return `default` immediately.
- `True` returns `1.0`; `False` returns `0.0`.
- Strings are parsed via `float(value)`.
- NaN and Inf return `default`.

Used everywhere numeric workbook fields are read from `dict[str, Any]` rows, where the value may be a string, None, or a bare numeric.

### `text(value: Any, default: str = "") -> str`

Converts any value to a stripped string, returning `default` for None or blank.

Params: `value` — raw input; `default` — returned when value is None or the stripped string is empty.

Used to safely read name/carrier/bus string fields from workbook rows.

---

## backend/pypsa/utils/workbook.py

Workbook accessor utilities.

### `workbook_rows(model: dict[str, list[dict[str, Any]]], sheet: str) -> list[dict[str, Any]]`

Returns the rows of `model[sheet]` as a list, or `[]` if the sheet is absent.

Params: `model` — workbook dict as sent by the frontend (`{sheet_name: [row_dict, ...]}`); `sheet` — sheet name to look up.

Notes: the result is always a `list`, never `None`. Used by `validate_model` to inspect sheets before building the network. Does not mutate the input dict.

---

## backend/pypsa/utils/series.py

Pandas Series helper utilities.

### `safe_series(frame: pd.DataFrame, name: str) -> pd.Series`

Returns the column `name` from `frame`, or a zero-filled `pd.Series` with the same index if the column is absent.

Params: `frame` — a `pd.DataFrame` (typically `network.<component>_t.<attr>`); `name` — column (component) name.

Used by `build_storage_series` to gracefully handle storage units that have no dispatch in a given solve (e.g. a unit that was idle throughout the horizon).

### `weighted_sum(series: pd.Series, weights: pd.Series) -> float`

Computes the weighted sum of `series` using `weights`.

Params: `series` — values to sum; `weights` — per-snapshot weights (e.g. `network.snapshot_weightings["generators"]`).

The weights are reindexed to match `series.index` with a fill value of 1.0 so snapshot-index mismatches (e.g. after stochastic collapse) do not raise. Returns `float((series * aligned_weights).sum())`.

Used for energy integrals (MWh = sum of MW * h_per_snapshot) throughout `results/`.

---

## backend/pypsa/utils/annuity.py

Capital recovery factor calculation for capacity expansion.

### `annuity_factor(discount_rate: float, lifetime_years: float) -> float`

Returns the capital recovery factor (CRF), also called the annuity factor.

Params:
- `discount_rate` — real discount rate (dimensionless, e.g. 0.07 for 7%).
- `lifetime_years` — asset economic lifetime (years).

Formula (when `discount_rate > 0` and `lifetime_years > 0`):

```
CRF = r * (1 + r)^n / ((1 + r)^n - 1)
```

where `r = discount_rate` and `n = lifetime_years`.

Special cases:
- `lifetime_years <= 0` returns `1.0` (full cost in one period).
- `discount_rate <= 0` returns `1.0 / lifetime_years` (straight-line amortisation, no time-value-of-money).

Used in `build_network` to convert overnight `capital_cost` (currency/MW) to an annualised cost (currency/MW/yr) for extendable assets before passing them to the LP solver.

---

## backend/pypsa/constants.py

Carrier and generator colour utilities.

### `DEFAULT_CARRIER_PALETTE: list[str]`

A 30-colour hex palette used as the fallback for carriers not assigned an explicit colour. Drawn from Tableau and matplotlib colour cycles.

### `_normalize_carrier_key(value: str) -> str`

Returns the carrier name stripped and lowercased, for consistent hash-based colour assignment.

### `default_carrier_color(carrier: str) -> str`

Returns a deterministic hex colour for `carrier` by hashing its normalised name against `DEFAULT_CARRIER_PALETTE`.

Params: `carrier` — carrier name string.
Returns: hex string like `"#4e79a7"`. Returns `"#94a3b8"` for empty carrier names.

Notes: the same carrier name always produces the same colour across runs (deterministic hash), but the colour is not guaranteed stable across palette changes.

### `carrier_color(network: pypsa.Network, carrier: str) -> str`

Returns the carrier's colour, preferring the `color` column in `network.carriers` when present and non-blank, falling back to `default_carrier_color`.

Params: `network` — solved or built network; `carrier` — carrier name.

### `generator_color(network: pypsa.Network, generator: str) -> str`

Returns the generator's colour, preferring an explicit `color` column in `network.generators`, then delegating to `carrier_color` for the generator's carrier.

Params: `network`; `generator` — generator name.

---

## backend/pypsa/pypsa_schema.py

Schema accessors — reads `pypsa_schema.json` and `network_import_policy.json` from the frontend config directory.

### `load_pypsa_schema() -> dict[str, Any]`

Reads and caches `frontend/Ragnarok_default/src/config/pypsa_schema.json`. Returns the full schema dict. Uses `lru_cache(maxsize=1)`. Called by all other functions in this module.

Notes: the schema is generated by frontend build-time codegen and shared between frontend and backend. The backend reads it to stay schema-driven — new PyPSA attributes added to the schema are automatically handled without changes to the Python code.

### `load_network_import_policy() -> dict[str, Any]`

Reads and caches `frontend/Ragnarok_default/src/config/network_import_policy.json`. Used by `_apply_network_sheet` to determine which `network` sheet fields to apply at runtime import. Uses `lru_cache(maxsize=1)`.

### `component_schema(sheet_name: str) -> dict[str, Any] | None`

Returns the schema dict for a single component sheet, or `None` if the sheet is not in the schema. Equivalent to `load_pypsa_schema()["components"].get(sheet_name)`.

### `component_sheets() -> list[str]`

Returns the list of all schema-defined component sheet names (e.g. `["buses", "generators", "loads", ...]`).

### `non_component_sheets() -> set[str]`

Returns the set of sheet names recorded in `schema["meta"]["non_component_sheets"]` — sheets like `"snapshots"` and `"network"` that are not PyPSA component tables. Used by `build_full_outputs` to skip non-component sheets.

### `network_runtime_import_fields() -> list[dict[str, Any]]`

Returns the subset of network import policy fields that have `enabled_for_runtime_import: true`. Used by `_apply_network_sheet` to decide which fields to process from the `network` workbook row.

### `input_static_attributes(sheet_name: str) -> set[str]`

Returns the set of attribute names that may appear as static columns in the workbook for `sheet_name`. Includes attributes with `status="input"` and `storage` in `{"static", "static_or_series"}`. Hybrid attributes (e.g. `marginal_cost`, `efficiency`) are included because they can be provided as a scalar.

### `input_temporal_attributes(sheet_name: str) -> set[str]`

Returns the set of attribute names that may appear as time-series sheet columns. Includes attributes with `status="input"` and `storage` in `{"series", "static_or_series"}`.

### `output_attributes(sheet_name: str) -> set[str]`

Returns the set of output-only attribute names for `sheet_name` from `schema["output_attributes"]`. Used by the validator to detect and note output columns present in input rows.

### `required_input_static_attributes(sheet_name: str) -> set[str]`

Returns the set of input static attributes that are required (i.e. `required: true` and `storage != "series"`). Used by the validator's `_check_required_fields` and by `_check_duplicate_names` (which looks for `"name"` in the required set).

### `bus_reference_attributes(sheet_name: str) -> list[dict[str, Any]]`

Returns a list of attribute dicts for input static columns that represent bus references — columns named `"bus"` or `"bus0"`, `"bus1"`, etc. Each dict includes at minimum `"attribute"` (str) and `"required"` (bool). Used by the validator and by `_drop_broken_bus_refs` in `components.py`.
