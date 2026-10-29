"""The run-options reference: every key a run submission carries, in one place.

``POST /api/queue`` / ``/api/validate`` take ``{sessionId, scenario,
options}``. The browser fills them from a scenario preset
(``frontend/.../features/scenario/buildRunPayload.ts``); this module documents each
key and nested field once - type, default, unit, allowed values, meaning, and the
backend reader that consumes it - and the MCP ``describe_run_options`` tool serves it.

One source of truth:

* defaults come from :mod:`backend.app.scenario_presets` (the port of the preset defaults),
* the field tables below carry only what a default cannot say (type, unit, meaning),
* ``backend/tests/test_run_options_reference.py`` fails when the frontend sends a key
  (``buildRunPayload.ts``, ``App.tsx`` batch ``runLabel``, the ``lib/types`` config
  interfaces) that this reference lacks, or a default drifts from ``scenarios.ts``.

Extension point: another module that adds a run option calls
:func:`register_options` with its entries (see :data:`EXTRA_OPTIONS`); no edit of the
tables below is needed. Entry shape: :class:`RunOption`.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from . import scenario_presets as sp

_RESULTS = "backend/pypsa/results/__init__.py (run_pypsa)"
_NETWORK = "backend/pypsa/network/__init__.py (build_network)"


@dataclass
class RunOption:
    """One documented key. ``path`` is dotted from ``scenario.`` / ``options.``; ``[]`` marks a list item."""

    path: str
    type: str
    meaning: str
    default: Any = None
    unit: str | None = None
    allowed: list[Any] | None = None
    reader: str | None = None
    #: ``ui`` = the browser sends it; ``api`` = accepted but never sent by the UI;
    #: ``alias`` = legacy spelling still read; ``unread`` = sent but no backend code reads it.
    source: str = "ui"
    group: str = ""
    required: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v not in (None, "", False) or k == "default"}


#: Entries added by other modules (PyPSA-1.4 options, plugins). See :func:`register_options`.
EXTRA_OPTIONS: list[RunOption] = []


def register_options(entries: list[RunOption]) -> None:
    """Add options to the reference (idempotent by ``path``). The extension point."""
    known = {e.path for e in EXTRA_OPTIONS}
    for entry in entries:
        if entry.path not in known:
            EXTRA_OPTIONS.append(entry)
            known.add(entry.path)


# ── scenario.* ───────────────────────────────────────────────────────────────

_SCENARIO: list[RunOption] = [
    RunOption("scenario.carbonPrice", "number", "Flat carbon price, handled by the carbon-pricing module: PyPSA gets price x carriers.co2_emissions / efficiency x output as an extra term of the OBJECTIVE (marginal_cost is left as the workbook states it, so n.statistics.opex is the fuel cost and the carbon cost is that term). Ignored per snapshot when options.carbonPriceSchedule has a row for that snapshot's year.", 0, "currency/tCO2", reader="backend/app/carbon_pricing (config_from_run, extra_functionality)", required=True),
    RunOption("scenario.discountRate", "number", "The project discount rate: used by the finance outputs (NPV/IRR) and written into the workbook by Forge -> Fill discount rate. It no longer converts any cost at run time: PyPSA annuitises each overnight_cost row with the row's own discount_rate.", 0.05, "fraction/year (0.05 = 5%)", reader="backend/pypsa/results/finance.py; Forge fill_discount_rate"),
    RunOption("scenario.constraints[]", "object[]", "Standard constraint table rows; only rows with enabled=true are applied (a missing 'enabled' means off). Fields below.", [], reader="backend/pypsa/network/custom_constraints.py (apply_custom_constraints)"),
    RunOption("scenario.constraints[].enabled", "boolean", "Apply this row.", False, reader="custom_constraints.py"),
    RunOption("scenario.constraints[].metric", "string", "Which constraint (see 'metrics' in the reference for units and whether a carrier is needed).", None, allowed=sorted(["co2_cap", "max_load_shed", "carrier_max_gen", "carrier_min_gen", "carrier_max_share", "carrier_min_share", "carrier_max_cf", "carrier_min_cf", "carrier_max_cap", "carrier_min_cap", "carrier_max_cap_share", "carrier_min_cap_share"]), reader="custom_constraints.py"),
    RunOption("scenario.constraints[].carrier", "string", "Generator carrier the constraint binds to; EXACT, case-sensitive match against generators.carrier (not the carriers sheet). Required for carrier_* metrics. An enabled row whose carrier no generator uses REFUSES the run.", "", reader="custom_constraints.py; pre-run guard backend/app/run_guards.py"),
    RunOption("scenario.constraints[].value", "number", "Limit, in the metric's unit (MWh, MW, %, tCO2/MWh).", None, reader="custom_constraints.py"),
    RunOption("scenario.constraints[].label", "string", "Display label used in solver notes.", None, reader="custom_constraints.py"),
    RunOption("scenario.constraints[].id", "string", "Row id (UI only).", None, source="ui", reader="not read by the solver"),
    RunOption("scenario.constraints[].unit", "string", "Display unit (UI only).", None, source="ui", reader="not read by the solver"),
    RunOption("scenario.constraintSpecs[]", "object[]", "Structured custom constraints (the compiled form of the text DSL). When this key is PRESENT (even []) it is used and the text DSL / DSL sheet is not. One spec = lhs terms, sense, rhs terms.", None, reader="backend/pypsa/network/constraint_dsl.py (apply_constraint_specs)"),
    RunOption("scenario.constraintSpecs[].id", "string", "Spec text/label (shown in solver notes).", None, reader="constraint_dsl.py"),
    RunOption("scenario.constraintSpecs[].sense", "string", "Comparator.", None, allowed=["<=", ">=", "=="], reader="constraint_dsl.py"),
    RunOption("scenario.constraintSpecs[].lhs[]", "object[]", "Left-hand terms. Fields: coef (number), kind (gen|cap|cf|emissions|load_shed|const), carrier (legacy single selector), column + values[] (generator column in the set; column omitted with values = the carrier column).", None, reader="constraint_dsl.py"),
    RunOption("scenario.constraintSpecs[].rhs[]", "object[]", "Right-hand terms, same shape as lhs[].", None, reader="constraint_dsl.py"),
    RunOption("scenario.customDsl", "string", "Constraint DSL as text, one line per constraint, '#' comments (e.g. 'gen(coal) <= 1000', 'cap(solar & wind) >= 500'). Used when constraintSpecs is absent. If BOTH are absent the model's RAGNAROK_CustomDSL sheet text is used (precedence: constraintSpecs > customDsl > sheet). Lines that do not parse REFUSE the run.", None, reader="backend/pypsa/network/constraint_dsl.py (apply_dsl_constraints); precedence in backend/app/run_guards.py", source="api"),
    RunOption("scenario.label", "string", "Fallback run label for the queue card when options.runLabel/scenarioLabel are absent.", None, source="api", reader="backend/app/main.py (_queue_label)"),
]

# ── options.* scalars ────────────────────────────────────────────────────────

_SCALARS: list[RunOption] = [
    RunOption("options.backend", "string", "Optimisation backend id. Only 'pypsa' exists; anything else is a 400.", "pypsa", allowed=["pypsa"], reader="backend/app/backends (get_backend)"),
    RunOption("options.snapshotStart", "integer", "First snapshot row (0-based index into the snapshots sheet) of the modelled window.", 0, "snapshot rows", reader=_NETWORK + " (windowing)"),
    RunOption("options.snapshotEnd", "integer", "End of the window, exclusive. Used as end - start when snapshotCount is absent. end <= start refuses the run.", None, "snapshot rows", reader=_NETWORK),
    RunOption("options.snapshotCount", "integer", "Number of snapshots modelled from snapshotStart. Wins over snapshotEnd. <= 0 refuses the run. Absent (with snapshotEnd) = every snapshot.", None, "snapshot rows", reader=_NETWORK),
    RunOption("options.snapshotWeight", "integer", "REMOVED as a run option (core cleanup step 4): a value above 1 refuses the run (it used to point-sample every Nth row). Resolution is a visible transform: Forge -> Temporal, POST /api/transform/temporal (resample 'Nh' takes block means and writes the snapshots, weightings and series into the workbook). Only 1 is accepted; it is read for stored runs from before build version 4.", 1, "rows per modelled step", reader=_NETWORK),
    RunOption("options.forceLp", "boolean", "PyPSA's linearized unit commitment: the committable binaries become continuous, every UC constraint stays (nothing is cleared). Refused for maintainable units: run the visible step 'Relax maintenance' (POST /api/model/relax-maintenance) first.", False, reader="backend/pypsa/optimise_options.py (linearized_unit_commitment); " + _NETWORK),
    RunOption("options.enableLoadShedding", "boolean", "Call PyPSA's n.optimize.add_load_shedding: one generator per bus (\"<bus> load shedding\", carrier LoadShedding) at loadSheddingCost, sized by the system peak of static and time-series loads, so an infeasible-by-capacity model solves instead of failing.", False, reader="backend/pypsa/network/load_shedding.py"),
    RunOption("options.adequacyReadout", "boolean", "The default resource-adequacy readout every run carries (renewable ensemble vs load: LOLE / EENS, payload key `adequacy`). false skips it - a study whose scope excludes formal adequacy indices, or one that only needs the dispatch, then neither computes nor stores them. The opt-in Monte Carlo studies (outageMcConfig, elccConfig, ...) are separate and stay off unless enabled.", True, reader="backend/app/adequacy/hooks.py"),
    RunOption("options.loadSheddingCost", "number", "Value of lost load for the shedding generators.", 1000, "currency/MWh", reader="backend/pypsa/network/load_shedding.py"),
    RunOption("options.ownerColumn", "string", "Name of the generators/storage column holding the owner/company tag, used by company, merchant, bid-strategy, PPA and asset-swap analyses.", "owner", reader=_RESULTS + ", backend/pypsa/results/company.py"),
    RunOption("options.carbonPriceSchedule[]", "object[]", "Year -> carbon price curve; overrides scenario.carbonPrice per snapshot (each snapshot takes its year's row; see backend/app/carbon_pricing/config.py for the year-resolution rule). Fields: year, price.", [], reader="backend/app/carbon_pricing/config.py"),
    RunOption("options.carbonPriceSchedule[].year", "integer", "Calendar year the price starts to apply.", None, "year", reader="carbon_pricing/config.py"),
    RunOption("options.carbonPriceSchedule[].price", "number", "Carbon price in that year.", None, "currency/tCO2", reader="carbon_pricing/config.py"),
    RunOption("options.modelOverrides[]", "object[]", "Per-run model cell patches applied to the run's model snapshot at submit time (never to the session). Each sets sheet[name].column = value on an EXISTING row; unknown sheet/name rows are skipped.", None, reader="backend/app/scenario_overrides.py"),
    RunOption("options.modelOverrides[].sheet", "string", "Sheet name, e.g. generators.", None, reader="scenario_overrides.py"),
    RunOption("options.modelOverrides[].name", "string", "Row 'name' to patch.", None, reader="scenario_overrides.py"),
    RunOption("options.modelOverrides[].column", "string", "Column (PyPSA attribute) to set, e.g. p_nom.", None, reader="scenario_overrides.py"),
    RunOption("options.modelOverrides[].value", "number|string|boolean", "New cell value.", None, reader="scenario_overrides.py"),
    RunOption("options.scenarioLabel", "string", "Label the stored run is tagged with (drives the Comparison pivot).", None, reader="backend/app/run_store.py, main.py (_queue_label)"),
    RunOption("options.runLabel", "string", "Leads the History run-name derivation; give each run of a batch a distinct one.", None, source="ui", reader="backend/app/run_store.py"),
    RunOption("options.filename", "string", "Source file name; part of the run-name derivation and the export header.", None, reader="backend/app/run_store.py, project_workbook.py"),
    RunOption("options.dateFormat", "string", "Date format hint stored with the run for re-export.", "auto", allowed=["auto", "dmy", "mdy", "ymd"], reader="backend/app/project_workbook.py"),
    RunOption("options.currencySymbol", "string", "Symbol shown next to money in results and notes.", "$", reader=_RESULTS),
    RunOption("options.solverType", "string", "HiGHS LP method: auto lets HiGHS pick; hipo uses HiPO where the build has it, else ipm.", "auto", allowed=["auto", "simplex", "ipm", "pdlp", "hipo"], reader=_RESULTS + " (_build_solver_options)"),
    RunOption("options.solverThreads", "integer", "HiGHS threads. 0 = automatic: the queue splits the machine's cores between concurrent solves.", 0, "threads", reader=_RESULTS + " (_build_solver_options), main.py (_resolve_cores)"),
    RunOption("options.solveAcceptance", "string", "lenient also accepts a validated solve whose HiGHS condition is 'unknown' (interior point without crossover); strict needs condition 'optimal'.", "lenient", allowed=["lenient", "strict"], reader=_RESULTS),
    RunOption("options.objectiveAutoScale", "boolean", "Pass HiGHS user_objective_scale=-1 (results-neutral; faster on wide cost ranges). The UI sends true; absent means off.", True, reader=_RESULTS + " (_build_solver_options)"),
    RunOption("options.buildVersion", "integer", "Build schema the run was built under (2 = PyPSA cost semantics; 3 = carbon price as an objective term and e_sum / GlobalConstraint constants as PyPSA horizon totals). 4 = no run-time stride, test-run sampling and rolling in hours as modules, ramps and UC times in RAGNAROK_TimeUnits, PyPSA's own ramp constraint and load shedding. Stamped by the server on every stored run; a run without it is re-derived through the legacy-run migration (including the old stride). Not sent by the UI.", None, source="api", reader=_NETWORK),
]

# ── nested config blocks: field -> (type, unit, meaning[, allowed]) ──────────

_BLOCK_INFO: dict[str, tuple[str, str]] = {
    "pathwayConfig": ("Multi-year investment pathway (PyPSA investment periods): capacity is optimised across periods, each weighted. Needs a 'period' column on every snapshots row (snapshotMappingMode explicit_period_column) and enabled=true.", "backend/pypsa/pathway.py (parse_pathway_config), network/validators.py"),
    "rollingConfig": ("Rolling-horizon dispatch: PyPSA solves overlapping windows in sequence, carrying storage state, dispatch and commitment across them. Window and overlap are given in HOURS and converted with the weights the run uses. Cyclic storage is refused (visible step: POST /api/model/make-noncyclic).", "backend/pypsa/rolling.py"),
    "samplingConfig": ("Sampled snapshot blocks ('test run'): solve a reduced, re-weighted snapshot set that represents the full window.", "backend/pypsa/sampling.py"),
    "stochasticConfig": ("Two-stage stochastic planning: shared investment, per-scenario dispatch under weighted uncertainty overrides. Cannot be combined with custom constraints or reserve.", "backend/pypsa/stochastic.py"),
    "securityConstrainedConfig": ("SCLOPF - security-constrained optimal power flow (N-1 line outages inside the solve).", _RESULTS),
    "reserveConfig": ("Operating-reserve co-optimisation: units keep headroom; a reserve price is reported next to the energy price. Not with stochastic.", "backend/pypsa/network/reserves.py"),
    "outageMcConfig": ("Thermal forced-outage Monte Carlo: distribution of LOLE / EUE over synthetic years.", "backend/pypsa/results/outage_mc.py"),
    "correlatedSamplingConfig": ("Correlated multi-driver Monte Carlo: one weather stress factor moves demand up and renewables/inflow down together.", "backend/pypsa/results/correlated_sampling.py"),
    "rampConfig": ("Default ramp rate (fraction of p_nom per hour) for generators without their own, written into RAGNAROK_TimeUnits terms and converted for the run's weights; PyPSA's native ramp constraint enforces it (also under rolling horizon and stochastic).", "backend/pypsa/network/time_units.py (ramp_config_rows)"),
    "elccConfig": ("Effective load-carrying capability (capacity credit) of wind/solar/storage via outage-inclusive LOLE.", "backend/pypsa/results/elcc.py"),
    "convergenceConfig": ("Convergence-controlled outage sampling: draw batches until the target metric's standard error is below tolerance; optional maintenance placement.", "backend/pypsa/results/convergence.py"),
    "lmpDecompositionConfig": ("Split each bus's LMP into energy + congestion and report congestion rent. Post-process, does not change the solve.", "backend/pypsa/results/lmp_decomposition.py"),
    "powerFlowConfig": ("Power-flow study mode: solve network physics (lpf / pf) instead of an LP.", "backend/pypsa/results/power_flow.py"),
    "marketSimConfig": ("Rule-based merit-order market clearing on one zone (not an optimisation).", "backend/pypsa/results/market.py, strategic.py"),
    "contingencyConfig": ("N-1 contingency study: branch loading under each single outage.", "backend/pypsa/results/contingency.py"),
    "mgaConfig": ("Modelling-to-generate-alternatives: map the near-optimal capacity space around the cost optimum.", "backend/pypsa/results/mga.py"),
    "merchantConfig": ("Merchant / price-taker analysis: one owner's profit against a price signal.", "backend/pypsa/results/merchant.py"),
    "bidStrategyConfig": ("Bid-strategy simulator (fixed markup) and optimal-bid sweep for one owner.", "backend/pypsa/results/bid_strategy.py, optimal_bid.py"),
    "assetSwapConfig": ("Asset-swap / repowering what-if: retire matched generators, add a replacement, compare before/after.", "backend/pypsa/results/asset_swap.py"),
    "essConfig": ("ESS business case: sweep battery sizes against arbitrage on the run's prices; NPV / IRR / payback per size.", "backend/pypsa/results/ess.py"),
    "ppaConfig": ("PPA contract valuation: fixed-price CfD vs the run's LMP, both sides.", "backend/pypsa/results/ppa.py"),
    "demandResponseConfig": ("Demand response: shiftable load (energy conserved) and optional price-elastic demand. The visible step POST /api/demand-response/apply writes the dr_* rows into the workbook and the run builds them; a workbook without those rows is rewired at build time (legacy, said in the notes).", "backend/app/demand_response"),
    "financeConfig": ("Optional debt assumptions for the company-finance DSCR. gearing 0 = all equity.", "backend/pypsa/results/finance.py"),
}

_N = "number"
_I = "integer"
_B = "boolean"
_S = "string"

_FIELDS: dict[str, dict[str, tuple]] = {
    "pathwayConfig": {
        "planningMode": (_S, None, "Mirrors enabled; the backend reads enabled.", ["single_period", "pathway"]),
        "enabled": (_B, None, "Run as a multi-period pathway."),
        "snapshotMappingMode": (_S, None, "explicit_period_column: every snapshots row has a 'period' value matching periods[]; repeat_all_snapshots: every period reuses all snapshots.", ["explicit_period_column", "repeat_all_snapshots"]),
        "periods[]": ("object[]", None, "Investment periods, increasing and unique."),
        "periods[].period": (_I, "year", "Period label (e.g. 2030); must equal the snapshots 'period' values."),
        "periods[].objectiveWeight": (_N, "-", "Weight of this period's cost in the objective."),
        "periods[].yearsWeight": (_N, "years", "Number of years the period represents (annuity/OPEX weighting)."),
        "selectedPeriod": (_I, "year", "UI cursor (which period is shown); the builder fills it with the first period when unset."),
    },
    "rollingConfig": {
        "enabled": (_B, None, "Solve in rolling windows."),
        "horizonHours": (_N, "hours", "Window length in hours; converted to snapshots as ceil(hours / step) with the run's weights. Wins over horizonSnapshots."),
        "overlapHours": (_N, "hours", "Overlap between consecutive windows in hours (0 <= overlap < horizon)."),
        "terminalSoc": (_B, None, "Soft terminal state of charge on the LAST window (RE7): storage units and stores must end the horizon with at least their horizon-start energy, "
                        "enforced as soc_end + shortfall >= initial with a penalised shortfall (options.rollingConfig.terminalSocPenalty), so it can never make a window infeasible. "
                        "An explicit option of the rolling module, default OFF; declared in the run notes when on. Ignored in pathway runs."),
        "horizonSnapshots": (_I, "snapshots", "Window length in snapshots (old presets; ignored when horizonHours is set)."),
        "overlapSnapshots": (_I, "snapshots", "Overlap in snapshots (old presets; ignored when overlapHours is set)."),
        "stepSnapshots": (_I, "snapshots", "horizon - overlap; derived and echoed by the UI, the backend recomputes it."),
    },
    "samplingConfig": {
        "enabled": (_B, None, "Solve sampled blocks instead of the whole window."),
        "mode": (_S, None, "count = N equally spaced blocks; gap = block + gap repeating; average = ONE synthetic block of the positional mean of all periods ('average week').", ["count", "gap", "average"]),
        "blockSize": (_I, "snapshots", "Snapshots per block (>= 1)."),
        "blockCount": (_I, "blocks", "Blocks, mode count (>= 1)."),
        "gapSnapshots": (_I, "snapshots", "Skipped snapshots between blocks, mode gap (>= 0)."),
        "scaleStartUpCosts": (_B, None, "Multiply start_up_cost / shut_down_cost of committable units by the representation factor (PyPSA charges them per event, unweighted). Default true; declared in the run notes."),
    },
    "stochasticConfig": {
        "enabled": (_B, None, "Run stochastic."),
        "scenarios[]": ("object[]", None, "Uncertainty scenarios; weights are PyPSA scenario probabilities and must sum to 1 (a run with another sum is refused)."),
        "scenarios[].id": (_S, None, "Scenario id (UI)."),
        "scenarios[].name": (_S, None, "Scenario name."),
        "scenarios[].weight": (_N, "-", "Probability weight."),
        "scenarios[].overrides[]": ("object[]", None, "Attribute overrides applied in this scenario."),
        "scenarios[].overrides[].id": (_S, None, "Override id (UI)."),
        "scenarios[].overrides[].sheet": (_S, None, "Component sheet, e.g. generators or loads."),
        "scenarios[].overrides[].attribute": (_S, None, "PyPSA attribute, e.g. p_max_pu, marginal_cost, p_set."),
        "scenarios[].overrides[].scopeType": (_S, None, "Which rows: all, one name, or a carrier.", ["all", "name", "carrier"]),
        "scenarios[].overrides[].scopeValue": (_S, None, "The name or carrier when scopeType is not all."),
        "scenarios[].overrides[].operation": (_S, None, "multiply the attribute by value, or set it to value.", ["multiply", "set"]),
        "scenarios[].overrides[].value": (_N, "-", "Multiplier or new value."),
    },
    "securityConstrainedConfig": {"enabled": (_B, None, "Run SCLOPF.")},
    "reserveConfig": {
        "enabled": (_B, None, "Co-optimise reserve."),
        "requirementType": (_S, None, "fraction of demand, the largest unit, or both (max).", ["fraction", "largestUnit", "both"]),
        "fraction": (_N, "fraction of demand", "Reserve held, 0.1 = 10%."),
        "providers": (_S, None, "thermal excludes variable renewables.", ["all", "thermal"]),
        "reserveCost": (_N, "currency/MW", "Cost of holding reserve added to the objective (usually 0)."),
    },
    "outageMcConfig": {
        "enabled": (_B, None, "Run the outage Monte Carlo."),
        "nMembers": (_I, "samples", "Synthetic years drawn."),
        "seed": (_I, None, "RNG seed (reproducible)."),
        "forcedOutageRate": (_N, "fraction", "EFOR used for generators with no forced_outage_rate column."),
        "mttrHours": (_N, "hours", "Mean time to repair."),
        "includeRenewableEnsemble": (_B, None, "Also sample renewable profiles."),
        "physicalRiskUplift": (_B, None, "Raise each generator's outage rate by its Physical Risk damage ratio (needs physicalRiskSessionId with a completed run)."),
        "physicalRiskSessionId": (_S, None, "Physical-risk session id to take the damage ratios from."),
    },
    "correlatedSamplingConfig": {
        "enabled": (_B, None, "Run correlated sampling."),
        "nMembers": (_I, "samples", "Synthetic years."),
        "seed": (_I, None, "RNG seed."),
        "loadSensitivity": (_N, "-", "Demand response to the common stress factor."),
        "renewableSensitivity": (_N, "-", "Renewable output response to the factor."),
        "inflowSensitivity": (_N, "-", "Hydro inflow response to the factor."),
        "loadStd": (_N, "-", "Independent demand noise, std dev."),
        "renewableStd": (_N, "-", "Independent renewable noise, std dev."),
        "inflowStd": (_N, "-", "Independent inflow noise, std dev."),
    },
    "rampConfig": {
        "enabled": (_B, None, "Fill RAGNAROK_TimeUnits with a default ramp rate for generators that have none of their own; the time-units module converts it for the run's weights and PyPSA's native ramp constraint enforces it."),
        "rampLimitUp": (_N, "fraction of p_nom per hour", "Max upward ramp, 0.5 = 50%/h."),
        "rampLimitDown": (_N, "fraction of p_nom per hour", "Max downward ramp."),
        "appliesTo": (_S, None, "thermal excludes variable renewables.", ["all", "thermal"]),
    },
    "elccConfig": {
        "enabled": (_B, None, "Compute ELCC."),
        "nMembers": (_I, "samples", "Synthetic years for the LOLE."),
        "seed": (_I, None, "RNG seed."),
        "forcedOutageRate": (_N, "fraction", "EFOR fallback."),
        "mttrHours": (_N, "hours", "Mean time to repair."),
        "carriers": ("string[]", None, "Carriers to evaluate; empty = variable renewables + storage."),
    },
    "convergenceConfig": {
        "enabled": (_B, None, "Run convergence-controlled sampling."),
        "targetMetric": (_S, None, "Metric whose standard error is controlled.", ["eue", "lole"]),
        "tolerance": (_N, "relative std error", "Stop when the standard error falls below this."),
        "batchSize": (_I, "samples", "Samples per batch."),
        "maxMembers": (_I, "samples", "Hard cap on total samples."),
        "seed": (_I, None, "RNG seed."),
        "forcedOutageRate": (_N, "fraction", "EFOR fallback."),
        "mttrHours": (_N, "hours", "Mean time to repair."),
        "maintenanceEnabled": (_B, None, "Schedule planned maintenance into low-load windows."),
        "maintenanceWeeks": (_N, "weeks", "Length of each maintenance outage."),
        "maintenanceCarriers": ("string[]", None, "Carriers to schedule maintenance for; empty = auto."),
    },
    "lmpDecompositionConfig": {
        "enabled": (_B, None, "Decompose LMPs."),
        "referenceMode": (_S, None, "How the energy-price reference is chosen.", ["load-weighted", "min", "bus"]),
        "referenceBus": (_S, None, "Bus used as reference when referenceMode is bus."),
    },
    "powerFlowConfig": {
        "enabled": (_B, None, "Run a power-flow study instead of an LP."),
        "linear": (_B, None, "true = linear DC lpf(); false = AC Newton-Raphson pf()."),
    },
    "marketSimConfig": {
        "enabled": (_B, None, "Run the market simulation."),
        "pricing": (_S, None, "Settlement: all dispatched units paid the clearing price, or their own bid.", ["uniform", "payAsBid"]),
        "voll": (_N, "currency/MWh", "Price applied to unserved energy."),
        "chargeQuantile": (_N, "quantile 0-1", "Storage charges at or below this price quantile."),
        "dischargeQuantile": (_N, "quantile 0-1", "Storage discharges at or above this price quantile."),
        "clearingModel": (_S, None, "singleSided = fixed demand merit order; twoSided = part of demand bids a willingness to pay.", ["singleSided", "twoSided"]),
        "demandElasticFraction": (_N, "fraction 0-1", "Share of demand that is price-elastic (twoSided)."),
        "demandWtp": (_N, "currency/MWh", "Elastic demand's willingness to pay (twoSided)."),
        "demandBids[]": ("object[]", None, "Extra stepped demand curve (twoSided): {fraction, wtp} steps."),
        "demandBids[].fraction": (_N, "fraction 0-1", "Share of load in this step."),
        "demandBids[].wtp": (_N, "currency/MWh", "Willingness to pay of this step."),
        "strategic": ("object", None, "Optional price-maker analysis riding the simulation (fields below); omit to skip."),
        "strategic.enabled": (_B, None, "Run the strategic sweep."),
        "strategic.owner": (_S, None, "Owner (value in the owner column) acting strategically."),
        "strategic.strategy": (_S, None, "Bid adder or capacity withholding.", ["markup", "withhold"]),
        "strategic.maxAdder": (_N, "currency/MWh", "Grid top for the bid adder (markup)."),
        "strategic.maxWithholdPct": (_N, "fraction 0-1", "Grid top for the withheld capacity share (withhold)."),
        "strategic.steps": (_I, "grid points", "Points on the sweep."),
        "strategic.rivalOwner": (_S, None, "Optional second strategic owner (alternating best responses ~ Nash); '' = none."),
        "strategic.rounds": (_I, "rounds", "Best-response rounds with a rival."),
    },
    "contingencyConfig": {"enabled": (_B, None, "Run the N-1 study.")},
    "mgaConfig": {
        "enabled": (_B, None, "Run MGA after the optimum."),
        "slack": (_N, "fraction of optimal cost", "Alternatives stay within 1 + slack of the optimal cost."),
        "carriers": ("string[]", None, "Extendable-generator carriers to explore; empty = all (backend-capped)."),
    },
    "merchantConfig": {
        "enabled": (_B, None, "Run the merchant analysis."),
        "owner": (_S, None, "Owner value whose assets are analysed."),
        "priceSource": (_S, None, "lmp = the run's system marginal price; series = an exogenous price.", ["lmp", "series"]),
        "flatPrice": (_N, "currency/MWh", "Flat price when priceSource is series."),
        "priceSeries": ("number[]", "currency/MWh", "Optional hourly price overriding flatPrice (series mode)."),
    },
    "bidStrategyConfig": {
        "enabled": (_B, None, "Run the bid-strategy analysis."),
        "mode": (_S, None, "fixed simulates the given markup; optimal sweeps for the profit-maximising one.", ["fixed", "optimal"]),
        "owner": (_S, None, "Owner whose offers are marked up."),
        "markupType": (_S, None, "percent: offer = cost x (1 + markup); absolute: offer = cost + markup.", ["percent", "absolute"]),
        "markup": (_N, "fraction (percent) or currency/MWh (absolute)", "Fixed-mode markup."),
        "maxMarkup": (_N, "same unit as markup", "Upper bound of the optimal-mode sweep."),
        "steps": (_I, "grid points", "Sweep steps (optimal mode)."),
    },
    "assetSwapConfig": {
        "enabled": (_B, None, "Run the asset-swap what-if."),
        "removeFilters[]": ("object[]", None, "Which generators to retire: matched on ALL filters; values within one filter are OR."),
        "removeFilters[].field": (_S, None, "Generator column to match (carrier, owner, ...)."),
        "removeFilters[].values": ("string[]", None, "Accepted values of that column."),
        "addCarrier": (_S, None, "Carrier of the replacement."),
        "addCapitalCost": (_N, "currency/MW", "Replacement cost when the carrier is not already in the model."),
        "addMarginalCost": (_N, "currency/MWh", "Replacement marginal cost."),
        "replaceRatio": (_N, "-", "Replacement MW = retired MW x ratio (a ceiling when sizeReplacement)."),
        "sizeReplacement": (_B, None, "Let the optimiser size the replacement instead of fixing it at retired MW x ratio."),
        "addStorageMW": (_N, "MW", "Paired battery power (0 = none)."),
        "addStorageHours": (_N, "hours", "Paired battery duration."),
        "addStorageCapexPerMW": (_N, "currency/MW", "Paired battery capex."),
    },
    "essConfig": {
        "enabled": (_B, None, "Run the ESS business case."),
        "bus": (_S, None, "Bus to site the battery; '' = automatic (most price-volatile bus)."),
        "maxHours": (_N, "hours", "Storage duration at rated power."),
        "capitalCostPerMW": (_N, "currency/MW", "Capital cost of power capacity."),
        "minSizeMW": (_N, "MW", "Smallest size in the sweep."),
        "maxSizeMW": (_N, "MW", "Largest size in the sweep."),
        "steps": (_I, "sizes", "Sizes in the sweep."),
        "roundTripEfficiency": (_N, "fraction 0-1", "Round-trip efficiency."),
        "capitalCostPerMWh": (_N, "currency per MWh per year", "Annualised capital cost of energy capacity. Optional; absent = 0."),
        "fixedOmPerMWYear": (_N, "currency per MW per year", "Fixed O&M. Optional; absent = 0."),
        "variableCostPerMWh": (_N, "currency/MWh discharged", "Variable cost. Optional; absent = 0."),
        "lifetimeYears": (_N, "years", "Project life. Optional; absent/0 = 15 years (reported in the result notes)."),
        "standingLoss": (_N, "fraction/hour 0-1", "Stored energy lost per hour. Optional; absent = 0."),
    },
    "ppaConfig": {
        "enabled": (_B, None, "Value the PPA."),
        "owner": (_S, None, "Owner whose generation backs the PPA (volumeType generation)."),
        "volumeType": (_S, None, "generation = the owner's hourly output; flat = a constant block.", ["generation", "flat"]),
        "flatMW": (_N, "MW", "Block size when volumeType is flat."),
        "strikePrice": (_N, "currency/MWh", "Contract strike price."),
    },
    "demandResponseConfig": {
        "enabled": (_B, None, "Make loads shiftable."),
        "loads": ("string[]", None, "Load names to make shiftable; empty = all loads."),
        "shiftFraction": (_N, "fraction of peak 0-1", "Buffer power as a share of each load's peak."),
        "maxShiftHours": (_N, "hours", "Buffer duration (shiftable energy = power x hours)."),
        "elasticEnabled": (_B, None, "Also model price-elastic demand."),
        "elasticFraction": (_N, "fraction 0-1", "Share of each load that is price-responsive."),
        "wtpMax": (_N, "currency/MWh", "Highest willingness-to-pay tier; the curve ramps down to ~0."),
    },
    "financeConfig": {
        "gearing": (_N, "fraction 0-1", "Debt share of overnight capex; 0 = all equity (then DSCR is null)."),
        "interestRate": (_N, "fraction/year", "Debt interest rate."),
        "tenorYears": (_N, "years", "Debt tenor."),
    },
}

#: Fields the backend accepts that the browser never sends (aliases, API-only extras).
_API_ONLY: list[RunOption] = [
    RunOption("options.assetSwapConfig.removeCarrier", "string", "Legacy single-carrier spelling of removeFilters (kept as an alias).", None, source="alias", reader="backend/pypsa/results/asset_swap.py"),
    RunOption("options.merchantConfig.ownerColumn", "string", "Legacy home of ownerColumn for scenarios saved before options.ownerColumn existed.", None, source="alias", reader=_RESULTS),
    RunOption("options.outageMcConfig.forRateUplift", "object", "Filled in by the backend from physicalRiskUplift at submit time; do not send.", None, source="api", reader="backend/app/physical_risk_uplift.py"),
]

_API_ONLY_PATH = {e.path for e in _API_ONLY}

# What a missing nested default means; keys with no default in scenarios.ts (optional extras).
_OPTIONAL_NO_DEFAULT = {
    "options.essConfig.capitalCostPerMWh", "options.essConfig.fixedOmPerMWYear", "options.essConfig.variableCostPerMWh",
    "options.essConfig.lifetimeYears", "options.essConfig.standingLoss",
    "options.marketSimConfig.strategic", "options.merchantConfig.priceSeries",
}

_UNREAD_NESTED = {"options.pathwayConfig.planningMode"}

_METRIC_UNITS = {
    "co2_cap": ("tCO2/MWh", False, "Average emission intensity <= value."),
    "max_load_shed": ("MWh", False, "Total unserved energy <= value."),
    "carrier_max_gen": ("MWh", True, "Total output of carrier <= value."),
    "carrier_min_gen": ("MWh", True, "Total output of carrier >= value."),
    "carrier_max_share": ("%", True, "Carrier dispatch / total dispatch <= value."),
    "carrier_min_share": ("%", True, "Carrier dispatch / total dispatch >= value."),
    "carrier_max_cf": ("%", True, "Carrier capacity factor <= value."),
    "carrier_min_cf": ("%", True, "Carrier capacity factor >= value."),
    "carrier_max_cap": ("MW", True, "Installed/optimised carrier capacity <= value (needs extendable capacity to bind)."),
    "carrier_min_cap": ("MW", True, "Installed/optimised carrier capacity >= value (needs extendable capacity to bind)."),
    "carrier_max_cap_share": ("%", True, "Carrier capacity / total capacity <= value."),
    "carrier_min_cap_share": ("%", True, "Carrier capacity / total capacity >= value."),
}

NOTES: list[str] = [
    "A run body is {sessionId, scenario, options}; submit_solve forwards scenario/options verbatim. To run a SAVED scenario use list_scenarios, then submit_scenario / submit_scenarios (they build the body exactly like the browser).",
    "DSL precedence: scenario.constraintSpecs (when the key is present, even []) > scenario.customDsl > the model's RAGNAROK_CustomDSL sheet (first row, column 'text'), which is applied when neither scenario field is present.",
    "Pre-run guards (the run is refused with a sentence saying what to fix): empty/inverted snapshot window; DSL text that does not parse; an enabled carrier constraint whose carrier no generator uses; plus the model validator's errors. Use validate_model first.",
    "Every config block is a no-op unless its enabled flag is true; omit a block to leave the feature off. A partially specified block takes backend defaults for missing fields (see 'default' per field; the UI always sends the full block).",
    "Study modes that replace the LP (powerFlowConfig, marketSimConfig, contingencyConfig) and the add-on analyses (mga, merchant, bidStrategy, assetSwap, ess, ppa) layer on a normal solve or on stored results; see each block's meaning.",
    "Scenario presets live in the model sheet RAGNAROK_Scenarios (row: id, label, active, notes, json = the preset fields without id/label/notes); carbon schedules in RAGNAROK_CarbonSchedules (id, name, json = [{year, price}]); DSL in RAGNAROK_CustomDSL.",
]


def _default_for(block: str, field_path: str) -> Any:
    """Default of a block's direct field, from the preset defaults (one source of truth)."""
    if "." in field_path:
        return None
    return sp.CONFIG_BLOCKS[block][0]().get(field_path.replace("[]", ""))


