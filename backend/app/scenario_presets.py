"""Backend resolution of scenario presets, the carbon library and the DSL sheet.

A faithful Python port of the browser-only logic in

* ``frontend/Ragnarok_default/src/lib/results/scenarios.ts``  (preset defaults, clone/normalise, sheet read)
* ``frontend/Ragnarok_default/src/features/scenario/buildRunPayload.ts``  (preset -> ``{scenario, options}``)
* ``frontend/Ragnarok_default/src/lib/results/carbonLibrary.ts``  (carbon-schedule library)
* ``frontend/Ragnarok_default/src/lib/constraints/custom.ts`` + ``dsl.ts``  (DSL sheet, generator carriers)
* ``lib/results/{pathway,rolling,sampling}.ts``  (the small normalisers the builder calls)

so a client that is not the browser (MCP, a script) can run a saved scenario without
hand-translating it. The UI keeps its own TypeScript for now; ``backend/tests/
test_scenario_presets.py`` and ``frontend/.../backendParity.test.ts`` both check the
same golden fixture (``backend/tests/fixtures/scenario_parity.json``) so the two
cannot drift silently.

Everything here is pure (dicts in, dicts out) except :func:`resolve_scenario_run`,
which takes the model as an argument — it never reads the session itself.

Porting notes (JavaScript semantics kept on purpose):

* ``primitiveNumber`` accepts a finite number or a numeric string, never a bool.
* a preset whose JSON cannot be parsed (or whose ``pathwayConfig.periods`` is missing)
  is *dropped* by the browser; here it is dropped too but reported in ``unreadable``
  so the caller can say why a scenario "vanished".
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Callable
from typing import Any

SCENARIO_SHEET = "RAGNAROK_Scenarios"
CARBON_LIBRARY_SHEET = "RAGNAROK_CarbonSchedules"
CUSTOM_DSL_SHEET = "RAGNAROK_CustomDSL"

#: Settings the browser keeps in ``AppSettings`` (not in a preset). Mirrors
#: ``frontend/.../config/app_config.json`` ``settings.defaults``; a test compares them.
UI_RUN_DEFAULTS: dict[str, Any] = {
    "backend": "pypsa",
    "filename": "bifrost-model",
    "dateFormat": "auto",
    "solverThreads": 0,
    "solverType": "auto",
    "solveAcceptance": "lenient",
    "objectiveAutoScale": True,
    "currencySymbol": "$",
}

_MISSING = object()

# ── JavaScript coercion helpers ──────────────────────────────────────────────


def _js_number(value: Any) -> float:
    """``Number(value)`` — NaN for anything that is not number-like."""
    if value is _MISSING:
        return math.nan
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if value is None:
        return 0.0
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return 0.0
        try:
            return float(text)
        except ValueError:
            return math.nan
    return math.nan


def _is_finite(x: float) -> bool:
    return not (math.isnan(x) or math.isinf(x))


def primitive_boolean(value: Any, fallback: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in ("true", "1", "yes"):
            return True
        if normalized in ("false", "0", "no"):
            return False
    return fallback


def primitive_number(value: Any, fallback: float | None = 0) -> Any:
    if isinstance(value, bool):
        return fallback
    if isinstance(value, (int, float)) and _is_finite(float(value)):
        return value
    if isinstance(value, str):
        parsed = _js_number(value)
        if _is_finite(parsed):
            return _num_out(parsed)
    return fallback


def primitive_string(value: Any, fallback: str = "") -> str:
    return value if isinstance(value, str) else fallback


def _num_out(x: float) -> Any:
    """A float that is a whole number comes back as int (JSON ``1`` not ``1.0``)."""
    if isinstance(x, float) and _is_finite(x) and x == int(x):
        return int(x)
    return x


def _js_floor(x: float) -> Any:
    return _num_out(math.floor(x)) if _is_finite(x) else x


def _or(value: Any, default: Any) -> Any:
    """JavaScript ``a ?? b`` (``None`` is both null and undefined here)."""
    return default if value is None else value


def _truthy(value: Any) -> bool:
    """JavaScript truthiness for the few values these rows hold."""
    if value is None or value is _MISSING:
        return False
    if isinstance(value, float) and math.isnan(value):
        return False
    return bool(value)


# ── defaults (scenarios.ts / pathway.ts / rolling.ts / sampling.ts) ──────────


def default_pathway_config() -> dict[str, Any]:
    return {
        "planningMode": "single_period",
        "enabled": False,
        "snapshotMappingMode": "explicit_period_column",
        "periods": [],
        "selectedPeriod": None,
    }


def default_rolling_config() -> dict[str, Any]:
    return {
        "enabled": False,
        "horizonSnapshots": 168,
        "overlapSnapshots": 24,
        "stepSnapshots": 144,
    }


def default_sampling_config() -> dict[str, Any]:
    return {"enabled": False, "mode": "count", "blockSize": 168, "blockCount": 4, "gapSnapshots": 672}


def default_stochastic_config() -> dict[str, Any]:
    return {"enabled": False, "scenarios": []}


def default_sclopf_config() -> dict[str, Any]:
    return {"enabled": False}


def default_reserve_config() -> dict[str, Any]:
    return {"enabled": False, "requirementType": "fraction", "fraction": 0.1, "providers": "all", "reserveCost": 0}


def default_outage_mc_config() -> dict[str, Any]:
    return {
        "enabled": False,
        "nMembers": 200,
        "seed": 42,
        "forcedOutageRate": 0.05,
        "mttrHours": 48,
        "includeRenewableEnsemble": False,
        "physicalRiskUplift": False,
        "physicalRiskSessionId": "",
    }


def default_correlated_sampling_config() -> dict[str, Any]:
    return {
        "enabled": False,
        "nMembers": 200,
        "seed": 42,
        "loadSensitivity": 0.15,
        "renewableSensitivity": 0.3,
        "inflowSensitivity": 0.2,
        "loadStd": 0.05,
        "renewableStd": 0.1,
        "inflowStd": 0.1,
    }


def default_ramp_config() -> dict[str, Any]:
    return {"enabled": False, "rampLimitUp": 0.5, "rampLimitDown": 0.5, "appliesTo": "all"}


def default_elcc_config() -> dict[str, Any]:
    return {"enabled": False, "nMembers": 200, "seed": 42, "forcedOutageRate": 0.05, "mttrHours": 48, "carriers": []}


def default_convergence_config() -> dict[str, Any]:
    return {
        "enabled": False,
        "targetMetric": "eue",
        "tolerance": 0.05,
        "batchSize": 50,
        "maxMembers": 2000,
        "seed": 42,
        "forcedOutageRate": 0.05,
        "mttrHours": 48,
        "maintenanceEnabled": False,
        "maintenanceWeeks": 3,
        "maintenanceCarriers": [],
    }


def default_lmp_decomposition_config() -> dict[str, Any]:
    return {"enabled": False, "referenceMode": "load-weighted", "referenceBus": ""}


def default_power_flow_config() -> dict[str, Any]:
    return {"enabled": False, "linear": False}


def default_market_sim_config() -> dict[str, Any]:
    return {
        "enabled": False,
        "pricing": "uniform",
        "voll": 3000,
        "chargeQuantile": 0.25,
        "dischargeQuantile": 0.75,
        "clearingModel": "singleSided",
        "demandElasticFraction": 0.2,
        "demandWtp": 120,
        "demandBids": [],
    }


def default_contingency_config() -> dict[str, Any]:
    return {"enabled": False}


def default_mga_config() -> dict[str, Any]:
    return {"enabled": False, "slack": 0.05, "carriers": []}


def default_merchant_config() -> dict[str, Any]:
    return {"enabled": False, "owner": "", "priceSource": "lmp", "flatPrice": 0}


def default_bid_strategy_config() -> dict[str, Any]:
    return {
        "enabled": False,
        "mode": "fixed",
        "owner": "",
        "markupType": "percent",
        "markup": 0.2,
        "maxMarkup": 2.0,
        "steps": 8,
    }


def default_asset_swap_config() -> dict[str, Any]:
    return {
        "enabled": False,
        "removeFilters": [],
        "addCarrier": "",
        "addCapitalCost": 0,
        "addMarginalCost": 0,
        "replaceRatio": 1,
        "sizeReplacement": False,
        "addStorageMW": 0,
        "addStorageHours": 4,
        "addStorageCapexPerMW": 20000,
    }


def default_ess_config() -> dict[str, Any]:
    return {
        "enabled": False,
        "bus": "",
        "maxHours": 4,
        "capitalCostPerMW": 30000,
        "minSizeMW": 10,
        "maxSizeMW": 100,
        "steps": 6,
        "roundTripEfficiency": 0.9,
    }


def default_ppa_config() -> dict[str, Any]:
    return {"enabled": False, "owner": "", "volumeType": "generation", "flatMW": 0, "strikePrice": 0}


def default_demand_response_config() -> dict[str, Any]:
    return {
        "enabled": False,
        "loads": [],
        "shiftFraction": 0.2,
        "maxShiftHours": 4,
        "elasticEnabled": False,
        "elasticFraction": 0.2,
        "wtpMax": 200,
    }


def default_owner_column() -> str:
    return "owner"


def default_finance_config() -> dict[str, Any]:
    return {"gearing": 0, "interestRate": 0.05, "tenorYears": 15}


# ── normalise / clone ────────────────────────────────────────────────────────


def _clamp_positive_int(value: Any, fallback: int) -> int:
    if value is None:
        return fallback
    n = _js_number(value)
    return max(1, math.floor(n)) if _is_finite(n) else fallback


def normalize_rolling_config(config: dict[str, Any]) -> dict[str, Any]:
    """Port of ``normalizeRollingConfig`` (rolling.ts).

    A non-numeric ``overlapSnapshots`` is NaN in the browser (serialised as ``null``);
    here it is treated as 0 so the result stays a valid config.
    """
    horizon = _clamp_positive_int(config.get("horizonSnapshots"), 168)
    overlap_raw = _js_number(config.get("overlapSnapshots", _MISSING))
    overlap_floor = math.floor(overlap_raw) if _is_finite(overlap_raw) else 0
    overlap = max(0, min(overlap_floor, horizon - 1))
    out = dict(config)
    out.update(
        {
            "horizonSnapshots": horizon,
            "overlapSnapshots": overlap,
            "stepSnapshots": max(1, horizon - overlap),
        }
    )
    return out


def normalize_sampling_config(config: dict[str, Any]) -> dict[str, Any]:
    """Port of ``normalizeSamplingConfig`` (sampling.ts)."""

    def num_or(value: Any, fallback: float) -> float:
        n = _js_number(value)
        return n if (_is_finite(n) and n != 0) else fallback

    mode = config.get("mode")
    return {
        "enabled": _truthy(config.get("enabled")),
        "mode": mode if mode in ("gap", "average") else "count",
        "blockSize": _js_floor(max(1, math.floor(num_or(config.get("blockSize", _MISSING), 168)))),
        "blockCount": _js_floor(max(1, math.floor(num_or(config.get("blockCount", _MISSING), 4)))),
        "gapSnapshots": _js_floor(max(0, math.floor(num_or(config.get("gapSnapshots", _MISSING), 0)))),
    }


def get_default_selected_period(config: dict[str, Any]) -> Any:
    periods = config.get("periods") or []
    if not periods:
        return None
    selected = config.get("selectedPeriod")
    if selected is not None and any(row.get("period") == selected for row in periods):
        return selected
    return periods[0].get("period")


def _clone_pathway(config: dict[str, Any]) -> dict[str, Any]:
    out = dict(config)
    out["periods"] = [dict(row) for row in config["periods"]]  # KeyError == browser TypeError
    return out


def _clone_stochastic(config: dict[str, Any]) -> dict[str, Any]:
    out = dict(config)
    out["scenarios"] = [
        {**s, "overrides": [dict(o) for o in _or(s.get("overrides"), [])]} for s in _or(config.get("scenarios"), [])
    ]
    return out


def _clone_flat(config: dict[str, Any]) -> dict[str, Any]:
    return dict(config)


def _clone_list_field(field: str) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def clone(config: dict[str, Any]) -> dict[str, Any]:
        out = dict(config)
        out[field] = list(_or(config.get(field), []))
        return out

    return clone


def _clone_market_sim(config: dict[str, Any]) -> dict[str, Any]:
    return {**default_market_sim_config(), **config}


def _clone_merchant(config: dict[str, Any]) -> dict[str, Any]:
    out = dict(config)
    series = config.get("priceSeries")
    if series:
        out["priceSeries"] = list(series)
    else:
        out.pop("priceSeries", None)
    return out


def _clone_asset_swap(config: dict[str, Any]) -> dict[str, Any]:
    out = dict(config)
    out["removeFilters"] = [{**f, "values": list(_or(f.get("values"), []))} for f in _or(config.get("removeFilters"), [])]
    return out


def clone_schedule(schedule: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    return [dict(row) for row in (schedule or [])]


def clone_model_overrides(overrides: list[Any] | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for o in overrides or []:
        if not isinstance(o, dict) or not (_truthy(o.get("sheet")) and _truthy(o.get("name")) and _truthy(o.get("column"))):
            continue
        item = {"sheet": o["sheet"], "name": o["name"], "column": o["column"]}
        if "value" in o and o["value"] is not None:
            item["value"] = o["value"]
        out.append(item)
    return out


#: key -> (default factory, clone). Order is the order the browser writes them.
CONFIG_BLOCKS: dict[str, tuple[Callable[[], dict[str, Any]], Callable[[dict[str, Any]], dict[str, Any]]]] = {
    "pathwayConfig": (default_pathway_config, _clone_pathway),
    "rollingConfig": (default_rolling_config, lambda c: normalize_rolling_config(dict(c))),
    "stochasticConfig": (default_stochastic_config, _clone_stochastic),
    "securityConstrainedConfig": (default_sclopf_config, _clone_flat),
    "reserveConfig": (default_reserve_config, _clone_flat),
    "outageMcConfig": (default_outage_mc_config, _clone_flat),
    "correlatedSamplingConfig": (default_correlated_sampling_config, _clone_flat),
    "rampConfig": (default_ramp_config, _clone_flat),
    "elccConfig": (default_elcc_config, _clone_list_field("carriers")),
    "convergenceConfig": (default_convergence_config, _clone_list_field("maintenanceCarriers")),
    "lmpDecompositionConfig": (default_lmp_decomposition_config, _clone_flat),
    "powerFlowConfig": (default_power_flow_config, _clone_flat),
    "marketSimConfig": (default_market_sim_config, _clone_market_sim),
    "contingencyConfig": (default_contingency_config, _clone_flat),
    "mgaConfig": (default_mga_config, _clone_list_field("carriers")),
    "merchantConfig": (default_merchant_config, _clone_merchant),
    "bidStrategyConfig": (default_bid_strategy_config, _clone_flat),
    "assetSwapConfig": (default_asset_swap_config, _clone_asset_swap),
    "essConfig": (default_ess_config, _clone_flat),
    "ppaConfig": (default_ppa_config, _clone_flat),
    "demandResponseConfig": (default_demand_response_config, _clone_list_field("loads")),
    "financeConfig": (default_finance_config, _clone_flat),
    "samplingConfig": (default_sampling_config, lambda c: normalize_sampling_config(c)),
}


def build_scenario_preset(inp: dict[str, Any]) -> dict[str, Any]:
    """Port of ``buildScenarioPreset``: fill defaults and deep-copy every block."""
    out: dict[str, Any] = {
        "id": _or(inp.get("id"), None) or "scenario-unsaved",
        "label": (str(inp.get("label")).strip() if inp.get("label") is not None else "") or "Scenario",
        "notes": _or(inp.get("notes"), ""),
        "snapshotStart": inp.get("snapshotStart"),
        "snapshotEnd": inp.get("snapshotEnd"),
        "snapshotWeight": inp.get("snapshotWeight"),
        "carbonPrice": inp.get("carbonPrice"),
        "carbonPriceSchedule": clone_schedule(inp.get("carbonPriceSchedule")),
        "discountRate": inp.get("discountRate"),
        "forceLp": inp.get("forceLp"),
        "enableLoadShedding": inp.get("enableLoadShedding"),
        "loadSheddingCost": inp.get("loadSheddingCost"),
    }
    for key, (default, clone) in CONFIG_BLOCKS.items():
        out[key] = clone(_or(inp.get(key), default()))
    out["ownerColumn"] = _or(inp.get("ownerColumn"), default_owner_column()) or default_owner_column()
    out["constraints"] = [dict(row) for row in inp.get("constraints") or []]
    out["modelOverrides"] = clone_model_overrides(inp.get("modelOverrides"))
    return out


def _normalize_catalog(catalog: dict[str, Any]) -> dict[str, Any]:
    scenarios = catalog["scenarios"]
    if not scenarios:
        return {"activeScenarioId": None, "scenarios": []}
    active = catalog.get("activeScenarioId")
    active_exists = active is not None and any(s["id"] == active for s in scenarios)
    out: list[dict[str, Any]] = []
    for s in scenarios:
        n = dict(s)
        n["label"] = str(s["label"]).strip() or "Scenario"
        n["notes"] = _or(s.get("notes"), "")
        n["carbonPriceSchedule"] = clone_schedule(s.get("carbonPriceSchedule"))
        for key, (default, clone) in CONFIG_BLOCKS.items():
            n[key] = clone(_or(s.get(key), default()))
        n["ownerColumn"] = _or(s.get("ownerColumn"), default_owner_column()) or default_owner_column()
        n["constraints"] = [dict(row) for row in s.get("constraints") or []]
        n["modelOverrides"] = clone_model_overrides(s.get("modelOverrides"))
        out.append(n)
    return {"activeScenarioId": active if active_exists else scenarios[0]["id"], "scenarios": out}


def _scenario_from_row(row: dict[str, Any]) -> dict[str, Any]:
    """One ``RAGNAROK_Scenarios`` row -> preset. Raises on what the browser's try/catch swallows."""
    sid = primitive_string(row.get("id")).strip()
    raw_json = row.get("json")
    payload = json.loads(raw_json) if isinstance(raw_json, str) and raw_json.strip() else {}
    if not isinstance(payload, dict):
        raise TypeError("scenario json is not an object")
    merchant = payload.get("merchantConfig")
    owner_column = payload.get("ownerColumn")
    if owner_column is None:
        owner_column = merchant.get("ownerColumn") if isinstance(merchant, dict) else None
    return build_scenario_preset(
        {
            "id": sid,
            "label": primitive_string(row.get("label"), _or(payload.get("label"), "Scenario")),
            "notes": primitive_string(row.get("notes"), _or(payload.get("notes"), "")),
            "snapshotStart": primitive_number(payload.get("snapshotStart"), 0),
            "snapshotEnd": primitive_number(payload.get("snapshotEnd"), 24),
            "snapshotWeight": primitive_number(payload.get("snapshotWeight"), 1),
            "carbonPrice": primitive_number(payload.get("carbonPrice"), 0),
            "carbonPriceSchedule": payload["carbonPriceSchedule"] if isinstance(payload.get("carbonPriceSchedule"), list) else [],
            "discountRate": primitive_number(payload.get("discountRate"), 0),
            "forceLp": primitive_boolean(payload.get("forceLp"), False),
            "enableLoadShedding": primitive_boolean(payload.get("enableLoadShedding"), False),
            "loadSheddingCost": primitive_number(payload.get("loadSheddingCost"), 1000),
            **{key: payload.get(key) for key in CONFIG_BLOCKS},
            "ownerColumn": owner_column,
            "constraints": payload["constraints"] if isinstance(payload.get("constraints"), list) else [],
            "modelOverrides": payload["modelOverrides"] if isinstance(payload.get("modelOverrides"), list) else [],
        }
    )


