"""Pre-flight checks that mirror PyPSA 1.4's own errors (P27, P37).

* :func:`check_global_constraints` / :func:`check_growth_limits` are cheap,
  workbook-level checks (no network build) run by ``validate_model``. They catch
  the 1.4 ``ValueError`` for ``investment_period`` on a single-period network and
  growth limits that cannot bind.
* :func:`consistency_report` builds the network and runs PyPSA's
  ``n.consistency_check(strict=...)``, returning every finding (warnings are
  captured from PyPSA's logger, strict failures become errors) so mistakes
  surface in seconds rather than mid-solve.
"""
from __future__ import annotations

import logging
import math
from typing import Any

from ..utils.coerce import number
from ..utils.workbook import workbook_rows

_GLC_TYPES = (
    "primary_energy",
    "operational_limit",
    "tech_capacity_expansion_limit",
    "transmission_volume_expansion_limit",
    "transmission_expansion_cost_limit",
)
# Types for which PyPSA 1.4 raises ValueError when ``investment_period`` is set on a
# network without investment periods (global_constraints.py, primary_energy and
# operational_limit builders).
_PERIOD_SENSITIVE = ("primary_energy", "operational_limit")


def _has_value(raw: Any) -> bool:
    if raw in (None, ""):
        return False
    if isinstance(raw, float) and math.isnan(raw):
        return False
    return True


def check_global_constraints(
    model: dict[str, list[dict[str, Any]]],
    *,
    pathway_enabled: bool,
    periods: list[int] | None = None,
) -> tuple[list[str], list[str]]:
    """Validate the ``global_constraints`` sheet against PyPSA 1.4's rules.

    Args:
        model: the workbook.
        pathway_enabled: whether the run is multi-investment-period.
        periods: configured investment periods (pathway mode).

    Returns:
        ``(errors, warnings)``.
    """
    errors: list[str] = []
    warnings: list[str] = []
    carriers = {str(r.get("name")) for r in workbook_rows(model, "carriers") if r.get("name")}
    carrier_cols: set[str] = set()
    for row in workbook_rows(model, "carriers"):
        carrier_cols.update(str(k) for k in row)
    for row in workbook_rows(model, "global_constraints"):
        name = str(row.get("name") or "").strip() or "(unnamed)"
        gtype = str(row.get("type") or "primary_energy").strip() or "primary_energy"
        sense = str(row.get("sense") or "==").strip() or "=="
        if gtype not in _GLC_TYPES:
            errors.append(f"global_constraints '{name}': unknown type '{gtype}' (use one of {', '.join(_GLC_TYPES)}).")
        if sense not in ("<=", "==", ">="):
            errors.append(f"global_constraints '{name}': sense must be <=, == or >=, got '{sense}'.")
        if _has_value(row.get("investment_period")):
            period = number(row.get("investment_period"), None)
            if not pathway_enabled and gtype in _PERIOD_SENSITIVE:
                errors.append(
                    f"global_constraints '{name}': investment_period is set but the run has no investment periods "
                    f"(PyPSA 1.4 raises ValueError for type '{gtype}'). Clear it or enable pathway mode."
                )
            elif pathway_enabled and periods and period is not None and int(period) not in periods:
                warnings.append(
                    f"global_constraints '{name}': investment_period {int(period)} is not one of the configured "
                    f"periods {periods}; the constraint will not bind."
                )
        attr = str(row.get("carrier_attribute") or "").strip()
        if gtype == "primary_energy" and carrier_cols and attr and attr not in carrier_cols:
            warnings.append(
                f"global_constraints '{name}': carrier_attribute '{attr}' is not a column of the carriers sheet."
            )
        if gtype == "tech_capacity_expansion_limit":
            if attr and carriers and attr not in carriers:
                warnings.append(
                    f"global_constraints '{name}': tech_capacity_expansion_limit carrier_attribute is the carrier "
                    f"name; '{attr}' is not a carrier."
                )
            if not attr:
                errors.append(f"global_constraints '{name}': tech_capacity_expansion_limit needs carrier_attribute (the carrier).")
    return errors, warnings


def check_growth_limits(
    model: dict[str, list[dict[str, Any]]], *, pathway_enabled: bool
) -> list[str]:
    """Warn about ``carriers.max_growth`` / ``max_relative_growth`` that cannot bind.

    Growth limits cap *new* capacity per investment period, so they are inert on
    a single-period run; a negative value is meaningless.
    """
    out: list[str] = []
    for row in workbook_rows(model, "carriers"):
        name = str(row.get("name") or "")
        for attr in ("max_growth", "max_relative_growth"):
            if not _has_value(row.get(attr)):
                continue
            value = number(row.get(attr), None)
            if value is None or math.isinf(value):
                continue
            if attr == "max_relative_growth" and value == 0.0:
                continue  # PyPSA default: unlimited
            if value < 0:
                out.append(f"carriers '{name}': {attr}={value:g} is negative.")
            elif not pathway_enabled:
                out.append(
                    f"carriers '{name}': {attr} limits new capacity per investment period and has no effect "
                    "on a single-period run."
                )
    return out


class _Capture(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


def consistency_report(
    model: dict[str, list[dict[str, Any]]],
    scenario: dict[str, Any] | None = None,
    options: dict[str, Any] | None = None,
    *,
    strict: list[str] | None = None,
    check_dtypes: bool = False,
) -> dict[str, Any]:
    """Run PyPSA's ``n.consistency_check`` on the model and return every finding.

    Args:
        model: the workbook (``{sheet: rows}``).
        scenario, options: as for ``run_pypsa`` (pathway/stochastic shape the network).
        strict: check names that must raise instead of warn (PyPSA defaults
            ``dispatch_delays``, ``maintenance``, ``phase_shift_bounds`` when None;
            ``["all"]`` makes everything strict).
        check_dtypes: also check attribute dtypes.

    Returns:
        ``{valid, errors, warnings, strict}``: ``errors`` holds the strict failure
        (``ConsistencyError``) or a build failure; ``warnings`` every logged finding.
    """
    from fastapi import HTTPException

    from . import build_network

    handler = _Capture()
    plog = logging.getLogger("pypsa.consistency")
    errors: list[str] = []
    try:
        network, _notes = build_network(model, scenario or {}, options or {})
    except HTTPException as exc:
        return {"valid": False, "errors": [f"build failed: {exc.detail}"], "warnings": [], "strict": strict}
    except Exception as exc:  # noqa: BLE001 - report, never raise into the caller
        return {"valid": False, "errors": [f"build failed: {exc}"], "warnings": [], "strict": strict}
    plog.addHandler(handler)
    try:
        network.consistency_check(check_dtypes=check_dtypes, strict=strict)
    except ValueError as exc:  # ConsistencyError subclasses ValueError; bad strict names too
        errors.append(str(exc))
    finally:
        plog.removeHandler(handler)
    return {
        "valid": not errors,
        "errors": errors,
        "warnings": list(dict.fromkeys(handler.messages)),
        "strict": strict,
    }