def _build_block_entries() -> list[RunOption]:
    out: list[RunOption] = []
    for block, fields in _FIELDS.items():
        meaning, reader = _BLOCK_INFO[block]
        out.append(RunOption(f"options.{block}", "object", meaning, sp.CONFIG_BLOCKS[block][0](), reader=reader, group=block))
        for fpath, info in fields.items():
            typ, unit, desc = info[0], info[1], info[2]
            allowed = info[3] if len(info) > 3 else None
            path = f"options.{block}.{fpath}"
            source = "ui"
            r = reader
            if path in _UNREAD_NESTED:
                source = "unread"
                r = "none (sent by the UI, not read by the backend)"
            out.append(
                RunOption(path, typ, desc, _default_for(block, fpath), unit, allowed, r, source, group=block)
            )
    return out


def _all_entries() -> list[RunOption]:
    entries: list[RunOption] = []
    for e in _SCENARIO:
        e.group = e.group or "scenario"
        entries.append(e)
    for e in _SCALARS:
        e.group = e.group or e.path.split(".")[1].split("[")[0]
        entries.append(e)
    entries.extend(_build_block_entries())
    for e in _API_ONLY:
        e.group = e.path.split(".")[1]
        entries.append(e)
    entries.extend(EXTRA_OPTIONS)
    return entries


