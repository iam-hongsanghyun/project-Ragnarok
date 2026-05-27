from __future__ import annotations

from collections import defaultdict
from typing import Any

import pypsa
from pyproj import CRS

from ..pypsa_schema import network_runtime_import_fields
from ..utils.coerce import number


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
