"""Promote screened sites into the model as generators with ``p_max_pu`` profiles.

Pure fragment building (no I/O): the screening dataset's per-site CF series
become ``generators`` rows plus a ``generators-p_max_pu`` sheet aligned to the
model's snapshots, packed as a ``WorkbookFragment`` so the ONE existing merge
path (``fragment_merge.merge_fragment``, served by ``POST
/api/session/merge-fragment`` and the GUI's "Add to workbook") applies it.

Alignment reuses :func:`backend.app.siting.core.align_cf_to_targets` — the same
rules as the siting scan: each dataset stamp (UTC) is shifted by ``utc_offset``
to the model's clock, then a snapshot is matched by exact hour, by the same
month-day-hour of another year, or by the hour-of-day mean. Every problem is
reported, never silent.
"""
from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any

import pandas as pd

from ..importers.protocol import Provenance, WorkbookFragment
from ..siting.core import align_cf_to_targets, haversine_km

DEFAULT_P_NOM_MW = 100.0
_NAME_SAFE = re.compile(r"[^A-Za-z0-9_]+")
#: Below this share of exactly matched snapshots the alignment is flagged as weak.
WEAK_EXACT_SHARE = 0.9


def generator_name(tech: str, site: str) -> str:
    """``screen_<tech>_<site>`` with the site name reduced to letters, digits and underscores."""
    return f"screen_{tech}_{_NAME_SAFE.sub('_', site).strip('_') or 'site'}"


def _nearest_bus(lat: float, lon: float, buses: list[dict[str, Any]]) -> tuple[str, float] | None:
    best: tuple[str, float] | None = None
    for b in buses:
        name, x, y = str(b.get("name") or "").strip(), b.get("x"), b.get("y")
        if not name or x in (None, "") or y in (None, ""):
            continue
        d = haversine_km(lat, lon, float(y), float(x))
        if best is None or d < best[1]:
            best = (name, d)
    return best


def _hourly(series: pd.DataFrame, step_minutes: float | None) -> tuple[pd.DataFrame, str | None]:
    """The series on an hourly grid and a note when it had to be resampled."""
    if step_minutes is None or abs(step_minutes - 60.0) < 1e-6:
        return series, None
    if step_minutes < 60.0:
        return series.resample("1h").mean().dropna(how="all"), (
            f"Dataset step is {step_minutes:g} min; averaged to hourly before alignment."
        )
    return series.resample("1h").ffill(), (
        f"Dataset step is {step_minutes:g} min (coarser than hourly); each value was held for the whole step."
    )