def all_entries() -> list[RunOption]:
    """Every documented key (built-in plus :func:`register_options` extras)."""
    return _all_entries()


def documented_paths() -> set[str]:
    return {e.path for e in _all_entries()}


def top_level_keys() -> dict[str, list[str]]:
    """``{"scenario": [...], "options": [...]}`` - the names directly under each section."""
    keys: dict[str, set[str]] = {"scenario": set(), "options": set()}
    for e in _all_entries():
        section, _, rest = e.path.partition(".")
        head = rest.split(".")[0].replace("[]", "")
        if section in keys:
            keys[section].add(head)
    return {k: sorted(v) for k, v in keys.items()}


def validate_options_patch(patch: dict[str, Any]) -> list[str]:
    """Sentences for any top-level key of ``patch`` that is not a documented ``options`` key."""
    if not patch:
        return []
    valid = set(top_level_keys()["options"])
    unknown = sorted(k for k in patch if k not in valid)
    if not unknown:
        return []
    return [f'unknown option(s) {", ".join(unknown)}; valid options keys: {", ".join(sorted(valid))}.']


def _index_row(group: str, entries: list[RunOption]) -> dict[str, Any]:
    head = next((e for e in entries if e.path.count(".") == 1 and not e.path.endswith("[]")), entries[0])
    return {
        "key": group,
        "type": head.type,
        "default": head.default,
        "meaning": head.meaning,
        "fields": len([e for e in entries if e.path != head.path]),
    }


