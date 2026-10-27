"""Rolling-horizon correctness.

Regression: storage with ``cyclic_state_of_charge=True`` (the default for the
system BESS) is incompatible with rolling horizon — cyclic forces each window to
return to its starting SOC, which makes the (shorter) trailing window infeasible.
PyPSA then silently leaves that window's results at zero, so the run output was
truncated to the earlier windows. The fix forces non-cyclic storage under rolling
so the carried-over ``state_of_charge_initial`` provides continuity.
"""
from __future__ import annotations

from typing import Any

from backend.pypsa.results import run_pypsa


def _model_with_cyclic_storage() -> dict[str, list[dict[str, Any]]]:
    """1 bus; load 50 MW for the first window, 150 MW for the second. The gas
    generator caps at 100 MW, so the high second window can only be served by
    discharging storage charged earlier — which cyclic SOC forbids."""
    snaps = [f"2030-01-01T{h:02d}:00:00" for h in range(12)]
    load = [50.0] * 6 + [150.0] * 6
    return {
        "buses": [{"name": "b"}],
        "carriers": [{"name": "gas"}, {"name": "store"}],
        "snapshots": [{"snapshot": s} for s in snaps],
        "loads": [{"name": "L", "bus": "b", "p_set": 100.0}],
        "loads-p_set": [{"snapshot": snaps[i], "L": load[i]} for i in range(12)],
        "generators": [{"name": "G", "bus": "b", "carrier": "gas", "p_nom": 100.0, "marginal_cost": 10.0}],
        "storage_units": [{
            "name": "S", "bus": "b", "carrier": "store", "p_nom": 100.0, "max_hours": 6.0,
            "efficiency_store": 1.0, "efficiency_dispatch": 1.0,
            "state_of_charge_initial": 600.0, "cyclic_state_of_charge": True, "marginal_cost": 0.1,
        }],
    }


def test_rolling_horizon_covers_last_window_with_cyclic_storage() -> None:
    options = {
        "snapshotStart": 0, "snapshotCount": 12, "snapshotWeight": 1.0,
        "rollingConfig": {"enabled": True, "horizonSnapshots": 6, "overlapSnapshots": 0},
    }
    result = run_pypsa(_model_with_cyclic_storage(), {"discountRate": 0.0, "carbonPrice": 0.0}, options)

    series = (result.get("outputs") or {}).get("series") or {}
    gp = series.get("generators-p") or []
    assert len(gp) == 12, "all 12 snapshots should be present"

    # The LAST window (snapshots 6–11, load 150 MW) must be served — pre-fix the
    # cyclic constraint made it infeasible and PyPSA left these at zero.
    last_window_gen = [float(gp[i].get("G", 0.0)) for i in range(6, 12)]
    assert all(v > 1e-6 for v in last_window_gen), f"last window was truncated: {last_window_gen}"


# ── RE7: soft terminal SOC on the last window ────────────────────────────────


def _model_flat_load(soc_initial: float = 200.0) -> dict[str, list[dict[str, Any]]]:
    """Flat 60 MW load, gas 10/MWh (cap 100), storage discharging at 0.1/MWh: with no terminal
    condition the storage dumps its whole 200 MWh because that is cheaper than gas."""
    snaps = [f"2030-01-01T{h:02d}:00:00" for h in range(12)]
    return {
        "buses": [{"name": "b"}],
        "carriers": [{"name": "gas"}, {"name": "store"}],
        "snapshots": [{"snapshot": s} for s in snaps],
        "loads": [{"name": "L", "bus": "b", "p_set": 60.0}],
        "generators": [{"name": "G", "bus": "b", "carrier": "gas", "p_nom": 100.0, "marginal_cost": 10.0}],
        "storage_units": [{
            "name": "S", "bus": "b", "carrier": "store", "p_nom": 50.0, "max_hours": 6.0,
            "efficiency_store": 1.0, "efficiency_dispatch": 1.0,
            "state_of_charge_initial": soc_initial, "cyclic_state_of_charge": False, "marginal_cost": 0.1,
        }],
    }


def _run(model: dict, **rolling: Any) -> dict:
    options = {
        "snapshotStart": 0, "snapshotCount": 12, "snapshotWeight": 1.0,
        "rollingConfig": {"enabled": True, "horizonSnapshots": 6, "overlapSnapshots": 0, **rolling},
    }
    return run_pypsa(model, {"discountRate": 0.0, "carbonPrice": 0.0}, options)


def _soc_series(result: dict) -> list[float]:
    series = (result.get("outputs") or {}).get("series") or {}
    rows = series.get("storage_units-state_of_charge") or []
    return [float(r.get("S", 0.0)) for r in rows]


def test_terminal_soc_default_keeps_storage_from_draining() -> None:
    soc = _soc_series(_run(_model_flat_load()))
    assert len(soc) == 12
    assert soc[-1] >= 200.0 - 1e-3, f"storage drained at the end: {soc}"


def test_terminal_soc_off_drains_storage() -> None:
    soc = _soc_series(_run(_model_flat_load(), terminalSoc=False))
    assert soc[-1] < 1.0, f"expected the old drain behaviour: {soc}"


def test_terminal_soc_is_soft_when_load_needs_the_energy() -> None:
    """Hard terminal SOC (target 600) is infeasible in the cyclic-storage fixture; the soft one solves."""
    result = _run(_model_with_cyclic_storage())
    gp = ((result.get("outputs") or {}).get("series") or {}).get("generators-p") or []
    assert len(gp) == 12
    assert all(float(gp[i].get("G", 0.0)) > 1e-6 for i in range(6, 12))
    soc = _soc_series(result)
    assert soc[-1] < 600.0 - 1.0, "storage must be allowed to fall short of the target when the load needs it"


def test_terminal_soc_options_registered() -> None:
    from backend.app import run_options_reference as ref
    from backend.app.routers import optimise  # noqa: F401  (registers the options)

    paths = {e.path for e in ref.EXTRA_OPTIONS}
    assert {"options.rollingConfig.terminalSoc", "options.rollingConfig.terminalSocPenalty"} <= paths
