"""Pre-run guards that used to exist only in the browser's run handler (``App.tsx``).

A run submitted by anything other than the browser (MCP, a script, a plugin) must
be stopped for the same reasons the UI stops it, otherwise the typo'd carrier cap
"solves" with the cap silently skipped. :func:`run_input_problems` is called from
``main._refuse_invalid_model`` and returns plain sentences the caller can act on.

Guards (each mirrors a check in ``handleRunModel``):

* empty / inverted snapshot window,
* custom-constraint DSL text that does not parse (the text the solver will use),
* an enabled carrier constraint whose carrier no generator carries.

DSL precedence (also documented in ``docs/API.md``): the solver applies, in order,
``scenario.constraintSpecs`` (structured, what the UI sends) when the key is present,
else ``scenario.customDsl`` (text) when present, else the model's
``RAGNAROK_CustomDSL`` sheet. :func:`apply_model_dsl_fallback` does the last step at
submit time, so the snapshot a queued run carries already includes it.
"""

from __future__ import annotations

import math
from typing import Any

from .scenario_presets import (
    generator_carriers,
    parse_constraint_dsl,
    read_custom_dsl,
    unresolved_carrier_constraints,
)


def apply_model_dsl_fallback(model: dict[str, Any] | None, scenario: dict[str, Any] | None) -> dict[str, Any]:
    """Return ``scenario`` with the model's DSL sheet filled in when the run names no DSL.

    Only when BOTH ``constraintSpecs`` and ``customDsl`` are absent (``None``/missing).
    An explicitly empty value means "no DSL for this run" and is respected, so a UI
    run (which always sends ``constraintSpecs``, possibly ``[]``) and a re-run of a
    stored run are unchanged. The returned scenario is a copy.
    """
    out = dict(scenario or {})
    if out.get("constraintSpecs") is not None or out.get("customDsl") is not None:
        return out
    text = read_custom_dsl(model or {})
    if text.strip():
        out["customDsl"] = text
    return out


def window_problem(options: dict[str, Any] | None) -> str | None:
    """The run window the solver will use is empty or inverted (``App.tsx`` first guard)."""
    opts = options or {}
    start, end, count = opts.get("snapshotStart"), opts.get("snapshotEnd"), opts.get("snapshotCount")
    # Same precedence as network.build_network: snapshotCount wins, else end - start.
    if count in (None, ""):
        if end in (None, ""):
            return None  # no window given: the solver models every snapshot
        start_n = _num(start, 0.0)
        count = _num(end, math.nan) - start_n
    else:
        count = _num(count, math.nan)
    if not math.isfinite(count) or count <= 0:
        return (
            f"the snapshot window is empty (snapshotStart={start!r}, snapshotEnd={end!r}, "
            f"snapshotCount={opts.get('snapshotCount')!r}). Set snapshotEnd after snapshotStart, "
            "or omit all three to model every snapshot."
        )
    return None


def _num(value: Any, fallback: float) -> float:
    if isinstance(value, bool):
        return fallback
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return fallback
    return fallback


def dsl_problem(scenario: dict[str, Any] | None) -> str | None:
    """Syntax errors in the DSL text the solver will apply (``scenario.customDsl``)."""
    text = (scenario or {}).get("customDsl")
    if not isinstance(text, str) or not text.strip():
        return None
    errors = [line for line in parse_constraint_dsl(text) if "error" in line]
    if not errors:
        return None
    shown = "; ".join(f"line {e['lineNo']}: {e['error']}" for e in errors[:5])
    return (
        f"{len(errors)} custom-constraint (DSL) line(s) have syntax errors and would NOT be applied ({shown}). "
        "Fix the text (scenario.customDsl or the model's RAGNAROK_CustomDSL sheet)."
    )


def carrier_problem(model: dict[str, Any] | None, scenario: dict[str, Any] | None) -> str | None:
    """Enabled carrier constraints that reference a carrier no generator uses."""
    constraints = [c for c in (scenario or {}).get("constraints") or [] if isinstance(c, dict)]
    carriers = generator_carriers(model or {})
    unresolved = unresolved_carrier_constraints(constraints, carriers)
    if not unresolved:
        return None
    names = ", ".join(f'"{c.get("label") or c.get("metric")}" (carrier "{c.get("carrier")}")' for c in unresolved)
    known = f"This model's generator carriers are: {', '.join(carriers)}." if carriers else "This model has no generator carriers."
    return (
        f"{len(unresolved)} enabled constraint(s) reference a carrier no generator uses, so the cap would be "
        f"silently skipped: {names}. {known} Fix the carrier or set enabled=false."
    )


def run_input_problems(
    model: dict[str, Any] | None, scenario: dict[str, Any] | None, options: dict[str, Any] | None
) -> list[str]:
    """Every browser-side pre-run guard, as sentences (empty list = clear to run)."""
    problems = [
        p
        for p in (window_problem(options), dsl_problem(scenario), carrier_problem(model, scenario))
        if p
    ]
    return problems