def build_reference(key: str | None = None) -> dict[str, Any]:
    """The reference document.

    ``key=None`` returns the compact index (one row per top-level key: type, default,
    meaning, number of nested fields) plus ``notes``; ``key="essConfig"`` (also
    ``"scenario.constraints"`` / ``"options.solverType"``) returns every field of that key.
    """
    entries = _all_entries()
    if key:
        section, wanted = None, key
        for prefix in ("scenario", "options"):
            if key.startswith(prefix + "."):
                section, wanted = prefix, key[len(prefix) + 1:]
        wanted = wanted.replace("[]", "")
        matches = []
        for e in entries:
            e_section, rest = e.path.split(".", 1)
            rest = rest.replace("[]", "")
            if (section is None or e_section == section) and (rest == wanted or rest.startswith(wanted + ".")):
                matches.append(e)
        if not matches:
            valid = top_level_keys()
            raise KeyError(
                f'unknown run-option key "{key}"; valid: scenario: {", ".join(valid["scenario"])}; '
                f'options: {", ".join(valid["options"])}'
            )
        return {"key": key, "fields": [e.to_dict() for e in matches], "notes": NOTES}
    groups: dict[str, list[RunOption]] = {}
    for e in entries:
        section, rest = e.path.split(".", 1)
        head = rest.split(".")[0].replace("[]", "")
        groups.setdefault(f"{section}.{head}", []).append(e)
    index = []
    for gkey, es in groups.items():
        es_sorted = sorted(es, key=lambda e: e.path.count(".") + e.path.count("[]"))
        index.append(_index_row(gkey, es_sorted))
    return {
        "index": index,
        "metrics": {m: {"unit": u, "needsCarrier": nc, "meaning": d} for m, (u, nc, d) in _METRIC_UNITS.items()},
        "notes": NOTES,
        "howToRead": "Call describe_run_options(key=<key>) for every nested field of one key, e.g. 'options.essConfig' or 'scenario.constraints'.",
    }