def build_promotion(
    series: pd.DataFrame,
    sites: list[dict[str, Any]],
    selected: list[str],
    *,
    step_minutes: float | None,
    target_snapshots: list[str],
    buses: list[dict[str, Any]],
    existing_generators: set[str] | None = None,
    utc_offset: int = 0,
    p_nom_mw: dict[str, float] | None = None,
    extendable: bool = False,
    capital_cost: dict[str, float] | None = None,
    marginal_cost: float = 0.0,
    bus_overrides: dict[str, str] | None = None,
    dataset_id: str = "",
) -> tuple[WorkbookFragment, dict[str, Any]]:
    """Build the generator fragment for the selected sites and the alignment report.

    Args:
        series: stored dataset frame (UTC index, CF 0-1, one column per site).
        sites: the dataset's site rows (``name, lat, lon, technology, capacityMw``).
        selected: site names to promote.
        step_minutes: native step of ``series``.
        target_snapshots: the model's snapshot labels (local time). Empty = the model has
            none: the dataset window itself becomes the snapshots.
        buses: model buses (``name``, ``x`` = lon, ``y`` = lat); a site attaches to the
            nearest one unless ``bus_overrides`` names a bus.
        existing_generators: names already in the model (a clash is reported; the merge dedupes).
        utc_offset: hours from UTC to the model's clock.
        p_nom_mw: per-site capacity; default the site's own capacity, else :data:`DEFAULT_P_NOM_MW`.
        extendable: when True the generators start at 0 MW and ``p_nom_mw`` becomes ``p_nom_max``.
        capital_cost: per-technology capex (currency/MW) for extendable generators.
        marginal_cost: operating cost (currency/MWh).
        bus_overrides: ``{site: bus}``.
        dataset_id: echoed into provenance.

    Returns:
        ``(fragment, report)``. ``report`` has per-site alignment counts and ``warnings``;
        ``report["ok"]`` is False when nothing aligned exactly or a hard problem was found.

    Raises:
        ValueError: nothing selected, unknown site, or no bus to attach a site to.
    """
    by_name = {s["name"]: s for s in sites}
    if not selected:
        raise ValueError("Select at least one site to add.")
    unknown = [s for s in selected if s not in by_name or s not in series.columns]
    if unknown:
        raise ValueError(f"Unknown site(s) in this dataset: {unknown}.")
    overrides = bus_overrides or {}
    costs = capital_cost or {}
    warnings: list[str] = []
    hourly, note = _hourly(series[selected], step_minutes)
    if note:
        warnings.append(note)

    own_mode = not target_snapshots
    utc_times = [str(t).replace("T", " ") for t in hourly.index]
    if own_mode:
        snapshots = [(t + pd.Timedelta(hours=int(utc_offset))).strftime("%Y-%m-%d %H:%M") for t in hourly.index]
        warnings.append(
            f"The model has no snapshots: the dataset window ({snapshots[0]} to {snapshots[-1]}, {len(snapshots)} h) becomes the snapshot axis."
        )
    else:
        snapshots = [str(s) for s in target_snapshots]
        stamps = pd.to_datetime([s.replace("T", " ") for s in snapshots], errors="coerce")
        if stamps.isna().any():
            warnings.append(f"{int(stamps.isna().sum())} model snapshot label(s) are not timestamps and cannot be matched by time.")
        valid = stamps.dropna()
        if len(valid) > 2:
            model_step = pd.Series(valid[1:] - valid[:-1]).median()
            if model_step != pd.Timedelta(hours=1):
                warnings.append(f"Model snapshots are {model_step} apart; profile values are sampled at the snapshot hour, not averaged over the step.")

    gen_rows: list[dict[str, Any]] = []
    carriers: dict[str, dict[str, Any]] = {}
    columns: dict[str, list[float | None]] = {}
    per_site: list[dict[str, Any]] = []
    taken = existing_generators or set()
    for name in selected:
        site = by_name[name]
        cf = [float(v) for v in hourly[name].to_numpy()]
        if own_mode:
            aligned: list[float | None] = list(cf)
            counts = {"exact": len(cf), "month_day_hour": 0, "hour_of_day": 0}
        else:
            aligned, counts = align_cf_to_targets(cf, utc_times, int(utc_offset), snapshots)
        mean_cf = float(sum(cf) / len(cf)) if cf else 0.0
        unaligned = sum(1 for v in aligned if v is None)
        filled = [mean_cf if v is None else round(float(v), 4) for v in aligned]
        gen = generator_name(site["technology"], name)
        if gen in taken:
            warnings.append(f"Generator {gen} already exists in the model; the merge will add it as a renamed copy.")
        bus = overrides.get(name)
        dist: float | None = None
        if not bus:
            near = _nearest_bus(float(site["lat"]), float(site["lon"]), buses)
            if near is None:
                raise ValueError(f"No bus with x/y coordinates to attach {name} to; pass a bus for it.")
            bus, dist = near[0], round(near[1], 1)
        cap = float((p_nom_mw or {}).get(name) or site.get("capacityMw") or DEFAULT_P_NOM_MW)
        tech = str(site["technology"])
        carriers.setdefault(tech, {"name": tech, "co2_emissions": 0.0})
        gen_rows.append({
            "name": gen, "bus": bus, "carrier": tech,
            "p_nom": 0.0 if extendable else cap,
            "p_nom_extendable": bool(extendable),
            **({"p_nom_max": cap, "capital_cost": float(costs.get(tech) or 0.0)} if extendable else {}),
            "marginal_cost": float(marginal_cost),
            "x": float(site["lon"]), "y": float(site["lat"]),
        })
        columns[gen] = filled
        n_target = len(aligned)
        per_site.append({
            "site": name, "generator": gen, "bus": bus, "busDistanceKm": dist, "pNomMw": cap,
            "meanCf": round(mean_cf, 4),
            "alignment": {"exact": counts["exact"], "monthDayHour": counts["month_day_hour"],
                          "hourOfDay": counts["hour_of_day"], "unaligned": unaligned, "total": n_target},
        })
        if not own_mode:
            if counts["exact"] == 0:
                warnings.append(
                    f"{name}: no snapshot matches the dataset's timestamps (dataset {hourly.index[0].date()} to {hourly.index[-1].date()}, "
                    f"model {snapshots[0]} to {snapshots[-1]}); the profile repeats the same calendar hour of another year."
                    if counts["month_day_hour"] else
                    f"{name}: no snapshot matches the dataset's calendar; the profile is the mean hour-of-day shape."
                )
            elif counts["exact"] < WEAK_EXACT_SHARE * n_target:
                warnings.append(f"{name}: only {counts['exact']} of {n_target} snapshots matched exactly "
                                f"({counts['month_day_hour']} by calendar hour, {counts['hour_of_day']} by hour-of-day mean).")
            if unaligned:
                warnings.append(f"{name}: {unaligned} snapshot(s) could not be matched and carry the site's mean CF.")

    p_rows = [
        {"snapshot": snap, **{g: col[i] for g, col in columns.items()}}
        for i, snap in enumerate(snapshots)
    ]
    frag = WorkbookFragment()
    frag.sheets["carriers"] = list(carriers.values())
    frag.sheets["generators"] = gen_rows
    frag.sheets["generators-p_max_pu"] = p_rows
    frag.snapshots = snapshots
    frag.provenance = Provenance(
        "screening", "", "Site screening",
        json.dumps({"dataset": dataset_id, "sites": selected, "utcOffset": int(utc_offset)}, sort_keys=True),
        json.dumps({"extendable": bool(extendable), "marginal_cost": float(marginal_cost)}, sort_keys=True),
        datetime.now(UTC).isoformat(timespec="seconds"),
        json.dumps({s: len(r) for s, r in frag.sheets.items()}, sort_keys=True),
    )
    exact_total = sum(s["alignment"]["exact"] for s in per_site)
    all_total = sum(s["alignment"]["total"] for s in per_site) or 1
    report = {
        "mode": "own-snapshots" if own_mode else "model-snapshots",
        "snapshots": len(snapshots),
        "exactShare": exact_total / all_total,
        "sites": per_site,
        "warnings": warnings,
        "ok": own_mode or exact_total > 0,
    }
    return frag, report
