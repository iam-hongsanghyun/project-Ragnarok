"""Run settings as one readable table: the ``RAGNAROK_RunSettings`` sheet, ``/api/session/run-settings`` and the MCP
``get_run_settings`` / ``set_run_settings`` tools all speak it.

The values themselves live in the project's app state (:mod:`backend.app.app_state`): the Settings object
(``project_ragnarok_settings``) and the live run controls (``ragnarok:session:controls``), the same strings the
browser keeps. This module only maps between those and a ``setting -> value`` table a person can fill in a
workbook (the project template) or an agent can set, so a file opens and runs with exactly the settings it states.

A ``RAGNAROK_RunSettings`` sheet in a model sent to the server is applied on top of the project's app state and
taken out of the model (:func:`split_from_model`); an exported workbook writes the sheet back from the app state,
so an edited workbook round-trips.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException

SHEET = "RAGNAROK_RunSettings"
SETTINGS_KEY = "project_ragnarok_settings"
CONTROLS_KEY = "ragnarok:session:controls"


@dataclass(frozen=True)
class Spec:
    key: str
    kind: str  # "number" | "bool" | "text" | "choice" | "snapshot"
    unit: str
    default: Any
    description: str
    choices: tuple[str, ...] = ()


SPECS: tuple[Spec, ...] = (
    Spec("windowStart", "snapshot", "snapshot label", None,
         "First snapshot the run solves (a label from the snapshots sheet). Blank = the first snapshot."),
    Spec("windowEnd", "snapshot", "snapshot label", None,
         "Last snapshot the run solves, inclusive. Blank = the last snapshot."),
    Spec("carbonPrice", "number", "currency/tCO2", 0.0, "Carbon price added to emitting generators' cost."),
    Spec("discountRate", "number", "fraction", 0.05, "Discount rate used to annualise overnight cost."),
    Spec("loadShedding", "bool", "true/false", True, "Allow unserved load at the load-shedding cost."),
    Spec("loadSheddingCost", "number", "currency/MWh", 10000.0, "Value of lost load."),
    Spec("forceLp", "bool", "true/false", False, "Solve unit-commitment models as an LP relaxation."),
    Spec("dryRun", "bool", "true/false", False, "Build and check the model without solving."),
    Spec("rolling", "bool", "true/false", False,
         "Rolling horizon: solve window by window. Period limits are carried over between windows "
         "(RAGNAROK_PeriodBudgets, CO2 caps, e_sum)."),
    Spec("rollingWindowHours", "number", "h", 168.0, "Length of one rolling window."),
    Spec("rollingOverlapHours", "number", "h", 24.0, "Hours each window overlaps the next (re-solved by the next)."),
    Spec("rollingTerminalSoc", "bool", "true/false", False, "Ask the last window to end with the starting storage level."),
    Spec("solverType", "choice", "", "auto", "HiGHS method.", ("auto", "simplex", "ipm", "pdlp", "hipo")),
    Spec("solverThreads", "number", "threads", 0, "Solver threads; 0 = let HiGHS decide."),
    Spec("solveAcceptance", "choice", "", "lenient", "Accept any valid solve, or only proven-optimal ones.",
         ("lenient", "strict")),
    Spec("objectiveAutoScale", "bool", "true/false", False, "Let HiGHS auto-scale a wide-ranging objective."),
    Spec("currencyCode", "text", "ISO 4217", "USD", "Currency of every cost in the model."),
    Spec("currencySymbol", "text", "", "$", "Symbol shown with costs."),
    Spec("enabledModules", "text", "comma list", None,
         "Module tabs shown (e.g. Data,Forge,Screening). Blank = every module."),
    Spec("dateFormat", "choice", "", "auto", "How dates in imported sheets are read.", ("auto", "dmy", "mdy", "ymd")),
)
BY_KEY = {s.key: s for s in SPECS}

# Settings-object fields (the rest are run controls).
_SETTINGS_FIELDS = {
    "discountRate": "discountRate", "loadShedding": "enableLoadShedding", "loadSheddingCost": "loadSheddingCost",
    "solverType": "solverType", "solverThreads": "solverThreads", "solveAcceptance": "solveAcceptance",
    "objectiveAutoScale": "objectiveAutoScale", "currencyCode": "currencyCode", "currencySymbol": "currencySymbol",
    "enabledModules": "enabledModules", "dateFormat": "dateFormat",
}
# Fields the live scenario in the controls also carries (it is applied first on load, so it must agree).
_SCENARIO_FIELDS = {
    "discountRate": "discountRate", "loadShedding": "enableLoadShedding", "loadSheddingCost": "loadSheddingCost",
    "carbonPrice": "carbonPrice", "forceLp": "forceLp",
}


def _json(state: dict[str, str], key: str) -> dict[str, Any]:
    try:
        value = json.loads(state.get(key) or "{}")
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _blank(v: Any) -> bool:
    return v is None or (isinstance(v, str) and not v.strip()) or (isinstance(v, float) and math.isnan(v))


def coerce(key: str, value: Any) -> Any:
    """``value`` as the setting's type. Raises ``HTTPException(400)`` naming the valid input."""
    spec = BY_KEY.get(key)
    if spec is None:
        raise HTTPException(status_code=400, detail=f"Unknown run setting {key!r}. Known: {', '.join(BY_KEY)}.")
    if _blank(value):
        return None
    if spec.kind == "bool":
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in ("true", "1", "yes", "y", "on", "1.0"):
            return True
        if text in ("false", "0", "no", "n", "off", "0.0"):
            return False
        raise HTTPException(status_code=400, detail=f"Run setting {key}: {value!r} is not true/false.")
    if spec.kind == "number":
        try:
            x = float(value)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail=f"Run setting {key}: {value!r} is not a number ({spec.unit}).") from None
        if not math.isfinite(x) or x < 0:
            raise HTTPException(status_code=400, detail=f"Run setting {key}: must be a finite number >= 0 ({spec.unit}).")
        return int(x) if key == "solverThreads" else x
    if spec.kind == "choice":
        text = str(value).strip().lower()
        if text not in spec.choices:
            raise HTTPException(status_code=400, detail=f"Run setting {key}: {value!r} is not one of {', '.join(spec.choices)}.")
        return text
    return str(value).strip()


