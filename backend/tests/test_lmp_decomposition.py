"""LMP decomposition — post-process energy/congestion split, regression tests.

Mirrors test_outage_mc.py's / test_elcc.py's integration style: build a small
model dict, solve via ``run_pypsa``, inspect the ``lmpDecomposition`` payload.
Also calls ``build_lmp_decomposition`` directly on the solved network to
verify the decomposition math with exact arithmetic.
"""
from __future__ import annotations

import warnings
from typing import Any

import numpy as np
import pytest

from backend.pypsa.network import build_network
from backend.pypsa.results import run_pypsa
from backend.pypsa.results.lmp_decomposition import build_lmp_decomposition

SCENARIO = {"discountRate": 0.0, "carbonPrice": 0.0}

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=DeprecationWarning)


def _hourly_snapshots(n_snaps: int) -> list[str]:
    return [f"2025-01-01T{h:02d}:00:00" for h in range(n_snaps)]


def _congested_two_bus_model(n_snaps: int = 3) -> dict[str, list[dict[str, Any]]]:
    """Bus A (cheap, mc=10) feeding bus B (expensive, mc=80) over a tight line.

    Load A=30, B=120; line A-B s_nom=50 binds fully every snapshot (cheap gen
    A can only cover 30 (own load) + 50 (line) = 80 MW at bus B, the rest (40
    MW) must come from bus B's own expensive generator) -> LMP A=10, LMP B=80.
    """
    snaps = _hourly_snapshots(n_snaps)
    return {
        "buses": [{"name": "A", "v_nom": 380.0}, {"name": "B", "v_nom": 380.0}],
        "carriers": [{"name": "gas", "co2_emissions": 0.0}],
        "snapshots": [{"snapshot": s} for s in snaps],
        "generators": [
            {"name": "gA", "bus": "A", "carrier": "gas", "p_nom": 200.0, "marginal_cost": 10.0},
            {"name": "gB", "bus": "B", "carrier": "gas", "p_nom": 200.0, "marginal_cost": 80.0},
        ],
        "lines": [
            {"name": "AB", "bus0": "A", "bus1": "B", "x": 0.1, "s_nom": 50.0},
        ],
        "loads": [
            {"name": "LA", "bus": "A", "p_set": 30.0},
            {"name": "LB", "bus": "B", "p_set": 120.0},
        ],
        "loads-p_set": [
            {"snapshot": s, "LA": 30.0, "LB": 120.0} for s in snaps
        ],
    }


def _uncongested_two_bus_model(n_snaps: int = 2) -> dict[str, list[dict[str, Any]]]:
    """Two buses, identical generator cost, huge line capacity -> single price."""
    snaps = _hourly_snapshots(n_snaps)
    return {
        "buses": [{"name": "A", "v_nom": 380.0}, {"name": "B", "v_nom": 380.0}],
        "carriers": [{"name": "gas", "co2_emissions": 0.0}],
        "snapshots": [{"snapshot": s} for s in snaps],
        "generators": [
            {"name": "gA", "bus": "A", "carrier": "gas", "p_nom": 500.0, "marginal_cost": 25.0},
        ],
        "lines": [
            {"name": "AB", "bus0": "A", "bus1": "B", "x": 0.1, "s_nom": 10_000.0},
        ],
        "loads": [
            {"name": "LA", "bus": "A", "p_set": 40.0},
            {"name": "LB", "bus": "B", "p_set": 60.0},
        ],
        "loads-p_set": [
            {"snapshot": s, "LA": 40.0, "LB": 60.0} for s in snaps
        ],
    }


def _lmp_options(**overrides: Any) -> dict[str, Any]:
    cfg = {"enabled": True}
    cfg.update(overrides)
    return {"currencySymbol": "$", "lmpDecompositionConfig": cfg}


def _solve(model: dict[str, list[dict[str, Any]]]):
    network, _notes = build_network(model, SCENARIO)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=FutureWarning)
        network.optimize(solver_name="highs")
    assert network.is_solved
    return network


# ── Guard cases ──────────────────────────────────────────────────────────────


def test_returns_none_when_unsolved() -> None:
    model = _congested_two_bus_model()
    network, _notes = build_network(model, SCENARIO)
    # never optimized -> no marginal_price
    result = build_lmp_decomposition(network, _lmp_options())
    assert result is None


