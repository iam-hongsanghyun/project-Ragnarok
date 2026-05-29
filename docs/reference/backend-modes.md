# backend-modes — Function Reference

Covers: `backend/pypsa/pathway.py`, `backend/pypsa/rolling.py`, `backend/pypsa/stochastic.py`, `backend/pypsa/carbon_price.py`.

---

## backend/pypsa/pathway.py

Multi-investment pathway planning configuration.

### Data classes

#### `PathwayPeriod`

`dataclass`. Fields:
- `period: int` — investment year (e.g. 2030).
- `objective_weight: float` — weight for the objective function in this period.
- `years_weight: float` — represents the number of years this period spans (used by PyPSA for inter-period annualisation).

#### `PathwayConfig`

`dataclass`. Fields:
- `enabled: bool` — True when pathway mode is active.
- `planning_mode: str` — `"pathway"` or `"single_period"`.
- `snapshot_mapping_mode: str` — `"explicit_period_column"` (default) or another mode string. Controls how the `period` column in the `snapshots` sheet is interpreted.
- `periods: list[PathwayPeriod]` — investment periods sorted ascending by year.
- `selected_period: int | None` — the period to display in the UI after a solve (optional).

### `parse_pathway_config(raw: dict[str, Any] | None) -> PathwayConfig`

Builds a `PathwayConfig` from the `options["pathwayConfig"]` JSON object.

Params: `raw` — the `pathwayConfig` dict, or `None`. Defaults to an empty dict.

Activation: `enabled` is True when `raw["enabled"]` is truthy or `raw["planningMode"] == "pathway"`.

Period parsing: each item in `raw["periods"]` must have `period` (convertible to int). `objectiveWeight` and `yearsWeight` default to 1.0. Items with unparseable periods are silently skipped. Periods are sorted ascending.

Returns: a fully populated `PathwayConfig`. When `raw` is None or empty, returns a disabled config with no periods.

---

## backend/pypsa/rolling.py

Rolling-horizon optimisation configuration.

### Data class

#### `RollingHorizonConfig`

`dataclass`. Fields:
- `enabled: bool`
- `horizon_snapshots: int` — total window size (snapshots). Clamped to >= 1.
- `overlap_snapshots: int` — overlap between consecutive windows (snapshots). Clamped to >= 0.
- `step_snapshots: int` — derived as `max(1, horizon - overlap)`. The number of snapshots accepted from each window.
- `preserve_terminal_state: bool` — whether to carry end-of-horizon storage state to the next window (defaults to True).
- `selected_window: int | None` — 1-based window index for UI display (optional).

### `parse_rolling_config(raw: dict[str, Any] | None) -> RollingHorizonConfig`

Builds a `RollingHorizonConfig` from `options["rollingConfig"]`.

Params: `raw` — the `rollingConfig` dict, or `None`.

Defaults: `horizonSnapshots = 168` (one week), `overlapSnapshots = 24` (one day). Both are clamped to their minimum values (1 and 0 respectively). `step_snapshots` is always derived from `horizon - overlap`, not read from the payload.

Returns: a fully populated `RollingHorizonConfig`. When `raw` is None or `enabled` is falsy, returns a disabled config with default dimension values.

---

## backend/pypsa/stochastic.py

Two-stage stochastic planning support.

### Data classes

#### `ScenarioOverride` (frozen)

Describes one attribute override applied to a specific scenario.
- `sheet: str` — component sheet name (e.g. `"generators"`, `"loads"`).
- `attribute: str` — attribute to modify (e.g. `"p_set"`, `"marginal_cost"`).
- `scope_type: str` — `"all"` | `"name"` | `"carrier"`.
- `scope_value: str` — ignored when `scope_type == "all"`; the name or carrier to target.
- `operation: str` — `"multiply"` | `"set"`.
- `value: float` — the multiplier or replacement value.

#### `StochasticScenario` (frozen)

- `name: str`
- `weight: float` — probability weight (normalised to sum=1 by `parse_stochastic_config`).
- `overrides: tuple[ScenarioOverride, ...]`

#### `StochasticConfig` (frozen)

- `enabled: bool`
- `scenarios: tuple[StochasticScenario, ...]`

### `parse_stochastic_config(raw: dict[str, Any] | None) -> StochasticConfig`

Builds a `StochasticConfig` from `options["stochasticConfig"]`.

Activation: `raw["enabled"]` must be truthy and at least two valid scenarios must be present (a single scenario is a deterministic solve). Scenarios with empty names or non-positive weights are skipped. Weights are normalised to sum to 1.0.

Each scenario's `overrides` array is parsed permissively: items with blank `sheet` or `attribute` are skipped. `scopeType` defaults to `"all"`, `operation` to `"multiply"`, `value` to `1.0`.

Returns: disabled `StochasticConfig` if `enabled` is falsy or fewer than two valid scenarios were found.

### `apply_scenarios(network: pypsa.Network, config: StochasticConfig) -> None`

Expands `network` to a stochastic shape and applies per-scenario overrides.