def _label_index(labels: list[str], value: str, key: str) -> int:
    import pandas as pd

    from backend.pypsa.network.snapshots import parse_snapshot_labels

    if value in labels:
        return labels.index(value)
    try:
        target = parse_snapshot_labels([value])[0]
        parsed = parse_snapshot_labels(labels)
        hits = [i for i, t in enumerate(parsed) if pd.Timestamp(t) == pd.Timestamp(target)]
        if hits:
            return hits[0]
    except (ValueError, TypeError):
        pass
    raise HTTPException(status_code=400, detail=f"Run setting {key}: {value!r} is not a snapshot of this model "
                        f"(first {labels[0] if labels else '-'}, last {labels[-1] if labels else '-'}).")


def read(state: dict[str, str] | None, labels: list[str] | None = None) -> dict[str, Any]:
    """The current value of every setting (``None`` = not set: the app default applies)."""
    state = state or {}
    settings, controls = _json(state, SETTINGS_KEY), _json(state, CONTROLS_KEY)
    rolling = controls.get("rollingConfig") if isinstance(controls.get("rollingConfig"), dict) else {}
    labels = labels or []
    out: dict[str, Any] = {}
    for spec in SPECS:
        k = spec.key
        if k in _SETTINGS_FIELDS:
            out[k] = settings.get(_SETTINGS_FIELDS[k])
        elif k == "windowStart":
            i = controls.get("snapshotStart")
            out[k] = labels[i] if isinstance(i, int) and 0 <= i < len(labels) else None
        elif k == "windowEnd":
            i = controls.get("snapshotEnd")
            out[k] = labels[i - 1] if isinstance(i, int) and 0 < i <= len(labels) else None
        elif k == "rolling":
            out[k] = rolling.get("enabled")
        elif k == "rollingWindowHours":
            out[k] = rolling.get("horizonHours")
        elif k == "rollingOverlapHours":
            out[k] = rolling.get("overlapHours")
        elif k == "rollingTerminalSoc":
            out[k] = rolling.get("terminalSoc")
        else:
            out[k] = controls.get(k)
    return out