def test_returns_none_for_single_bus() -> None:
    model = {
        "buses": [{"name": "b0", "v_nom": 380.0}],
        "carriers": [{"name": "gas", "co2_emissions": 0.0}],
        "snapshots": [{"snapshot": "2025-01-01T00:00:00"}],
        "generators": [{"name": "g", "bus": "b0", "carrier": "gas", "p_nom": 100.0, "marginal_cost": 10.0}],
        "loads": [{"name": "L", "bus": "b0", "p_set": 50.0}],
        "loads-p_set": [{"snapshot": "2025-01-01T00:00:00", "L": 50.0}],
    }
    network = _solve(model)
    result = build_lmp_decomposition(network, _lmp_options())
    assert result is None


def test_disabled_config_returns_none_via_run_pypsa() -> None:
    model = _congested_two_bus_model()
    out = run_pypsa(model, SCENARIO, options={"lmpDecompositionConfig": {"enabled": False}})
    assert out["lmpDecomposition"] is None


# ── Congested 2-bus example (the "KEY GROUNDING FACT" example) ──────────────


def test_congested_two_bus_lmp_and_rent() -> None:
    n_snaps = 3
    network = _solve(_congested_two_bus_model(n_snaps=n_snaps))

    lmp = network.buses_t.marginal_price
    np.testing.assert_allclose(lmp["A"].to_numpy(), 10.0, rtol=0, atol=1e-6)
    np.testing.assert_allclose(lmp["B"].to_numpy(), 80.0, rtol=0, atol=1e-6)

    result = build_lmp_decomposition(network, _lmp_options(referenceMode="min"))
    assert result is not None
    assert result["enabled"] is True
    assert result["referenceMode"] == "min"
    assert result["referenceBus"] is None
    assert result["currency"] == "$"
    assert result["unit"] == "$/MWh"

    # congestionRent total ~ 70 * 50 * 3 snapshots (1h weights) = 10500
    np.testing.assert_allclose(result["totals"]["congestionRent"], 10500.0, rtol=1e-6, atol=1e-2)

    bus_by_name = {row["bus"]: row for row in result["buses"]}
    # Under 'min' mode energy_t = min(LMP_A, LMP_B) = 10 -> congestion_B = 80-10=70
    np.testing.assert_allclose(bus_by_name["B"]["congestion"], 70.0, rtol=1e-6, atol=1e-2)
    np.testing.assert_allclose(bus_by_name["A"]["congestion"], 0.0, rtol=1e-6, atol=1e-2)
    np.testing.assert_allclose(bus_by_name["A"]["meanLmp"], 10.0, rtol=1e-6, atol=1e-2)
    np.testing.assert_allclose(bus_by_name["B"]["meanLmp"], 80.0, rtol=1e-6, atol=1e-2)

    # Sorted by congestion desc -> B (congestion 70) before A (congestion 0)
    assert result["buses"][0]["bus"] == "B"

    assert len(result["lines"]) == 1
    line_row = result["lines"][0]
    assert line_row["name"] == "AB"
    assert line_row["kind"] == "line"
    assert line_row["from"] == "A"
    assert line_row["to"] == "B"
    np.testing.assert_allclose(line_row["congestionRent"], 10500.0, rtol=1e-6, atol=1e-2)
    # Line is fully loaded every snapshot (flow == 50 MW == s_nom) -> hoursCongested ~ 3
    np.testing.assert_allclose(line_row["hoursCongested"], float(n_snaps), rtol=1e-6, atol=1e-6)
    np.testing.assert_allclose(line_row["meanAbsFlow"], 50.0, rtol=1e-6, atol=1e-2)
    np.testing.assert_allclose(line_row["sNom"], 50.0, rtol=1e-6, atol=1e-9)
    np.testing.assert_allclose(line_row["utilizationPct"], 100.0, rtol=1e-6, atol=1e-2)

    assert result["series"] is not None
    assert len(result["series"]["snapshots"]) == n_snaps
    np.testing.assert_allclose(result["series"]["congestionRent"], [3500.0] * n_snaps, rtol=1e-6, atol=1e-2)

    assert "copper-plate" not in result["note"].lower()
    assert any("Peak congestion" in row["label"] for row in result["summary"])


def test_run_pypsa_wires_lmp_decomposition() -> None:
    model = _congested_two_bus_model()
    out = run_pypsa(model, SCENARIO, options=_lmp_options())
    result = out["lmpDecomposition"]
    assert result is not None
    np.testing.assert_allclose(result["totals"]["congestionRent"], 10500.0, rtol=1e-6, atol=1e-2)