Calls `network.set_scenarios({name: weight})` to expand all static and dynamic frames to a `(scenario, name)` MultiIndex. Then calls `_apply_advanced_override` for each override in each scenario.

Params: `network` — deterministic network, fully built; `config` — stochastic configuration. No-op when `config.enabled` is False.

### `_resolve_override_targets(network, scenario, override) -> pd.Index`

Returns the static-frame row index entries that the override should modify, filtered to the given `scenario.name`.
- `scope_type="all"`: all rows for the scenario.
- `scope_type="name"`: rows where the name level matches `override.scope_value`.
- `scope_type="carrier"`: rows where `static["carrier"] == override.scope_value`.
Returns empty `pd.Index` if the component sheet does not exist or the static frame is not a `MultiIndex`.

### `_apply_advanced_override(network, scenario, override) -> None`

Applies one `ScenarioOverride` to both the static frame and the corresponding dynamic frame (if present). Writes to `comp.static.loc[targets, attr]` and, for time-varying attributes, to `df.loc[:, scenario_cols]` in `comp.dynamic[attr]`. Supports `"multiply"` and `"set"` operations.

### `per_scenario_summaries(network, config, emissions_factors, currency_symbol) -> list[dict[str, Any]]`

Computes one summary row per scenario from a solved stochastic network.

Params: `network` — solved stochastic network (still multi-indexed before collapse); `config` — stochastic config; `emissions_factors` — `{carrier: tCO2/MWh}`; `currency_symbol` — for formatted cost string.

For each scenario, slices the generator dispatch and static frames to that scenario level and computes:
- `totalEnergyMwh` — weighted total generation.
- `totalEmissionsTco2` — weighted total emissions.
- `totalOperatingCost` — weighted total operating cost.
- `totalOperatingCostFormatted` — formatted with thousands separator and currency symbol.
- `loadShedEnergyMwh` — total load-shedding energy (MWh).

Also records `name`, `weight`, `overrideCount`.

### `collapse_to_representative_scenario(network, config) -> str`

Reduces a solved stochastic network in-place to its highest-weight scenario so the deterministic result-extraction pipeline can consume it unchanged.

Slices every static frame from `(scenario, name)` MultiIndex to `name` (using `xs(rep_name, level="scenario")`). Slices every dynamic frame's column `MultiIndex` similarly. Handles empty frames on newer pandas versions where `xs` raises on empty MultiIndex.

Returns: the name of the representative scenario, for surfacing in the UI narrative.

---

## backend/pypsa/carbon_price.py

Carbon price schedule support and generator marginal cost application.

### Data classes

#### `CarbonPriceScheduleEntry` (frozen)

- `year: int`
- `price: float` — currency/tCO2

#### `CarbonPriceConfig` (frozen)

- `scalar: float` — single carbon price (currency/tCO2); used when `is_scheduled` is False.
- `schedule: tuple[CarbonPriceScheduleEntry, ...]` — year-price schedule sorted ascending.
- `is_scheduled: bool` (property) — True when the schedule is non-empty.

### `parse_carbon_price_config(scalar: float, raw_schedule: Any) -> CarbonPriceConfig`

Builds a `CarbonPriceConfig` from the `scenario["carbonPrice"]` scalar and the optional `options["carbonPriceSchedule"]` array.

Params: `scalar` — base carbon price; `raw_schedule` — list of `{year, price}` dicts or `None`.

Schedule parsing: items with non-numeric or non-positive years are skipped; duplicates are resolved last-write-wins; sorted ascending. If `raw_schedule` is None or empty the config uses only the scalar.

### `build_price_series(network: pypsa.Network, config: CarbonPriceConfig) -> pd.Series`

Returns a per-snapshot carbon price series indexed by `network.snapshots`.

When `config.is_scheduled` is False, returns a constant series equal to `config.scalar`.

When scheduled, for each snapshot looks up the snapshot's year (via `_snapshot_years`) and applies the most-recent schedule entry with year <= snapshot year. Falls back to the first (earliest) entry when the snapshot predates the schedule.

Returns: `pd.Series` of dtype float, indexed by `network.snapshots`.

### `apply_carbon_price(network, config, notes, currency_symbol) -> None`

Adds the carbon adder to every emitting generator's marginal cost. Only acts on generators whose carrier has `co2_emissions > 0` in `network.carriers`.

Two code paths:
- **Constant** (scalar or schedule that resolves to a single value): adds `constant * emission_factor` to the static `marginal_cost` column and to any existing time-varying `marginal_cost_t` columns. Preserves the historical static+dynamic behaviour.
- **Varying** (schedule with multiple distinct values): writes all generators onto the time-varying `generators_t.marginal_cost` frame using a per-snapshot adder series `series * emission_factor`. PyPSA's `_t` column overrides the static value during the solve.

Appends a narrative note describing the applied price or schedule.

### `_snapshot_years(snapshots: pd.Index) -> pd.Index`

Extracts the year for each snapshot. For pathway `MultiIndex` with a `period` level, returns the period values directly. For other `MultiIndex` types, uses the last level. For single-level indexes, parses as `DatetimeIndex` and returns `.year`. Falls back to a zero-filled index on parse failure.