def apply(
    state: dict[str, str] | None,
    values: dict[str, Any],
    *,
    labels: list[str] | None = None,
    step_hours: float = 1.0,
    filename: str | None = None,
) -> dict[str, str]:
    """``state`` with ``values`` written into it (a ``None`` value leaves that setting as it is). Validates first."""
    clean = {k: coerce(k, v) for k, v in values.items()}
    out = dict(state or {})
    settings, controls = _json(out, SETTINGS_KEY), _json(out, CONTROLS_KEY)
    scenario = controls.get("scenario") if isinstance(controls.get("scenario"), dict) else None
    rolling = dict(controls.get("rollingConfig") or {}) if isinstance(controls.get("rollingConfig"), dict) else {}
    labels = labels or []
    touched_settings = touched_controls = False
    for k, v in clean.items():
        if v is None:
            continue
        if k in _SETTINGS_FIELDS:
            settings[_SETTINGS_FIELDS[k]] = v
            touched_settings = True
        elif k in ("windowStart", "windowEnd"):
            if not labels:
                raise HTTPException(status_code=400, detail=f"Run setting {k}: the model has no snapshots yet.")
            i = _label_index(labels, str(v), k)
            controls["snapshotStart" if k == "windowStart" else "snapshotEnd"] = i if k == "windowStart" else i + 1
            if scenario is not None:
                scenario["snapshotStart" if k == "windowStart" else "snapshotEnd"] = i if k == "windowStart" else i + 1
            touched_controls = True
        elif k.startswith("rolling"):
            field = {"rolling": "enabled", "rollingWindowHours": "horizonHours", "rollingOverlapHours": "overlapHours",
                     "rollingTerminalSoc": "terminalSoc"}[k]
            rolling[field] = v
            touched_controls = True
        else:
            controls[k] = v
            touched_controls = True
        if scenario is not None and k in _SCENARIO_FIELDS:
            scenario[_SCENARIO_FIELDS[k]] = v
    if rolling:
        step = step_hours if step_hours > 0 else 1.0
        horizon_h = float(rolling.get("horizonHours") or rolling.get("horizonSnapshots", 168) * step)
        overlap_h = float(rolling.get("overlapHours") if rolling.get("overlapHours") is not None else rolling.get("overlapSnapshots", 24) * step)
        if overlap_h >= horizon_h:
            raise HTTPException(status_code=400, detail="Run setting rollingOverlapHours must be shorter than rollingWindowHours.")
        rolling.setdefault("enabled", False)
        rolling["horizonHours"], rolling["overlapHours"] = horizon_h, overlap_h
        rolling["horizonSnapshots"] = max(1, math.ceil(horizon_h / step))
        rolling["overlapSnapshots"] = min(rolling["horizonSnapshots"] - 1, math.ceil(overlap_h / step))
        rolling["stepSnapshots"] = rolling["horizonSnapshots"] - rolling["overlapSnapshots"]
        controls["rollingConfig"] = rolling
        if scenario is not None:
            scenario["rollingConfig"] = dict(rolling)
    if touched_controls or rolling:
        if filename:
            controls["filename"] = filename  # the run window belongs to THIS model (the boot restore checks it)
        controls.setdefault("carbonPrice", 0.0)
        controls.setdefault("carbonPriceSchedule", [])
        controls.setdefault("snapshotStart", 0)
        controls.setdefault("snapshotEnd", len(labels))
        controls.setdefault("snapshotWeight", 1)
        controls.setdefault("forceLp", False)
        controls["savedAt"] = int(controls.get("savedAt") or 0) + 1
        if scenario is not None:
            controls["scenario"] = scenario
        out[CONTROLS_KEY] = json.dumps(controls)
    if touched_settings:
        out[SETTINGS_KEY] = json.dumps(settings)
    return out


def table(state: dict[str, str] | None, labels: list[str] | None = None) -> list[dict[str, Any]]:
    """Every setting with its current value, unit, default, choices and meaning (the API / MCP shape)."""
    current = read(state, labels)
    return [
        {"setting": s.key, "value": current.get(s.key), "unit": s.unit, "default": s.default,
         "choices": list(s.choices), "description": s.description}
        for s in SPECS
    ]


def sheet_rows(state: dict[str, str] | None, labels: list[str] | None = None) -> list[dict[str, Any]]:
    """The ``RAGNAROK_RunSettings`` sheet: a row per setting, the value blank where the app default applies."""
    return [
        {"setting": r["setting"], "value": "" if r["value"] is None else r["value"], "unit": r["unit"],
         "description": r["description"] + (f" Choices: {', '.join(r['choices'])}." if r["choices"] else "")}
        for r in table(state, labels)
    ]


def from_rows(rows: list[Any]) -> dict[str, Any]:
    """The sheet's ``setting -> value`` pairs (unit / description columns are ignored)."""
    out: dict[str, Any] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        key = str(row.get("setting") or "").strip()
        if key:
            out[key] = row.get("value")
    return out


