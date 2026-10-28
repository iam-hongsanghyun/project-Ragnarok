"""Cost-basis schema version and the one-off workbook migration (schema 1 -> 2).

Ragnarok's core is a shell around PyPSA: a workbook's cost columns mean exactly what
PyPSA says they mean (``pypsa.costs.periodized_cost``):

* ``capital_cost``   - periodised cost per MW (MWh, MVA) for the MODELLED HORIZON, as is;
* ``overnight_cost`` - annuitised by PyPSA: ``overnight x annuity(discount_rate, lifetime) x nyears``;
* ``fom_cost``       - added per horizon, unscaled.

Before schema 2 a workbook ``capital_cost`` was an OVERNIGHT price that the builder
annuitised (and, single-period, pro-rated by ``hours / 8760``) at run time. Such a workbook
means something else under PyPSA's semantics, so it is migrated ONCE, visibly, when it is
loaded: the number moves to the column PyPSA annuitises. The solve is unchanged because the
old window factor equals PyPSA's ``n.nyears``.

Algorithm:
    Old objective term (per extendable asset, capacity :math:`P`):

    $$ c^{old} = K \\cdot a(r, L) \\cdot \\frac{\\sum_t w_t}{8760} \\cdot P $$

    New (PyPSA, ``overnight_cost`` :math:`=K`, ``capital_cost`` :math:`=0`):

    $$ c^{new} = K \\cdot a(r, L) \\cdot n_{years} \\cdot P, \\qquad n_{years} = \\frac{\\sum_t w_t}{8760} $$

    ASCII: old = K * a(r, L) * (sum_t w_t / 8760) * P ; new = K * a(r, L) * nyears * P.
    :math:`K`: overnight price (currency/MW); :math:`a`: annuity factor (1/year);
    :math:`r`: discount rate (1/year); :math:`L`: lifetime (years); :math:`w_t`: objective
    snapshot weight (h); :math:`P`: capacity (MW).

The version lives in the model sheet ``RAGNAROK_Schema`` (one row, ``ragnarok_schema_version``),
so it travels with the session store, a project xlsx / zip and a transform's output.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from ...app.config import load_system_defaults

SCHEMA_SHEET = "RAGNAROK_Schema"
SCHEMA_KEY = "ragnarok_schema_version"
#: 1 = implicit legacy (Ragnarok annuitised ``capital_cost`` at run time); 2 = PyPSA cost semantics.
CURRENT_SCHEMA_VERSION = 3
#: 2 = PyPSA cost semantics (step 1); 3 adds the carbon-pricing module (no carbon adder in marginal_cost) and the
#: annual-budgets module (``e_sum_*`` / GlobalConstraint ``constant`` are PyPSA horizon totals, never scaled).
COST_SCHEMA_VERSION = 2
LEGACY_SCHEMA_VERSION = 1

#: sheet -> its extendable flag. Only these were annuitised by the old builder.
#: ``transformers`` were never converted (their ``capital_cost`` already went to PyPSA 1:1), so
#: they are left alone.
_COMPONENTS: dict[str, str] = {
    "generators": "p_nom_extendable",
    "storage_units": "p_nom_extendable",
    "stores": "e_nom_extendable",
    "lines": "s_nom_extendable",
    "links": "p_nom_extendable",
    "processes": "p_nom_extendable",
}

_TRUE = frozenset({"true", "1", "yes", "y", "t", "on"})
#: ``lifetime`` at or above this is a "no limit" placeholder (the builder snaps 1e9+ to inf).
_INF_LIFETIME = 1e9


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value) and not (isinstance(value, float) and math.isnan(value))
    return str(value).strip().lower() in _TRUE


def _number(value: Any) -> float | None:
    """Finite-or-inf float of a cell; ``None`` for blank / NaN / junk."""
    if value is None or isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(out) else out


def schema_version(model: dict[str, Any]) -> int | None:
    """The stamped schema version of ``model``, ``None`` when it carries none (a legacy workbook)."""
    rows = model.get(SCHEMA_SHEET)
    if not isinstance(rows, list):
        return None
    for row in rows:
        if isinstance(row, dict):
            value = _number(row.get(SCHEMA_KEY))
            if value is not None:
                return int(value)
    return None


def stamp(model: dict[str, Any], version: int = CURRENT_SCHEMA_VERSION) -> dict[str, Any]:
    """Write the schema version into ``model`` (in place) and return it."""
    model[SCHEMA_SHEET] = [{SCHEMA_KEY: int(version)}]
    return model


@dataclass
class MigrationReport:
    """What the cost-basis migration did, for the user-facing notice and the journal."""

    from_version: int = LEGACY_SCHEMA_VERSION
    to_version: int = CURRENT_SCHEMA_VERSION
    migrated: bool = False
    discount_rate: float | None = None
    discount_rate_source: str = ""
    changed_rows: list[dict[str, Any]] = field(default_factory=list)
    #: annual ``e_sum_*`` values moved into the RAGNAROK_AnnualBudgets sheet (schema 2 -> 3)
    budgets: list[dict[str, Any]] = field(default_factory=list)
    review: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def noteworthy(self) -> bool:
        """Something was converted or flagged: worth a notice and a journal entry."""
        return bool(self.changed_rows or self.review or self.budgets)

    def as_dict(self) -> dict[str, Any]:
        return {
            "fromVersion": self.from_version,
            "toVersion": self.to_version,
            "migrated": self.migrated,
            "discountRate": self.discount_rate,
            "discountRateSource": self.discount_rate_source,
            "changedRows": self.changed_rows,
            "budgets": self.budgets,
            "review": self.review,
            "notes": self.notes,
        }


def resolve_discount_rate(
    model: dict[str, Any], explicit: float | None = None
) -> tuple[float | None, str]:
    """The project discount rate and where it came from.

    Order: the caller's value (the run's scenario / the app Settings), the active scenario
    preset (``RAGNAROK_Scenarios``), then a ``discountRate`` key of ``RAGNAROK_Settings``.
    ``(None, "")`` when the workbook states none.
    """
    if explicit is not None and 0.0 <= explicit < 1.0:
        return float(explicit), "the run / app setting"
    import json

    scenarios = model.get("RAGNAROK_Scenarios")
    if isinstance(scenarios, list):
        # the ACTIVE preset first (the frontend writes ``active`` on one row), then any other
        for row in sorted((r for r in scenarios if isinstance(r, dict)), key=lambda r: not _truthy(r.get("active"))):
            payload: Any = row.get("json") or row.get("payload")
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except ValueError:
                    payload = None
            candidate = _number((payload or {}).get("discountRate")) if isinstance(payload, dict) else None
            if candidate is None:
                candidate = _number(row.get("discountRate"))
            if candidate is not None and 0.0 < candidate < 1.0:
                return float(candidate), "the scenario preset"
    settings = model.get("RAGNAROK_Settings")
    if isinstance(settings, list):
        for row in settings:
            if isinstance(row, dict) and str(row.get("key", "")).strip() == "discountRate":
                candidate = _number(row.get("value"))
                if candidate is not None and 0.0 <= candidate < 1.0:
                    return float(candidate), "the project settings"
    return None, ""


def _fallback_rate() -> float:
    return float(load_system_defaults().get("simulation", {}).get("migration_discount_rate", 0.05))


def _fallback_lifetime() -> float:
    return float(load_system_defaults().get("simulation", {}).get("fallback_lifetime_years", 20.0))


def _is_pathway(model: dict[str, Any]) -> bool:
    for row in model.get("RAGNAROK_Pathway") or []:
        if isinstance(row, dict) and _truthy(row.get("enabled")):
            return True
    return False


def _retarget_scenario_overrides(out: dict[str, Any], report: MigrationReport, rate: float) -> None:
    """Saved scenario presets: an override of ``capital_cost`` was an OVERNIGHT price, so it now sets ``overnight_cost``.

    A preset (a ``RAGNAROK_Scenarios`` row, ``json`` payload) may carry ``modelOverrides`` - ``{sheet, name, column, value}``
    cell patches applied to the run's model. After the migration a row's price lives in ``overnight_cost`` (which wins
    over ``capital_cost``), so an override left on ``capital_cost`` would silently do nothing. Each one is retargeted. A
    target row that carries no ``overnight_cost`` after the migration has no ``discount_rate`` for PyPSA to annuitise
    with, so the override set is extended with the project rate for it (and reported).
    """
    import json

    rows = out.get("RAGNAROK_Scenarios")
    if not isinstance(rows, list) or not rows:
        return
    priced = {(c["sheet"], c["name"]) for c in report.changed_rows}
    have_rate = {
        (sheet, str(r.get("name", "")))
        for sheet in _COMPONENTS for r in (out.get(sheet) or [])
        if isinstance(r, dict) and _number(r.get("overnight_cost")) is not None and _number(r.get("discount_rate")) is not None
    } | priced
    retargeted = 0
    new_rows: list[Any] = []
    for row in rows:
        payload = row.get("json") if isinstance(row, dict) else None
        if not isinstance(payload, str):
            new_rows.append(row)
            continue
        try:
            data = json.loads(payload)
        except ValueError:
            new_rows.append(row)
            continue
        overrides = data.get("modelOverrides") if isinstance(data, dict) else None
        if not isinstance(overrides, list):
            new_rows.append(row)
            continue
        extra: list[dict[str, Any]] = []
        for ov in overrides:
            if isinstance(ov, dict) and ov.get("column") == "capital_cost" and ov.get("sheet") in _COMPONENTS:
                ov["column"] = "overnight_cost"
                retargeted += 1
                key = (str(ov.get("sheet")), str(ov.get("name")))
                if key not in have_rate:
                    extra.append({"sheet": ov["sheet"], "name": ov["name"], "column": "discount_rate", "value": rate})
                    have_rate.add(key)
                    report.review.append({
                        "sheet": key[0], "name": key[1],
                        "reason": "a saved scenario overrides its cost, but the row has no overnight_cost/discount_rate: the override now sets "
                                  f"overnight_cost and the project rate ({rate:g}) is added as a discount_rate override; give the row a lifetime.",
                    })
        overrides.extend(extra)
        new_row = dict(row)
        new_row["json"] = json.dumps(data)
        new_rows.append(new_row)
    out["RAGNAROK_Scenarios"] = new_rows
    if retargeted:
        report.notes.append(f"{retargeted} saved scenario override(s) of capital_cost now set overnight_cost.")


def _migrate_costs(out: dict[str, Any], report: MigrationReport, discount_rate: float | None) -> None:
    """Schema 1 -> 2: overnight prices out of ``capital_cost`` (mutates ``out`` and ``report``)."""
    rate, source = resolve_discount_rate(out, discount_rate)
    if rate is None:
        rate, source = _fallback_rate(), "the app default (the workbook states no discount rate)"
    report.discount_rate, report.discount_rate_source = rate, source
    life_default = _fallback_lifetime()
    pathway = _is_pathway(out)

    curves = {
        name.split("-", 1)[0]
        for name, rows in out.items()
        if isinstance(rows, list) and rows and name.endswith("-capital_cost-pw")
    }

    for sheet, ext_col in _COMPONENTS.items():
        source = out.get(sheet)
        if not isinstance(source, list):
            continue
        rows = [dict(r) if isinstance(r, dict) else r for r in source]
        out[sheet] = rows
        for row in rows:
            if not isinstance(row, dict):
                continue
            cost = _number(row.get("capital_cost"))
            if not cost:
                continue
            if _number(row.get("overnight_cost")) is not None:
                continue
            name = str(row.get("name", ""))
            if sheet in curves:
                report.review.append({
                    "sheet": sheet, "name": name,
                    "reason": "has a piecewise capital_cost curve; PyPSA refuses a curve combined with overnight_cost, "
                              "and the curve must be periodised for the horizon. Left as is - review it.",
                })
                continue
            extendable = _truthy(row.get(ext_col))
            old = float(cost)
            row["overnight_cost"] = old
            row["capital_cost"] = 0
            row["discount_rate"] = rate
            life = _number(row.get("lifetime"))
            defaulted = False
            if extendable and (life is None or life <= 0 or life >= _INF_LIFETIME or math.isinf(life)):
                row["lifetime"] = life_default
                defaulted = True
                if pathway and _number(row.get("build_year")):
                    report.review.append({
                        "sheet": sheet, "name": name,
                        "reason": f"lifetime was unset and is now {life_default:g} years; in a multi-period run "
                                  "it now also retires the asset after that many years.",
                    })
            report.changed_rows.append({
                "sheet": sheet, "name": name, "extendable": extendable,
                "capital_cost_was": old, "overnight_cost": old, "discount_rate": rate,
                "lifetime": _number(row.get("lifetime")), "lifetimeDefaulted": defaulted,
            })

    _retarget_scenario_overrides(out, report, rate)

    if curves:
        report.notes.append(
            "Piecewise capital_cost curves are not converted (flagged for review): "
            + ", ".join(sorted(curves)) + "."
        )
    if pathway and report.changed_rows:
        report.notes.append(
            "Multi-period model: PyPSA scales overnight_cost by each period's nyears. The solve is unchanged "
            "while a period represents 8760 h; otherwise it moves by (period hours / 8760)."
        )


def migrate_cost_basis(
    model: dict[str, Any],
    *,
    discount_rate: float | None = None,
    pypsa_native: bool = False,
    budgets: bool = True,
) -> tuple[dict[str, Any], MigrationReport]:
    """Return ``(model, report)`` with ``model`` on the current schema; the input is not mutated.

    Two steps, each skipped when the stamp already covers it: schema 1 -> 2 (costs, below) and 2 -> 3 (annual
    ``e_sum`` values move to the annual-budgets sheet; ``budgets=False`` stops at 2, for a stored run).

    Already stamped, or ``pypsa_native`` (a netcdf / h5 / PyPSA Excel / CSV / MATPOWER import,
    already PyPSA-semantic): only (re)stamped, nothing converted.

    Otherwise every component row with a nonzero ``capital_cost`` and no ``overnight_cost``
    moves to PyPSA's overnight path:

    * ``overnight_cost = capital_cost``, ``capital_cost = 0``;
    * ``discount_rate`` = the project rate (:func:`resolve_discount_rate`; the app default
      ``simulation.migration_discount_rate`` when the workbook states none, which the report says);
    * extendable rows: ``lifetime`` = ``simulation.fallback_lifetime_years`` (20) where it is inf
      or blank, because PyPSA's ``annuity(r, inf) = r`` would otherwise price the asset as
      interest-only - the same fallback the old builder used inside its annuity;
    * NON-extendable rows move too: the old builder left their ``capital_cost`` raw and the LP
      ignored it, but PyPSA's statistics (``capex`` / ``installed_capex``) report it, and an
      overnight price read as a per-horizon cost would overstate sunk capex by ``1 / (a * nyears)``.
      Their ``lifetime`` is NOT touched: it also decides retirement in a multi-period run.

    Components with a piecewise ``capital_cost`` curve are flagged for review and left as they
    are: PyPSA refuses a curve combined with ``overnight_cost`` and the curve itself must be
    periodised for the horizon, which is a decision for the user.
    """
    out = dict(model)  # shallow: only the component sheets that change are copied (below)
    report = MigrationReport()
    current = schema_version(out)
    if current is not None:
        report.from_version = current
    if current is not None and current >= (CURRENT_SCHEMA_VERSION if budgets else COST_SCHEMA_VERSION):
        return out, report
    if pypsa_native:
        report.from_version = CURRENT_SCHEMA_VERSION
        report.notes.append("PyPSA-native file: cost columns already follow PyPSA semantics; stamped, not converted.")
        stamp(out)
        return out, report

    if current is None or current < COST_SCHEMA_VERSION:
        _migrate_costs(out, report, discount_rate)
    if budgets:
        from ...app.annual_budgets import migrate_e_sum

        out, moved = migrate_e_sum(out)
        report.budgets = moved
        if moved:
            report.notes.append(
                f"{len(moved)} e_sum value(s) had ANNUAL semantics (Ragnarok scaled them to the window); they moved to the "
                "RAGNAROK_AnnualBudgets sheet and the annual-budgets module writes the horizon total (annual x hours / 8760) into e_sum."
            )
    report.migrated = True
    stamp(out, CURRENT_SCHEMA_VERSION if budgets else COST_SCHEMA_VERSION)
    return out, report


# ── stored runs ───────────────────────────────────────────────────────────────────

#: ``options["buildVersion"]`` / the run bundle's ``buildVersion``: the cost-basis schema a run was solved under.
BUILD_VERSION_KEY = "buildVersion"


def build_version_of(model: dict[str, Any], options: dict[str, Any] | None = None) -> int | None:
    """The cost-basis schema a stored run was built under; ``None`` for a run that predates the stamp.

    A new run is stamped ``buildVersion`` in its options (and its model carries the schema sheet).
    """
    value = _number((options or {}).get(BUILD_VERSION_KEY))
    if value is not None:
        return int(value)
    return schema_version(model)


def model_for_stored_run(
    model: dict[str, Any],
    scenario: dict[str, Any] | None,
    options: dict[str, Any] | None,
) -> tuple[dict[str, Any], MigrationReport | None]:
    """The model to REBUILD a stored run's network from, on the current cost basis.

    A run stamped ``buildVersion >= 2`` is returned as is. A run without a stamp was solved when
    Ragnarok annuitised ``capital_cost`` itself, so its stored workbook holds OVERNIGHT prices. Its
    analytics (statistics_query, derive_outputs, from_outputs, P2X / plant results) are re-derived
    from the stored outputs on a rebuilt network, so that workbook is migrated IN MEMORY - the same
    :func:`migrate_cost_basis` the loader uses (cost step only), at the run's OWN ``scenario.discountRate`` -
    and PyPSA then prices it exactly as the original solve did (``overnight x annuity x n.nyears`` equals the
    old ``overnight x annuity x hours / 8760``). The stored run is never rewritten and no legacy code path
    survives: a run's numbers are reproduced through PyPSA's own semantics.

    Build version 3 (carbon-pricing and annual-budgets modules) needs no workbook change: the carbon price is
    rebuilt from the stored ``scenario.carbonPrice`` / ``options.carbonPriceSchedule`` and a run before 3 holds
    ANNUAL ``e_sum`` values, which :func:`legacy_e_sum_scale` scales after the build (see there).

    Returns:
        ``(model, report)``; ``report`` is ``None`` when nothing was migrated.
    """
    version = build_version_of(model, options)
    if version is not None and version >= COST_SCHEMA_VERSION:
        return model, None
    raw_rate = (scenario or {}).get("discountRate")
    rate = _number(raw_rate)
    migrated, report = migrate_cost_basis(model, discount_rate=rate, budgets=False)
    return migrated, report


def legacy_e_sum_scale(network: Any, version: int | None) -> float | None:
    """Reproduce a stored run before build version 3: its ``e_sum_*`` were ANNUAL and the old builder scaled them.

    Before version 3 the run builder multiplied every ``*_sum_min`` / ``*_sum_max`` by
    ``min(1, modelled hours / 8760)`` (a pathway: the SMALLEST period's hours). New runs pass the value to PyPSA
    as a horizon total (the annual-budgets module writes it). A stored older run is rebuilt with the same factor so
    its numbers are unchanged. Applied in place, only here, only for ``version < 3``.

    Returns:
        The factor applied (``None`` when nothing was scaled).
    """
    if version is not None and version >= CURRENT_SCHEMA_VERSION:
        return None
    import pandas as pd

    hours = float(load_system_defaults().get("simulation", {}).get("hours_in_year", 8760.0))
    weights = network.snapshot_weightings["objective"]
    if isinstance(network.snapshots, pd.MultiIndex):
        sizes = weights.groupby(level="period").sum()
        factor = min(float(sizes.min()) / hours, 1.0) if len(sizes) else 1.0
    else:
        total = float(weights.sum())
        factor = min(1.0, total / hours) if total > 0 else 1.0
    if factor >= 1.0:
        return None
    for frame in (network.generators, network.storage_units, network.stores):
        for col in list(frame.columns):
            if col.endswith("_sum_min") or col.endswith("_sum_max"):
                frame[col] = frame[col] * factor
    return factor


def horizon_years(model: dict[str, Any]) -> float:
    """The modelled horizon of a workbook in years: ``sum(objective snapshot weights) / 8760``.

    The weights are the ones authored on the ``snapshots`` sheet (``objective`` column) or 1 h per
    snapshot. This is the ``n.nyears`` PyPSA derives for the full time axis, i.e. the factor that
    turns a per-year figure into the per-horizon one ``fom_cost`` and ``capital_cost`` are in. A module
    that writes ``fom_cost`` multiplies its per-year input by it and shows the product. Run-time
    windowing (``snapshotCount`` / ``snapshotWeight``) changes the horizon of THAT run, not of the
    workbook: when it differs, refresh the module's rows (plant edit / re-apply).

    Returns:
        Years; 1.0 when the workbook has no snapshots yet.
    """
    rows = [r for r in (model.get("snapshots") or []) if isinstance(r, dict)]
    if not rows:
        return 1.0
    hours_per_year = float(load_system_defaults().get("simulation", {}).get("hours_in_year", 8760.0))
    total = 0.0
    for row in rows:
        w = _number(row.get("objective"))
        total += 1.0 if w is None else w
    return total / hours_per_year
