"""Build a PyPSA Network from an uploaded Excel workbook.

We delegate row-by-row workbook parsing to PyPSA's own `import_from_excel`
reader. This avoids hand-rolled, per-component importers that would silently
drop unknown columns or fabricate defaults. After import, we apply a small
set of derived transformations (snapshot windowing, carbon adder, capex
annuitisation, force-LP, load shedding) that depend on Settings rather than
on the workbook itself.
"""
from __future__ import annotations

import os
import tempfile
from collections import defaultdict
from typing import Any

import pandas as pd
import pypsa

from ..utils.annuity import annuity_factor
from ..utils.coerce import number
from .generators import add_load_shedding
from .validators import validate_model  # re-export for backend.main

__all__ = ["build_network", "validate_model"]


def build_network(
    xlsx_bytes: bytes,
    scenario: dict[str, Any],
    options: dict[str, Any] | None = None,
) -> tuple[pypsa.Network, list[str]]:
    """Build a solved-ready PyPSA Network from the uploaded workbook bytes.

    Args:
        xlsx_bytes: raw bytes of the user's Excel workbook (the same workbook
            shown in the GUI; round-tripped via `workbookToArrayBuffer`).
        scenario:   {carbonPrice, discountRate, constraints, ...}
        options:    {snapshotStart, snapshotCount, snapshotWeight, forceLp,
                    enableLoadShedding, loadSheddingCost, currencySymbol, ...}

    Returns:
        (network, notes) — the configured network and a list of human-readable
        notes for the Run narrative panel.
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

    # ── Load via PyPSA's native Excel importer ────────────────────────────────
    # PyPSA's reader handles every standard sheet (buses, generators, lines,
    # storage_units, …) and every standard time-series sheet (loads-p_set,
    # generators-p_max_pu, …) without us having to enumerate columns.
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        tmp.write(xlsx_bytes)
        tmp_path = tmp.name
    try:
        network = pypsa.Network()
        network.import_from_excel(tmp_path)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    notes.append(
        f"Imported workbook via pypsa.Network.import_from_excel: "
        f"{len(network.buses)} buses, {len(network.generators)} generators, "
        f"{len(network.loads)} loads, {len(network.lines)} lines, "
        f"{len(network.links)} links, {len(network.storage_units)} storage units, "
        f"{len(network.stores)} stores, {len(network.snapshots)} snapshots."
    )

    # ── Snapshot windowing & downsampling ─────────────────────────────────────
    # The user selects (start, count, weight) in the Run dialog. We keep every
    # `weight`-th snapshot from the [start, start+count) slice and set
    # snapshot_weightings = weight so total energy is preserved.
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

    # Period factor: how much of a full year (8760 h) is modelled, used to
    # scale workbook-supplied annual energy caps (`*_sum_min`, `*_sum_max`)
    # down to the partial window.
    hours_in_year = 8760.0
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
    for class_name, frame in (
        ("Generator", network.generators),
        ("StorageUnit", network.storage_units),
        ("Store", network.stores),
        ("Line", network.lines),
        ("Link", network.links),
    ):
        ext_col = "e_nom_extendable" if class_name == "Store" else "p_nom_extendable" if class_name in ("Generator", "StorageUnit", "Link") else "s_nom_extendable"
        if ext_col not in frame.columns or "capital_cost" not in frame.columns:
            continue
        ext = frame[ext_col].astype(bool)
        if not ext.any():
            continue
        lifetime_col = "lifetime" if "lifetime" in frame.columns else None
        if lifetime_col is None:
            lifetimes = pd.Series(20.0, index=frame.index[ext])
        else:
            lifetimes = frame.loc[ext, lifetime_col].replace(0, pd.NA).fillna(20.0)
        afs = lifetimes.apply(lambda L: annuity_factor(discount_rate, float(L)))
        frame.loc[ext, "capital_cost"] = frame.loc[ext, "capital_cost"].fillna(0.0) * afs
        notes.append(
            f"Annualised CAPEX for {int(ext.sum())} extendable {class_name}(s) "
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

    notes.append(
        f"Prepared PyPSA case with {len(network.buses)} buses, "
        f"{len(network.generators)} generators, {len(network.loads)} loads."
    )
    return network, notes


def _peak_load_per_bus(network: pypsa.Network) -> dict[str, float]:
    """Sum of peak load (across snapshots) at each bus. Used to size the
    load-shedding generator's p_nom uncapped."""
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
