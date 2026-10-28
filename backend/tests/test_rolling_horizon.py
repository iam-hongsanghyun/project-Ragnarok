"""Rolling-horizon correctness.

Regression: storage with ``cyclic_state_of_charge=True`` (the default for the
system BESS) is incompatible with rolling horizon — cyclic forces each window to
return to its starting SOC, which makes the (shorter) trailing window infeasible.
PyPSA then silently leaves that window's results at zero, so the run output was
truncated to the earlier windows. The fix forces non-cyclic storage under rolling
so the carried-over ``state_of_charge_initial`` provides continuity.

Core cleanup step 5 (D10, B1): the builder no longer switches the cyclic flags off silently. A cyclic storage under
rolling horizon is REFUSED with the visible workbook step that writes the flags (``rolling.make_noncyclic``); the
terminal-SOC soft target is an explicit rolling option, default OFF, declared in the run notes; the window and the
overlap are given in hours and converted with the weights the run uses.
"""
from __future__ import annotations

from typing import Any

import pytest
from fastapi import HTTPException

from backend.pypsa.results import run_pypsa
from backend.pypsa.rolling import make_noncyclic, parse_rolling_config, resolve_rolling


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


def test_cyclic_storage_under_rolling_is_refused_with_the_visible_action() -> None:
    options = {
        "snapshotStart": 0, "snapshotCount": 12, "snapshotWeight": 1.0,
        "rollingConfig": {"enabled": True, "horizonSnapshots": 6, "overlapSnapshots": 0},
    }
    with pytest.raises(HTTPException) as err:
        run_pypsa(_model_with_cyclic_storage(), {"discountRate": 0.0, "carbonPrice": 0.0}, options)
    assert err.value.status_code == 400
    detail = str(err.value.detail)
    assert "cyclic_state_of_charge=true" in detail and "Make non-cyclic for rolling" in detail


def test_make_noncyclic_writes_the_flags_and_the_last_window_is_covered() -> None:
    model, changed = make_noncyclic(_model_with_cyclic_storage())
    assert changed == [{"sheet": "storage_units", "name": "S", "attribute": "cyclic_state_of_charge"}]
    assert model["storage_units"][0]["cyclic_state_of_charge"] is False
    assert _model_with_cyclic_storage()["storage_units"][0]["cyclic_state_of_charge"] is True  # input untouched
    options = {
        "snapshotStart": 0, "snapshotCount": 12, "snapshotWeight": 1.0,
        "rollingConfig": {"enabled": True, "horizonSnapshots": 6, "overlapSnapshots": 0},
    }
    result = run_pypsa(model, {"discountRate": 0.0, "carbonPrice": 0.0}, options)
    series = (result.get("outputs") or {}).get("series") or {}
    gp = series.get("generators-p") or []
    assert len(gp) == 12, "all 12 snapshots should be present"
    # The LAST window (snapshots 6–11, load 150 MW) must be served.
    last_window_gen = [float(gp[i].get("G", 0.0)) for i in range(6, 12)]
    assert all(v > 1e-6 for v in last_window_gen), f"last window was truncated: {last_window_gen}"


def test_horizon_and_overlap_are_hours_converted_with_the_run_weights() -> None:
    cfg = parse_rolling_config({"enabled": True, "horizonHours": 24, "overlapHours": 6})
    assert (cfg.horizon_hours, cfg.overlap_hours) == (24.0, 6.0)
    for step, horizon, overlap in ((1.0, 24, 6), (4.0, 6, 2), (0.5, 48, 12), (3.0, 8, 2)):
        r = resolve_rolling(cfg, step)
        assert (r.horizon_snapshots, r.overlap_snapshots) == (horizon, overlap)  # ceil(hours / step)
        assert r.step_snapshots == horizon - overlap
    # an old preset (counts) is unchanged by the weights
    old = parse_rolling_config({"enabled": True, "horizonSnapshots": 12, "overlapSnapshots": 2})
    assert resolve_rolling(old, 4.0) is old
    with pytest.raises(HTTPException):
        parse_rolling_config({"enabled": True, "horizonHours": 6, "overlapHours": 6})


def test_rolling_in_hours_solves_the_expected_number_of_windows() -> None:
    model, _ = make_noncyclic(_model_with_cyclic_storage())
    result = run_pypsa(model, {"discountRate": 0.0, "carbonPrice": 0.0}, {
        "snapshotStart": 0, "snapshotCount": 12, "rollingConfig": {"enabled": True, "horizonHours": 6, "overlapHours": 0},
    })
    roll = result["runMeta"]["rolling"]
    assert (roll["horizonSnapshots"], roll["horizonHours"], roll["windowCount"]) == (6, 6.0, 2)
    assert any("6 h window / 0 h overlap = 6 / 0 snapshots" in n for n in result["narrative"])


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


def test_terminal_soc_is_an_explicit_option_default_off() -> None:
    assert parse_rolling_config({"enabled": True}).terminal_soc is False
    assert parse_rolling_config({"enabled": True, "terminalSoc": True}).terminal_soc is True


def test_terminal_soc_on_keeps_storage_from_draining_and_is_declared() -> None:
    result = _run(_model_flat_load(), terminalSoc=True)
    soc = _soc_series(result)
    assert len(soc) == 12
    assert soc[-1] >= 200.0 - 1e-3, f"storage drained at the end: {soc}"
    assert any("soft terminal SOC target" in n for n in result["narrative"])


def test_terminal_soc_off_by_default_drains_storage_and_says_so() -> None:
    result = _run(_model_flat_load())
    soc = _soc_series(result)
    assert soc[-1] < 1.0, f"expected the drain without a terminal target: {soc}"
    assert any("terminal SOC target off" in n for n in result["narrative"])


def test_terminal_soc_is_soft_when_load_needs_the_energy() -> None:
    """Hard terminal SOC (target 600) is infeasible in the cyclic-storage fixture; the soft one solves."""
    result = _run(make_noncyclic(_model_with_cyclic_storage())[0], terminalSoc=True)
    gp = ((result.get("outputs") or {}).get("series") or {}).get("generators-p") or []
    assert len(gp) == 12
    assert all(float(gp[i].get("G", 0.0)) > 1e-6 for i in range(6, 12))
    soc = _soc_series(result)
    assert soc[-1] < 600.0 - 1.0, "storage must be allowed to fall short of the target when the load needs it"


def test_terminal_soc_options_registered() -> None:
    from backend.app import run_options_reference as ref
    from backend.app.routers import optimise  # noqa: F401  (registers the options)

    paths = ref.documented_paths()
    assert {"options.rollingConfig.terminalSoc", "options.rollingConfig.terminalSocPenalty",
            "options.rollingConfig.horizonHours", "options.rollingConfig.overlapHours"} <= paths
    terminal = next(e for e in ref.all_entries() if e.path == "options.rollingConfig.terminalSoc")
    assert "default OFF" in terminal.meaning