# ── Reference-mode decomposition: energy + congestion == LMP exactly ────────


@pytest.mark.parametrize("mode", ["load-weighted", "min", "bus"])
def test_energy_plus_congestion_reconstructs_lmp_exactly(mode: str) -> None:
    network = _solve(_congested_two_bus_model(n_snaps=2))
    options = _lmp_options(referenceMode=mode, referenceBus="A" if mode == "bus" else None)
    result = build_lmp_decomposition(network, options)
    assert result is not None

    for row in result["buses"]:
        reconstructed = row["energy"] + row["congestion"]
        np.testing.assert_allclose(reconstructed, row["meanLmp"], rtol=1e-6, atol=1e-6)


def test_load_weighted_mode_matches_documented_formula() -> None:
    network = _solve(_congested_two_bus_model(n_snaps=1))
    result = build_lmp_decomposition(network, _lmp_options(referenceMode="load-weighted"))
    assert result is not None
    # load-weighted energy_t = (30*10 + 120*80) / (30+120) = (300+9600)/150 = 66.0
    expected_energy = (30.0 * 10.0 + 120.0 * 80.0) / 150.0
    np.testing.assert_allclose(result["totals"]["energyPrice"], expected_energy, rtol=1e-6, atol=1e-6)
    bus_by_name = {row["bus"]: row for row in result["buses"]}
    np.testing.assert_allclose(bus_by_name["A"]["congestion"], 10.0 - expected_energy, rtol=1e-6, atol=1e-6)
    np.testing.assert_allclose(bus_by_name["B"]["congestion"], 80.0 - expected_energy, rtol=1e-6, atol=1e-6)


def test_bus_mode_pins_energy_to_reference_bus() -> None:
    network = _solve(_congested_two_bus_model(n_snaps=1))
    result = build_lmp_decomposition(network, _lmp_options(referenceMode="bus", referenceBus="A"))
    assert result is not None
    assert result["referenceMode"] == "bus"
    assert result["referenceBus"] == "A"
    np.testing.assert_allclose(result["totals"]["energyPrice"], 10.0, rtol=1e-6, atol=1e-6)
    bus_by_name = {row["bus"]: row for row in result["buses"]}
    np.testing.assert_allclose(bus_by_name["A"]["congestion"], 0.0, rtol=1e-6, atol=1e-6)
    np.testing.assert_allclose(bus_by_name["B"]["congestion"], 70.0, rtol=1e-6, atol=1e-6)


def test_bus_mode_falls_back_to_load_weighted_when_bus_missing() -> None:
    network = _solve(_congested_two_bus_model(n_snaps=1))
    result = build_lmp_decomposition(network, _lmp_options(referenceMode="bus", referenceBus="does-not-exist"))
    assert result is not None
    assert result["referenceMode"] == "load-weighted"
    assert result["referenceBus"] is None
    expected_energy = (30.0 * 10.0 + 120.0 * 80.0) / 150.0
    np.testing.assert_allclose(result["totals"]["energyPrice"], expected_energy, rtol=1e-6, atol=1e-6)


# ── Copper-plate case ────────────────────────────────────────────────────────


def test_uncongested_network_reports_copperplate_note_and_near_zero_congestion() -> None:
    network = _solve(_uncongested_two_bus_model())
    result = build_lmp_decomposition(network, _lmp_options())
    assert result is not None
    assert "copper-plate" in result["note"].lower()

    for row in result["buses"]:
        np.testing.assert_allclose(row["congestion"], 0.0, rtol=0, atol=1e-6)

    for row in result["lines"]:
        np.testing.assert_allclose(row["congestionRent"], 0.0, rtol=0, atol=1e-6)

    np.testing.assert_allclose(result["totals"]["congestionRent"], 0.0, rtol=0, atol=1e-6)


# ── Review regressions: effective capacity + link efficiency ────────────────


