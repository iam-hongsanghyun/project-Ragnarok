"""Build a PyPSA Network from the in-memory workbook model.

The frontend POSTs the workbook to /api/run as a per-sheet JSON object:
``model: {sheet_name: [row_dict, ...]}``. We turn each sheet into a pandas
DataFrame and use PyPSA's bulk `network.add()` API to import every column
the user provided. The mapping between sheet names, PyPSA component classes,
time-varying attributes and bus-reference columns is **derived from PyPSA's
own component registry** (`n.components`) so nothing is hardcoded here — when
a new PyPSA version adds attributes or component types, they Just Work.

After import we apply five small post-load transformations that depend on
Settings rather than on the workbook:
  * Snapshot windowing & downsampling
  * Period-factor scaling of ``*_sum_min`` / ``*_sum_max`` annual caps
  * Carbon-price adder on generator marginal_cost
  * Annuitisation of capital_cost for extendable assets
  * Force-LP override of committable=True
  * Optional per-bus load shedding generators
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

import pandas as pd
import pypsa
from pyproj import CRS

from ..config import load_system_defaults
from ..pypsa_schema import (
    input_static_attributes,
    input_temporal_attributes,
    network_runtime_import_fields,
)
from ..utils.annuity import annuity_factor
from ..utils.coerce import number
from .load_shedding import add_load_shedding
from .validators import validate_model  # re-export for backend.main

__all__ = ["build_network", "validate_model"]


def build_network(
    model: dict[str, list[dict[str, Any]]],
    scenario: dict[str, Any],
    options: dict[str, Any] | None = None,
) -> tuple[pypsa.Network, list[str]]:
    """Build a solved-ready PyPSA Network from the JSON workbook model.

    Args:
        model:      ``{sheet_name: [row_dict, ...]}`` — the GUI workbook.
        scenario:   ``{carbonPrice, discountRate, constraints, ...}``
        options:    ``{snapshotStart, snapshotCount, snapshotWeight, forceLp,
                    enableLoadShedding, loadSheddingCost, currencySymbol, …}``

    Returns:
        ``(network, notes)``
    """
    notes: list[str] = []
    options = options or {}

    if "discountRate" not in scenario:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=400,
            detail="discountRate is required (set it in Settings).",
        )
    discount_rate = number(scenario.get("discountRate"))
    carbon_price = number(scenario.get("carbonPrice"), 0.0)
    currency = str(options.get("currencySymbol", "$"))

    network = pypsa.Network()

    _apply_network_sheet(network, model, notes)

    # ── Snapshots ─────────────────────────────────────────────────────────────
    snaps_idx = _snapshots_index(model)
    if len(snaps_idx) > 0:
        network.set_snapshots(snaps_idx)

    # ── Bulk-add every component class PyPSA knows about ──────────────────────
    # Iterate the official component registry — order is dependency-safe
    # (buses before everything that references them, carriers before buses).
    # `network` and `snapshots` are handled explicitly; every other schema-
    # defined sheet should flow through the generic component path.
    ordered = _ordered_component_sheets(network)
    for sheet_name, cls in ordered:
        rows = [r for r in (model.get(sheet_name) or []) if _has_name(r)]
        if not rows:
            continue
        df = pd.DataFrame(rows).set_index("name")
        df = _strip_blank_columns(df)
        allowed_static = input_static_attributes(sheet_name)
        if allowed_static:
            keep = [col for col in df.columns if col in allowed_static or col == "name"]
            df = df.loc[:, keep]
        # Note: zero columns is fine — we still add the components using all
        # PyPSA defaults. Skip only if there are no rows at all.
        if len(df.index) == 0:
            continue
        df = _drop_broken_bus_refs(df, cls, network, sheet_name, notes)
        if len(df.index) == 0:
            continue
        if "carrier" in df.columns and cls != "Carrier":
            _ensure_carriers(network, df["carrier"])
        kwargs = {col: df[col].tolist() for col in df.columns}
        network.add(cls, df.index.tolist(), **kwargs)

    # Generic per-component row count (schema-driven — every populated
    # component class shows up automatically, including new ones PyPSA adds).
    counts = [
        f"{len(network.components[list_name].static)} {list_name}"
        for list_name in network.components.keys()
        if len(network.components[list_name].static) > 0
    ]
    notes.append(
        f"Imported model: {', '.join(counts)}; {len(network.snapshots)} snapshots."
    )

    # ── Time-series sheets ────────────────────────────────────────────────────
    # PyPSA's per-component `defaults` table marks every time-varying attribute
    # (`varying=True`). Sheet name convention is `<list_name>-<attr>`.
    for sheet_name, rows in model.items():
        if not rows or "-" not in sheet_name:
            continue
        list_name, _, attr = sheet_name.partition("-")
        if list_name not in network.components.keys():
            continue
        allowed_temporal = input_temporal_attributes(list_name)
        if allowed_temporal and attr not in allowed_temporal:
            continue
        comp = network.components[list_name]
        if attr not in comp.defaults.index:
            continue
        if not bool(comp.defaults.at[attr, "varying"]):
            continue
        _apply_ts_sheet(network, rows, list_name, attr)

    # ── Snapshot windowing & downsampling ─────────────────────────────────────
    start = max(0, int(number(options.get("snapshotStart"), 0)))
    count = max(1, int(number(options.get("snapshotCount"), len(network.snapshots) or 1)))
    step = max(1, int(number(options.get("snapshotWeight"), 1)))
    full = network.snapshots
    if len(full) > 0:
        stop = min(len(full), start + count)
        windowed = full[start:stop]
        if step > 1:
            windowed = windowed[::step]
        if len(windowed) == 0:
            windowed = full[:1]
        network.set_snapshots(windowed)
        for col in ("objective", "stores", "generators"):
            network.snapshot_weightings[col] = float(step)
        notes.append(
            f"Modelled {len(windowed)} snapshots at {step}h resolution "
            f"(rows {start} → {stop} of {len(full)})."
        )

    # ── Period-factor scaling of annual energy caps ───────────────────────────
    sim_cfg = load_system_defaults().get("simulation", {})
    hours_in_year = float(sim_cfg.get("hours_in_year", 8760.0))
    modelled_hours = float(len(network.snapshots)) * float(step)
    period_factor = min(1.0, modelled_hours / hours_in_year) if modelled_hours > 0 else 1.0
    if period_factor < 1.0:
        for frame in (network.generators, network.storage_units, network.stores):
            for col in list(frame.columns):
                if col.endswith("_sum_min") or col.endswith("_sum_max"):
                    frame[col] = frame[col] * period_factor
        notes.append(f"Scaled annual energy-sum caps by period factor {period_factor:.3f}.")

    # ── Carbon-price adder on generator marginal cost ─────────────────────────
    if carbon_price > 0 and "co2_emissions" in network.carriers.columns:
        ef = network.carriers["co2_emissions"]
        gen_ef = network.generators["carrier"].map(ef).fillna(0.0)
        if (gen_ef > 0).any():
            network.generators["marginal_cost"] = (
                network.generators["marginal_cost"].fillna(0.0)
                + carbon_price * gen_ef
            )
            notes.append(
                f"Applied carbon price {carbon_price:.2f} {currency}/t to "
                f"{(gen_ef > 0).sum()} emitting generator(s)."
            )

    # ── Annuitise CAPEX for extendable assets ─────────────────────────────────
    # The extendable flag column name varies by component (p_nom_extendable,
    # s_nom_extendable, e_nom_extendable). Find it via PyPSA's defaults.
    for list_name in ("generators", "storage_units", "stores", "lines", "links"):
        comp = network.components[list_name]
        frame = comp.static
        ext_cols = [c for c in frame.columns if c.endswith("_nom_extendable")]
        if not ext_cols or "capital_cost" not in frame.columns:
            continue
        ext = frame[ext_cols[0]].astype(bool)
        if not ext.any():
            continue
        if "lifetime" in frame.columns:
            lifetimes = frame.loc[ext, "lifetime"].replace(0, pd.NA).fillna(20.0)
        else:
            lifetimes = pd.Series(20.0, index=frame.index[ext])
        afs = lifetimes.apply(lambda L: annuity_factor(discount_rate, float(L)))
        frame.loc[ext, "capital_cost"] = frame.loc[ext, "capital_cost"].fillna(0.0) * afs
        notes.append(
            f"Annualised CAPEX for {int(ext.sum())} extendable {comp.name}(s) "
            f"at discount rate {discount_rate:.3f}."
        )

    # ── Force-LP override (ignore committable=True flags) ─────────────────────
    if bool(options.get("forceLp", False)) and "committable" in network.generators.columns:
        n_committable = int(network.generators["committable"].astype(bool).sum())
        if n_committable > 0:
            network.generators["committable"] = False
            notes.append(
                f"Force-LP enabled: overrode committable=True on {n_committable} generator(s)."
            )

    # ── Carbon-price emission factor sanity warning ───────────────────────────
    if "co2_emissions" in network.carriers.columns:
        suspect = network.carriers[network.carriers["co2_emissions"] > 5.0]
        for carrier_name in suspect.index:
            val = float(suspect.at[carrier_name, "co2_emissions"])
            notes.append(
                f"Warning: carrier '{carrier_name}' has co2_emissions={val} "
                f"(expected tCO₂/MWh, real fuels ≤ ~1). If this is kg/MWh, divide by 1000."
            )

    # ── Per-bus load shedding (optional VOLL backstop) ────────────────────────
    load_totals = _peak_load_per_bus(network)
    enable_load_shedding = bool(options.get("enableLoadShedding", False))
    load_shedding_cost = options.get("loadSheddingCost")
    add_load_shedding(
        network,
        load_totals,
        notes,
        enable_load_shedding=enable_load_shedding,
        load_shedding_cost=load_shedding_cost,
        currency=currency,
    )

    final_counts = ", ".join(
        f"{len(network.components[list_name].static)} {list_name}"
        for list_name in network.components.keys()
        if len(network.components[list_name].static) > 0
    )
    notes.append(f"Prepared PyPSA case with {final_counts}.")
    return network, notes


# ── Helpers ─────────────────────────────────────────────────────────────────


def _has_name(row: dict[str, Any]) -> bool:
    name = row.get("name")
    return name is not None and str(name).strip() != ""


def _strip_blank_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Drop columns that are entirely null or blank — let PyPSA defaults apply."""
    df = df.dropna(axis=1, how="all")
    for col in list(df.columns):
        if df[col].astype(str).str.strip().eq("").all():
            df = df.drop(columns=[col])
    return df