def read_scenario_catalog(model: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    """Port of ``readScenarioCatalogFromModel``.

    Returns ``{activeScenarioId, scenarios, unreadable}``. ``unreadable`` lists
    ``{id, reason}`` for rows the browser silently drops (bad JSON, missing
    ``pathwayConfig.periods``, blank id) so a caller can explain a missing scenario.
    """
    rows = model.get(SCENARIO_SHEET) or []
    scenarios: list[dict[str, Any]] = []
    unreadable: list[dict[str, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        sid = primitive_string(row.get("id")).strip()
        if not sid:
            unreadable.append({"id": str(row.get("id")), "reason": "row has no string id"})
            continue
        try:
            scenarios.append(_scenario_from_row(row))
        except Exception as exc:  # noqa: BLE001 — mirrors the browser's catch -> null
            unreadable.append({"id": sid, "reason": f"{type(exc).__name__}: {exc}"})
    active_id = None
    for row in rows:
        if isinstance(row, dict) and primitive_boolean(row.get("active"), False):
            active_id = row.get("id")
            break
    normalized = _normalize_catalog({"activeScenarioId": active_id, "scenarios": scenarios})
    normalized["unreadable"] = unreadable
    return normalized


# ── carbon library (carbonLibrary.ts) ────────────────────────────────────────


def clean_carbon_schedule(schedule: Any) -> list[dict[str, Any]]:
    """Port of ``cloneSchedule`` in carbonLibrary.ts: numeric entries only, year-sorted."""
    rows: list[dict[str, Any]] = []
    for row in schedule or []:
        if not isinstance(row, dict):
            continue
        year = _js_number(row.get("year", _MISSING))
        price = _js_number(row.get("price", _MISSING))
        if _is_finite(year) and _is_finite(price):
            rows.append({"year": _num_out(year), "price": _num_out(price)})
    rows.sort(key=lambda r: r["year"])
    return rows


def read_carbon_library(model: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Port of ``readCarbonLibraryFromModel``."""
    out: list[dict[str, Any]] = []
    for row in model.get(CARBON_LIBRARY_SHEET) or []:
        if not isinstance(row, dict):
            continue
        pid = primitive_string(row.get("id")).strip()
        if not pid:
            continue
        schedule: list[dict[str, Any]] = []
        raw = row.get("json")
        try:
            parsed = json.loads(raw) if isinstance(raw, str) and raw.strip() else []
            if isinstance(parsed, list):
                schedule = clean_carbon_schedule(parsed)
        except ValueError:
            pass
        out.append({"id": pid, "name": primitive_string(row.get("name")).strip() or "Carbon schedule", "schedule": schedule})
    return out


# ── custom DSL (custom.ts / dsl.ts) ──────────────────────────────────────────

#: Metrics that bind to a generator carrier (``METRIC_DEFS[m].needsCarrier`` in constants/index.ts).
CARRIER_METRICS = frozenset(
    {
        "carrier_max_gen", "carrier_min_gen", "carrier_max_share", "carrier_min_share",
        "carrier_max_cf", "carrier_min_cf", "carrier_max_cap", "carrier_min_cap",
        "carrier_max_cap_share", "carrier_min_cap_share",
    }
)


#: Keys of a preset's ``json`` cell, in the order ``writeScenarioCatalogToModel`` writes them.
_SCENARIO_JSON_SCALARS = (
    "snapshotStart", "snapshotEnd", "snapshotWeight", "carbonPrice", "carbonPriceSchedule",
    "discountRate", "forceLp", "enableLoadShedding", "loadSheddingCost",
)
#: Fields a caller may set on a preset (``id`` comes from the URL / tool argument).
SCENARIO_FIELDS = frozenset(
    ("label", "notes", *_SCENARIO_JSON_SCALARS, *CONFIG_BLOCKS, "ownerColumn", "constraints", "modelOverrides")
)


def write_scenario_catalog(
    model: dict[str, list[dict[str, Any]]], catalog: dict[str, Any]
) -> list[dict[str, Any]]:
    """Port of ``writeScenarioCatalogToModel``: the ``RAGNAROK_Scenarios`` rows for ``catalog``."""
    normalized = _normalize_catalog(
        {"activeScenarioId": catalog.get("activeScenarioId"), "scenarios": list(catalog.get("scenarios") or [])}
    )
    rows: list[dict[str, Any]] = []
    for sc in normalized["scenarios"]:
        payload: dict[str, Any] = {key: sc.get(key) for key in _SCENARIO_JSON_SCALARS}
        payload.update({key: sc.get(key) for key in CONFIG_BLOCKS})
        payload["ownerColumn"] = sc.get("ownerColumn")
        payload["constraints"] = sc.get("constraints")
        payload["modelOverrides"] = sc.get("modelOverrides")
        rows.append({
            "id": sc["id"],
            "label": sc["label"],
            "active": sc["id"] == normalized["activeScenarioId"],
            "notes": sc["notes"],
            "json": json.dumps(payload),
        })
    return rows


def upsert_scenario(
    model: dict[str, list[dict[str, Any]]],
    scenario_id: str,
    fields: dict[str, Any],
    *,
    activate: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Create or update one preset; returns ``(sheet rows, saved preset)``.

    ``fields`` merge over the existing preset (a config block replaces the stored
    block whole). A new preset starts from the defaults. Unknown fields and a blank
    id raise ``ScenarioResolveError`` so a typo never saves silently.
    """
    sid = str(scenario_id or "").strip()
    if not sid:
        raise ScenarioResolveError("scenario id must not be blank")
    unknown = sorted(set(fields) - SCENARIO_FIELDS)
    if unknown:
        raise ScenarioResolveError(
            f"unknown scenario field(s): {', '.join(unknown)}; allowed: {', '.join(sorted(SCENARIO_FIELDS))}"
        )
    catalog = read_scenario_catalog(model)
    scenarios = list(catalog["scenarios"])
    idx = next((i for i, sc in enumerate(scenarios) if sc["id"] == sid), None)
    base = dict(scenarios[idx]) if idx is not None else {"id": sid}
    base.update(fields)
    base["id"] = sid
    preset = build_scenario_preset(base)
    if idx is None:
        scenarios.append(preset)
    else:
        scenarios[idx] = preset
    active = sid if activate or not catalog["scenarios"] else catalog["activeScenarioId"]
    rows = write_scenario_catalog(model, {"activeScenarioId": active, "scenarios": scenarios})
    return rows, preset


def remove_scenario(model: dict[str, list[dict[str, Any]]], scenario_id: str) -> list[dict[str, Any]]:
    """Rows of ``RAGNAROK_Scenarios`` without ``scenario_id`` (``ScenarioResolveError`` if unknown)."""
    catalog = read_scenario_catalog(model)
    kept = [sc for sc in catalog["scenarios"] if sc["id"] != scenario_id]
    if len(kept) == len(catalog["scenarios"]):
        raise ScenarioResolveError(f'unknown scenario "{scenario_id}"')
    active = catalog["activeScenarioId"]
    if active == scenario_id:
        active = kept[0]["id"] if kept else None
    return write_scenario_catalog(model, {"activeScenarioId": active, "scenarios": kept})


def activate_scenario(model: dict[str, list[dict[str, Any]]], scenario_id: str) -> list[dict[str, Any]]:
    """Rows of ``RAGNAROK_Scenarios`` with ``scenario_id`` marked active."""
    catalog = read_scenario_catalog(model)
    if not any(sc["id"] == scenario_id for sc in catalog["scenarios"]):
        raise ScenarioResolveError(f'unknown scenario "{scenario_id}"')
    return write_scenario_catalog(model, {"activeScenarioId": scenario_id, "scenarios": catalog["scenarios"]})


def read_custom_dsl(model: dict[str, list[dict[str, Any]]]) -> str:
    """Port of ``readCustomDslFromModel``: the ``text`` of the sheet's first row."""
    rows = model.get(CUSTOM_DSL_SHEET) or []
    row = rows[0] if rows else None
    text = row.get("text") if isinstance(row, dict) else None
    return text if isinstance(text, str) else ""


def generator_carriers(model: dict[str, list[dict[str, Any]]]) -> list[str]:
    """Port of ``generatorCarriers``: distinct trimmed carriers, ``localeCompare`` order (lower case before upper on ties)."""
    seen = {str(r.get("carrier") if r.get("carrier") is not None else "").strip() for r in model.get("generators") or [] if isinstance(r, dict)}
    seen.discard("")
    return sorted(seen, key=lambda s: (s.casefold(), s.swapcase()))


def unresolved_carrier_constraints(constraints: list[dict[str, Any]], gen_carriers: list[str]) -> list[dict[str, Any]]:
    """Port of ``unresolvedCarrierConstraints``: enabled carrier constraints matching no generator."""
    valid = set(gen_carriers)
    return [
        c for c in constraints
        if _truthy(c.get("enabled")) and c.get("metric") in CARRIER_METRICS and c.get("carrier") not in valid
    ]


def parse_constraint_dsl(text: str) -> list[dict[str, Any]]:
    """Port of ``parseConstraintDsl``: per-line ``{lineNo, raw, spec | error}``.

    Uses the solver's own parser (``backend.pypsa.network.constraint_dsl``), so the
    text the browser would accept is exactly the text the solver accepts.
    """
    from backend.app.constraints.constraint_dsl import DslParseError, parse_line

    out: list[dict[str, Any]] = []
    for idx, raw_line in enumerate(re.split(r"\r?\n", text or ""), start=1):
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        try:
            parsed = parse_line(line, idx)
        except DslParseError as exc:
            out.append({"lineNo": idx, "raw": line, "error": exc.message})
            continue

        def term(t: Any) -> dict[str, Any]:
            d: dict[str, Any] = {"coef": _num_out(float(t.coef)), "kind": t.kind}
            if t.carrier is not None:
                d["carrier"] = t.carrier
            if t.column is not None:
                d["column"] = t.column
            if t.values is not None:
                d["values"] = list(t.values)
            return d

        out.append(
            {
                "lineNo": idx,
                "raw": line,
                "spec": {"id": line, "lhs": [term(t) for t in parsed.lhs], "sense": parsed.sense, "rhs": [term(t) for t in parsed.rhs]},
            }
        )
    return out


def dsl_to_specs(text: str) -> list[dict[str, Any]]:
    """Port of ``dslToSpecs``: only the lines that parse."""
    return [r["spec"] for r in parse_constraint_dsl(text) if "spec" in r]


# ── preset -> run body (buildRunPayload.ts) ──────────────────────────────────


def build_run_payload(
    preset: dict[str, Any], ui_opts: dict[str, Any], constraint_specs: list[dict[str, Any]]
) -> dict[str, Any]:
    """Port of ``buildRunPayload``: ``{scenario, options}`` for ``POST /api/queue``."""
    scenario = {
        "constraints": [c for c in preset["constraints"] if _truthy(c.get("enabled"))],
        "constraintSpecs": constraint_specs,
        "carbonPrice": preset["carbonPrice"],
        "discountRate": preset["discountRate"],
    }
    options: dict[str, Any] = {
        "backend": _or(ui_opts.get("backend"), "pypsa"),
        "snapshotCount": preset["snapshotEnd"] - preset["snapshotStart"],
        "snapshotStart": preset["snapshotStart"],
        "snapshotEnd": preset["snapshotEnd"],
        "snapshotWeight": preset["snapshotWeight"],
        "forceLp": preset["forceLp"],
        "scenarioLabel": ui_opts.get("scenarioLabel"),
        "filename": ui_opts["filename"],
        "dateFormat": ui_opts["dateFormat"],
        "solverThreads": ui_opts["solverThreads"],
        "solverType": ui_opts["solverType"],
        "solveAcceptance": ui_opts["solveAcceptance"],
        "objectiveAutoScale": ui_opts["objectiveAutoScale"],
        "currencySymbol": ui_opts["currencySymbol"],
        "enableLoadShedding": preset["enableLoadShedding"],
        "loadSheddingCost": preset["loadSheddingCost"],
        "pathwayConfig": {**preset["pathwayConfig"], "selectedPeriod": get_default_selected_period(preset["pathwayConfig"])},
        "rollingConfig": normalize_rolling_config(preset["rollingConfig"]),
        "samplingConfig": normalize_sampling_config(preset["samplingConfig"]),
    }
    for key in (
        "stochasticConfig", "securityConstrainedConfig", "reserveConfig", "outageMcConfig",
        "correlatedSamplingConfig", "rampConfig", "elccConfig", "convergenceConfig",
        "lmpDecompositionConfig", "powerFlowConfig", "marketSimConfig", "contingencyConfig",
        "mgaConfig", "merchantConfig", "bidStrategyConfig", "assetSwapConfig", "essConfig",
        "ppaConfig", "demandResponseConfig", "ownerColumn", "financeConfig", "carbonPriceSchedule",
    ):
        options[key] = preset[key]
    if preset.get("modelOverrides"):
        options["modelOverrides"] = preset["modelOverrides"]
    return {"scenario": scenario, "options": options}


class ScenarioResolveError(ValueError):
    """A scenario cannot be turned into a run body; the message says why and what to do."""


def summarize_preset(preset: dict[str, Any]) -> dict[str, Any]:
    """A short row for ``list_scenarios``: what differs from a plain run, in one glance."""
    enabled_blocks = sorted(
        key for key in CONFIG_BLOCKS
        if key not in ("financeConfig",) and isinstance(preset.get(key), dict) and preset[key].get("enabled")
    )
    return {
        "id": preset["id"],
        "label": preset["label"],
        "notes": preset.get("notes", ""),
        "snapshotStart": preset["snapshotStart"],
        "snapshotEnd": preset["snapshotEnd"],
        "snapshotWeight": preset["snapshotWeight"],
        "carbonPrice": preset["carbonPrice"],
        "carbonPriceScheduleYears": [r.get("year") for r in preset.get("carbonPriceSchedule") or []],
        "discountRate": preset["discountRate"],
        "forceLp": preset["forceLp"],
        "enableLoadShedding": preset["enableLoadShedding"],
        "enabledModes": enabled_blocks,
        "constraintsEnabled": sum(1 for c in preset["constraints"] if _truthy(c.get("enabled"))),
        "modelOverrides": len(preset.get("modelOverrides") or []),
    }


def resolve_scenario_run(
    model: dict[str, list[dict[str, Any]]],
    scenario_id: str,
    *,
    ui_options: dict[str, Any] | None = None,
    carbon_schedule_id: str | None = None,
    options_patch: dict[str, Any] | None = None,
    run_label: str | None = None,
) -> dict[str, Any]:
    """Turn a saved scenario into the ``{scenario, options}`` body ``/api/queue`` takes.

    Equivalent to the browser's batch runner: the preset comes from
    ``RAGNAROK_Scenarios``, the constraint specs from the model-level
    ``RAGNAROK_CustomDSL`` sheet (shared by every scenario), the solver knobs from
    ``ui_options`` over :data:`UI_RUN_DEFAULTS`.

    Args:
        model: The session's full model (only the ``RAGNAROK_*`` and ``generators`` sheets are read).
        scenario_id: ``id`` of the preset (see ``read_scenario_catalog``).
        ui_options: Overrides for the non-preset knobs (``filename``, ``solverType`` …).
        carbon_schedule_id: Replace the preset's carbon schedule with this library profile.
        options_patch: Top-level ``options`` keys to replace after the preset is built
            (validated by the caller against the run-options reference).
        run_label: Sets ``options.runLabel`` (distinct History names for a batch).

    Raises:
        ScenarioResolveError: unknown scenario/profile, or a DSL line that does not parse.
    """
    catalog = read_scenario_catalog(model)
    preset = next((s for s in catalog["scenarios"] if s["id"] == scenario_id), None)
    if preset is None:
        known = ", ".join(f'"{s["id"]}" ({s["label"]})' for s in catalog["scenarios"]) or "none saved"
        raise ScenarioResolveError(f'unknown scenario "{scenario_id}"; saved scenarios: {known}')
    if carbon_schedule_id:
        library = read_carbon_library(model)
        profile = next((p for p in library if p["id"] == carbon_schedule_id), None)
        if profile is None:
            known = ", ".join(f'"{p["id"]}" ({p["name"]})' for p in library) or "none saved"
            raise ScenarioResolveError(f'unknown carbon schedule "{carbon_schedule_id}"; library: {known}')
        preset = {**preset, "carbonPriceSchedule": clone_schedule(profile["schedule"])}
    lines = parse_constraint_dsl(read_custom_dsl(model))
    errors = [line for line in lines if "error" in line]
    if errors:
        shown = "; ".join(f"line {e['lineNo']}: {e['error']}" for e in errors[:5])
        raise ScenarioResolveError(
            f"{len(errors)} custom-constraint line(s) in the model's RAGNAROK_CustomDSL sheet do not parse, "
            f"so the run was not built ({shown}). Fix the sheet with edit_sheet."
        )
    specs = [line["spec"] for line in lines]
    ui = {**UI_RUN_DEFAULTS, **{k: v for k, v in (ui_options or {}).items() if v is not None}}
    ui["scenarioLabel"] = preset["label"]
    body = build_run_payload(preset, ui, specs)
    if options_patch:
        body["options"].update(options_patch)
    if run_label:
        body["options"]["runLabel"] = run_label
    body["scenarioId"] = preset["id"]
    body["scenarioLabel"] = preset["label"]
    return body