def _lossy_link_model(n_snaps: int = 2, efficiency: float = 0.9) -> dict[str, list[dict[str, Any]]]:
    """Bus A (cheap gen) delivering to bus B ONLY through a lossy Link.

    p_nom is ample so the link never binds thermally: the whole A->B price
    spread (LMP_B = LMP_A / efficiency) is pure conversion loss, so the true
    merchandising surplus a transmission-rights auction would collect is ZERO.
    The pre-fix formula (LMP_B - LMP_A)*p0 would report a fabricated rent.
    """
    snaps = _hourly_snapshots(n_snaps)
    return {
        "buses": [{"name": "A", "v_nom": 380.0}, {"name": "B", "v_nom": 380.0}],
        "carriers": [{"name": "gas", "co2_emissions": 0.0}],
        "snapshots": [{"snapshot": s} for s in snaps],
        "generators": [
            {"name": "gA", "bus": "A", "carrier": "gas", "p_nom": 500.0, "marginal_cost": 10.0},
        ],
        "links": [
            {"name": "AB", "bus0": "A", "bus1": "B", "p_nom": 500.0, "efficiency": efficiency},
        ],
        "loads": [{"name": "LB", "bus": "B", "p_set": 90.0}],
        "loads-p_set": [{"snapshot": s, "LB": 90.0} for s in snaps],
    }


def test_lossy_link_rent_is_efficiency_aware_pure_loss_collects_zero() -> None:
    """A non-binding lossy link's price spread is pure loss -> zero rent."""
    network = _solve(_lossy_link_model(efficiency=0.9))
    result = build_lmp_decomposition(network, _lmp_options())
    assert result is not None

    link_rows = [r for r in result["lines"] if r["kind"] == "link"]
    assert len(link_rows) == 1
    ab = link_rows[0]
    # Efficiency-aware rent = -(LMP_to*p1 + LMP_from*p0) = 0 for pure loss.
    # The buggy (LMP_to - LMP_from)*p0 would report ~ (11.11-10)*100*2h = 222.
    np.testing.assert_allclose(ab["congestionRent"], 0.0, rtol=0, atol=1e-2)
    np.testing.assert_allclose(result["totals"]["congestionRent"], 0.0, rtol=0, atol=1e-2)


def _derated_line_model(n_snaps: int = 3) -> dict[str, list[dict[str, Any]]]:
    """Congested topology but the line is rated s_nom=100 with s_max_pu=0.5, so
    its effective limit is 50 MW and it binds fully (flow=50) every snapshot."""
    model = _congested_two_bus_model(n_snaps)
    model["lines"] = [
        {"name": "AB", "bus0": "A", "bus1": "B", "x": 0.1, "s_nom": 100.0, "s_max_pu": 0.5},
    ]
    return model


def test_derated_line_registers_congested_against_effective_limit() -> None:
    """s_max_pu<1: the line binds at s_nom*s_max_pu, not raw s_nom."""
    network = _solve(_derated_line_model())
    result = build_lmp_decomposition(network, _lmp_options())
    assert result is not None

    ab = next(r for r in result["lines"] if r["name"] == "AB")
    # effective cap = 100 * 0.5 = 50; flow binds at 50 every snapshot.
    np.testing.assert_allclose(ab["sNom"], 50.0, rtol=0, atol=1e-6)
    np.testing.assert_allclose(ab["utilizationPct"], 100.0, rtol=0, atol=0.5)
    assert ab["hoursCongested"] > 0.0  # raw-s_nom (100) cap would give 0
    assert result["totals"]["congestionRent"] > 0.0


def _extendable_line_model(n_snaps: int = 3) -> dict[str, list[dict[str, Any]]]:
    """Congested topology but the tie-line is extendable and cheap to expand, so
    the solver grows s_nom_opt well above the 50 MW nameplate."""
    model = _congested_two_bus_model(n_snaps)
    model["lines"] = [
        {
            "name": "AB", "bus0": "A", "bus1": "B", "x": 0.1, "s_nom": 50.0,
            "s_nom_extendable": True, "capital_cost": 1.0,
        },
    ]
    return model


def test_extendable_line_uses_optimized_capacity_not_nameplate() -> None:
    """Utilization/limit are judged against s_nom_opt, so an expanded line is
    never reported at a nonsensical >100% utilization."""
    network = _solve(_extendable_line_model())
    result = build_lmp_decomposition(network, _lmp_options())
    assert result is not None

    ab = next(r for r in result["lines"] if r["name"] == "AB")
    assert network.lines.at["AB", "s_nom_opt"] > 50.0  # solver actually expanded
    assert ab["sNom"] > 50.0  # reported cap tracks s_nom_opt, not nameplate 50
    # Pre-fix: cap=50 with flow ~120 gives utilizationPct ~240% (absurd).
    assert ab["utilizationPct"] <= 100.5