def _ordered_component_sheets(network: pypsa.Network) -> list[tuple[str, str]]:
    """Return [(sheet_name, pypsa_class_name), …] in dependency-safe order.

    Carriers and buses must be added before anything that references them. The
    remainder follows PyPSA's own component registry order.
    """
    keys = list(network.components.keys())
    priority = {"carriers": 0, "buses": 1}
    sortable: list[tuple[int, int, str, str]] = []
    for i, list_name in enumerate(keys):
        comp = network.components[list_name]
        sortable.append((priority.get(list_name, 99), i, list_name, comp.name))
    sortable.sort()
    return [(list_name, cls) for _, _, list_name, cls in sortable]


def _apply_network_sheet(
    network: pypsa.Network,
    model: dict[str, list[dict[str, Any]]],
    notes: list[str],
) -> None:
    rows = model.get("network") or []
    network_row = next(
        (
            row for row in rows
            if any(value not in (None, "") for value in row.values())
        ),
        None,
    )
    if not network_row:
        return

    applied_fields: list[str] = []
    for policy in network_runtime_import_fields():
        field = str(policy.get("field", "")).strip()
        if not field:
            continue
        value = network_row.get(field)
        if value in (None, ""):
            continue
        coercion = str(policy.get("coercion", "any"))
        if field == "name":
            network.name = str(value)
        elif field == "srid":
            _override_network_crs(network, CRS.from_epsg(int(number(value))))
        elif field == "crs":
            _override_network_crs(network, CRS.from_user_input(value))
        elif field == "now":
            network.now = value
        else:
            continue
        applied_fields.append(field)

    if applied_fields:
        notes.append(
            "Applied network sheet fields: " + ", ".join(applied_fields) + "."
        )


