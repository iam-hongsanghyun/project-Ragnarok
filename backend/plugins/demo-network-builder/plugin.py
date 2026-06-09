"""Demo Network Builder — a reference backend plugin.

Demonstrates the backend-plugin contract: a server-side ``build(config)`` that
imports the bundled PyPSA source directly (``backend.pypsa``) to construct a real
``pypsa.Network``, then returns the model dict for the session. Nothing runs in
the browser and there is no separate server / ``plugins.env`` entry.

Algorithm:
    Daily load shape on each bus over ``H`` hourly snapshots::

        $$ P_i(t) = P_\\text{peak} \\cdot \\left(0.6 + 0.4\\,\\sin\\!\\frac{2\\pi t}{24}\\right) $$

    ASCII: load(t) = peak * (0.6 + 0.4 * sin(2*pi*t/24)), clipped at >= 0.
    Symbols: P_peak = peak load per bus [MW]; t = hour index [h]; H = snapshot
    count [h]; one generator per bus sized at 1.5 * P_peak [MW].
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Any


def _num(config: dict[str, Any], key: str, default: float) -> float:
    try:
        return float(config.get(key, default))
    except (TypeError, ValueError):
        return float(default)


def build(config: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Build a small valid model dict; validate it by constructing the network
    with the bundled PyPSA source.

    Args:
        config: ``{buses:int, snapshots:int, peak_load_mw:float, carrier:str}``.

    Returns:
        A model dict ``{sheet: [rows]}`` ready for the session store.
    """
    n_buses = max(1, int(_num(config, "buses", 1)))
    n_snaps = max(1, int(_num(config, "snapshots", 24)))
    peak = _num(config, "peak_load_mw", 100.0)
    carrier = str(config.get("carrier") or "gas")

    start = datetime(2030, 1, 1)
    snaps = [(start + timedelta(hours=t)).strftime("%Y-%m-%dT%H:%M:%S") for t in range(n_snaps)]
    load_at = [max(0.0, peak * (0.6 + 0.4 * math.sin(2.0 * math.pi * t / 24.0))) for t in range(n_snaps)]

    buses = [{"name": f"bus{i}"} for i in range(n_buses)]
    loads = [{"name": f"load{i}", "bus": f"bus{i}", "p_set": peak} for i in range(n_buses)]
    generators = [
        {
            "name": f"gen{i}",
            "bus": f"bus{i}",
            "carrier": carrier,
            "p_nom": round(1.5 * peak, 3),
            "marginal_cost": 50.0,
        }
        for i in range(n_buses)
    ]
    # Per-snapshot load table: one column per load, value identical across buses.
    loads_p_set = [
        {"snapshot": snaps[t], **{f"load{i}": round(load_at[t], 3) for i in range(n_buses)}}
        for t in range(n_snaps)
    ]

    model: dict[str, list[dict[str, Any]]] = {
        "buses": buses,
        "carriers": [{"name": carrier}],
        "snapshots": [{"snapshot": s} for s in snaps],
        "loads": loads,
        "loads-p_set": loads_p_set,
        "generators": generators,
    }

    # Use the bundled PyPSA source directly to construct (and thereby validate)
    # the network in-process. We discard the Network and return the model dict —
    # the session stores the editable model, not the solved object.
    from backend.pypsa.network import build_network

    _network, _warnings = build_network(model, {"discountRate": 0.0, "carbonPrice": 0.0}, None)
    return model