def split_from_model(model: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """``(model without the sheet, its values or None)``."""
    if SHEET not in model:
        return model, None
    rest = {k: v for k, v in model.items() if k != SHEET}
    rows = model.get(SHEET)
    return rest, from_rows(rows if isinstance(rows, list) else [])


def snapshot_labels(model: dict[str, Any]) -> list[str]:
    rows = model.get("snapshots") if isinstance(model.get("snapshots"), list) else []
    return [str(r.get("snapshot") or r.get("name") or r.get("datetime") or "") for r in rows if isinstance(r, dict)]


def step_hours_of(model: dict[str, Any]) -> float:
    """Hours one snapshot stands for: the ``generators`` (else ``objective``) weighting of the first snapshot, else the
    spacing of the first two labels, else 1."""
    rows = model.get("snapshots") if isinstance(model.get("snapshots"), list) else []
    if rows and isinstance(rows[0], dict):
        for col in ("generators", "objective"):
            try:
                v = float(rows[0].get(col))
                if math.isfinite(v) and v > 0:
                    return v
            except (TypeError, ValueError):
                pass
    labels = snapshot_labels(model)
    if len(labels) >= 2:
        try:
            import pandas as pd

            from backend.pypsa.network.snapshots import parse_snapshot_labels

            t = parse_snapshot_labels(labels[:2])
            hours = (pd.Timestamp(t[1]) - pd.Timestamp(t[0])).total_seconds() / 3600.0
            if hours > 0:
                return hours
        except (ValueError, TypeError):
            pass
    return 1.0


# Run-option keys the live scenario carries under the same name (frontend buildRunPayload).
_SCENARIO_OPTION_KEYS = (
    "snapshotStart", "snapshotEnd", "forceLp", "enableLoadShedding", "loadSheddingCost", "pathwayConfig", "rollingConfig",
    "samplingConfig", "stochasticConfig", "securityConstrainedConfig", "reserveConfig", "outageMcConfig",
    "correlatedSamplingConfig", "rampConfig", "elccConfig", "convergenceConfig", "lmpDecompositionConfig",
    "powerFlowConfig", "marketSimConfig", "contingencyConfig", "mgaConfig", "merchantConfig", "bidStrategyConfig",
    "assetSwapConfig", "essConfig", "ppaConfig", "demandResponseConfig", "ownerColumn", "financeConfig",
    "carbonPriceSchedule",
)
_SETTINGS_OPTION_KEYS = ("solverType", "solverThreads", "solveAcceptance", "objectiveAutoScale", "currencySymbol",
                         "dateFormat", "advancedSolve")


def payload_defaults(state: dict[str, str] | None) -> tuple[dict[str, Any], dict[str, Any]]:
    """``(scenario, options)`` of a run from the project's own settings: what the GUI would send if Run were pressed.

    A run submitted without them (an agent's ``submit_solve``, a script) is completed from these, key by key, so a
    project runs with the settings it carries; anything the submitter states wins.
    """
    state = state or {}
    settings, controls = _json(state, SETTINGS_KEY), _json(state, CONTROLS_KEY)
    live = controls.get("scenario") if isinstance(controls.get("scenario"), dict) else {}
    options: dict[str, Any] = {k: live[k] for k in _SCENARIO_OPTION_KEYS if k in live}
    for k in ("snapshotStart", "snapshotEnd", "forceLp", "rollingConfig", "samplingConfig", "pathwayConfig",
              "carbonPriceSchedule", "dryRun"):
        if k in controls:
            options[k] = controls[k]
    if "enableLoadShedding" in settings:
        options["enableLoadShedding"] = settings["enableLoadShedding"]
    if "loadSheddingCost" in settings:
        options["loadSheddingCost"] = settings["loadSheddingCost"]
    options.update({k: settings[k] for k in _SETTINGS_OPTION_KEYS if k in settings})
    if isinstance(options.get("snapshotStart"), int) and isinstance(options.get("snapshotEnd"), int):
        options["snapshotCount"] = options["snapshotEnd"] - options["snapshotStart"]
    scenario: dict[str, Any] = {}
    if "carbonPrice" in controls or "carbonPrice" in live:
        scenario["carbonPrice"] = controls.get("carbonPrice", live.get("carbonPrice"))
    if "discountRate" in settings or "discountRate" in live:
        scenario["discountRate"] = settings.get("discountRate", live.get("discountRate"))
    constraints = controls.get("constraints", live.get("constraints"))
    if isinstance(constraints, list):
        scenario["constraints"] = [c for c in constraints if isinstance(c, dict) and c.get("enabled", True)]
    return scenario, options