def _override_network_crs(network: pypsa.Network, crs: CRS) -> None:
    shapes = network.c.shapes.static
    shapes = shapes.set_crs(crs, allow_override=True)
    network.c.shapes.static = shapes
    network._crs = shapes.crs


def _snapshots_index(model: dict[str, list[dict[str, Any]]]) -> pd.Index:
    """Build the snapshot index from the `snapshots` sheet, if present."""
    rows = model.get("snapshots") or []
    labels: list[str] = []
    for r in rows:
        for k in ("snapshot", "name", "datetime", "timestep", "index"):
            v = r.get(k)
            if v not in (None, ""):
                labels.append(str(v))
                break
    if not labels:
        return pd.Index([], dtype="object")
    try:
        return pd.to_datetime(labels)
    except Exception:
        return pd.Index(labels, dtype="object")


def _bus_ref_columns(network: pypsa.Network, cls: str) -> list[str]:
    """Return the column names of bus references for a PyPSA component class.

    Looks up PyPSA's attribute schema rather than hardcoding which classes
    have `bus` vs `bus0/bus1` vs `bus0..bus3`.
    """
    # Find the component by class name
    for list_name in network.components.keys():
        if network.components[list_name].name != cls:
            return _bus_ref_columns_for_list(network, list_name)
    return []


def _bus_ref_columns_for_list(network: pypsa.Network, list_name: str) -> list[str]:
    defaults = network.components[list_name].defaults
    return [a for a in defaults.index if a == "bus" or (a.startswith("bus") and a[3:].isdigit())]


def _drop_broken_bus_refs(
    df: pd.DataFrame,
    cls: str,
    network: pypsa.Network,
    sheet: str,
    notes: list[str],
) -> pd.DataFrame:
    """Drop rows where a required bus reference points to a missing bus."""
    bus_cols = _bus_ref_columns_for_list(network, sheet)
    if not bus_cols:
        return df
    # Only the primary bus (bus or bus0/bus1) is required; bus2/bus3 are optional.
    required = [c for c in bus_cols if c in ("bus", "bus0", "bus1")]
    if not required:
        return df
    valid_buses = set(network.buses.index)
    keep_mask = pd.Series(True, index=df.index)
    skipped: list[str] = []
    for col in required:
        if col not in df.columns:
            notes.append(f"Sheet '{sheet}' has no '{col}' column — all rows skipped.")
            return df.iloc[0:0]
        for name, bus in df[col].items():
            if pd.isna(bus) or str(bus).strip() == "" or str(bus) not in valid_buses:
                keep_mask[name] = False
                skipped.append(f"{name} ({col}='{bus}')")
    dropped = (~keep_mask).sum()
    if dropped:
        notes.append(
            f"{cls}: {int(dropped)} row(s) skipped — bus reference missing: "
            f"{', '.join(skipped[:5])}{' …' if len(skipped) > 5 else ''}"
        )
    return df[keep_mask]


def _ensure_carriers(network: pypsa.Network, carriers: pd.Series) -> None:
    """Auto-add any carrier referenced by a component but missing from carriers sheet."""
    referenced = {str(c).strip() for c in carriers.dropna().unique() if str(c).strip()}
    missing = referenced - set(network.carriers.index)
    for name in missing:
        network.add("Carrier", name)


def _apply_ts_sheet(
    network: pypsa.Network,
    rows: list[dict[str, Any]],
    list_name: str,
    attr: str,
) -> None:
    """Assign a time-series sheet to ``network.<list_name>_t.<attr>``."""
    df = pd.DataFrame(rows)
    label_col = next(
        (k for k in ("snapshot", "datetime", "name", "index", "timestep") if k in df.columns),
        None,
    )
    if label_col is None:
        return
    try:
        idx = pd.to_datetime(df[label_col])
    except Exception:
        idx = pd.Index(df[label_col].astype(str))
    data = df.drop(columns=[label_col])
    if data.empty:
        return
    data.index = idx
    static_frame = network.components[list_name].static
    valid_cols = [c for c in data.columns if c in static_frame.index]
    if not valid_cols:
        return
    data = data[valid_cols].apply(pd.to_numeric, errors="coerce")
    if len(network.snapshots) > 0:
        data = data.reindex(network.snapshots)
    t_frame = getattr(network, list_name + "_t")
    current = getattr(t_frame, attr)
    # Re-stitch via concat (avoid the per-column-insert performance warning).
    merged = pd.concat(
        [current.drop(columns=[c for c in current.columns if c in data.columns]), data],
        axis=1,
    )
    setattr(t_frame, attr, merged)


def _peak_load_per_bus(network: pypsa.Network) -> dict[str, float]:
    """Sum of peak load (across snapshots) at each bus.

    Used to size the load-shedding generator's p_nom uncapped.
    """
    totals: dict[str, float] = defaultdict(float)
    if network.loads.empty:
        return {}
    load_to_bus = network.loads["bus"].to_dict()
    if not network.loads_t.p_set.empty:
        peaks = network.loads_t.p_set.max(axis=0)
        for load_name, bus in load_to_bus.items():
            if load_name in peaks.index:
                totals[bus] += float(peaks[load_name])
            elif "p_set" in network.loads.columns:
                totals[bus] += float(network.loads.at[load_name, "p_set"])
    else:
        for load_name, bus in load_to_bus.items():
            if "p_set" in network.loads.columns:
                totals[bus] += float(network.loads.at[load_name, "p_set"])
    return dict(totals)
