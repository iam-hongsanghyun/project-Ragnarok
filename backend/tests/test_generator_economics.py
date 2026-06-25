"""Math tests for build_generator_economics (F0).

The network is constructed and its result frames are set by hand (no solve), so
every figure can be checked against an analytical value. Weights are chosen so
the modeled horizon is exactly one year (Σ w = 8760 h), making capex recovery
land on the native annual basis.
"""

from __future__ import annotations

import pandas as pd
import pypsa
import pytest

from backend.pypsa.network import build_network
from backend.pypsa.results.market import build_generator_economics


@pytest.fixture
def solved_network() -> pypsa.Network:
    n = pypsa.Network()
    n.set_snapshots(pd.date_range("2025-01-01", periods=2, freq="h"))
    # Two snapshots, each representing half a year → full-year horizon.
    n.snapshot_weightings.loc[:, :] = 4380.0

    n.add("Bus", "b")
    for c in ("coal", "gas", "battery"):
        n.add("Carrier", c)

    # g1: cheap baseload, no capital cost (recovery undefined).
    n.add("Generator", "g1", bus="b", carrier="coal", marginal_cost=20.0, p_nom=100.0)
    # g2: peaker, extendable with a known annual fixed cost.
    n.add(
        "Generator",
        "g2",
        bus="b",
        carrier="gas",
        marginal_cost=50.0,
        p_nom=0.0,
        p_nom_extendable=True,
        capital_cost=1000.0,
    )
    # System backstop — must be excluded from the economics.
    n.add(
        "Generator",
        "load_shedding_b",
        bus="b",
        carrier="coal",
        marginal_cost=9999.0,
        p_nom=1000.0,
    )

    n.add(
        "StorageUnit", "su1", bus="b", carrier="battery", marginal_cost=0.0, p_nom=100.0
    )

    # Solved capacity for the extendable peaker.
    n.generators.loc["g2", "p_nom_opt"] = 50.0

    # Hand-set dispatch + LMPs.
    n.generators_t["p"] = pd.DataFrame(
        {"g1": [100.0, 80.0], "g2": [0.0, 50.0], "load_shedding_b": [0.0, 0.0]},
        index=n.snapshots,
    )
    n.storage_units_t["p"] = pd.DataFrame({"su1": [-100.0, 90.0]}, index=n.snapshots)
    n.buses_t["marginal_price"] = pd.DataFrame({"b": [30.0, 60.0]}, index=n.snapshots)
    return n


def test_horizon_and_currency(solved_network):
    econ = build_generator_economics(solved_network, currency="€")
    assert econ["currency"] == "€"
    assert econ["modeledHours"] == 8760.0
    assert econ["horizonYears"] == 1.0


def test_system_generators_excluded(solved_network):
    econ = build_generator_economics(solved_network)
    names = {g["name"] for g in econ["generators"]}
    assert names == {"g1", "g2"}
    assert econ["system"]["generatorsModeled"] == 2


def test_generator_revenue_margin_capture(solved_network):
    econ = build_generator_economics(solved_network)
    g = {row["name"]: row for row in econ["generators"]}

    # g1: energy = 4380*(100+80) = 788_400 MWh
    #     revenue = 4380*(30*100 + 60*80) = 34_164_000
    #     varcost = 4380*(20*100 + 20*80) = 15_768_000
    assert g["g1"]["energyMwh"] == 788_400.0
    assert g["g1"]["revenue"] == 34_164_000
    assert g["g1"]["variableCost"] == 15_768_000
    assert g["g1"]["grossMargin"] == 18_396_000
    assert g["g1"]["capturePrice"] == pytest.approx(43.33, abs=0.01)
    assert g["g1"]["capacityMw"] == 100.0  # p_nom fallback (no p_nom_opt)
    assert g["g1"]["fixedCostAnnual"] == 0
    assert g["g1"]["recoveryPct"] is None  # no fixed cost → undefined

    # g2: only dispatches at t1 (price 60). revenue = 4380*60*50 = 13_140_000
    #     varcost = 4380*50*50 = 10_950_000 ; margin = 2_190_000
    #     fixed = 1000 * 50 * (8760/8760) = 50_000
    assert g["g2"]["revenue"] == 13_140_000
    assert g["g2"]["grossMargin"] == 2_190_000
    assert g["g2"]["capturePrice"] == pytest.approx(60.0)
    assert g["g2"]["fixedCostAnnual"] == 50_000
    assert g["g2"]["fixedCostHorizon"] == 50_000
    assert g["g2"]["netHorizon"] == 2_140_000
    assert g["g2"]["recoveryPct"] == pytest.approx(4380.0)


def test_storage_arbitrage(solved_network):
    econ = build_generator_economics(solved_network)
    assert len(econ["storage"]) == 1
    su = econ["storage"][0]
    # revenue = 4380*30*(-100) + 4380*60*90 = -13_140_000 + 23_652_000 = 10_512_000
    assert su["energyChargedMwh"] == 438_000.0
    assert su["energyDischargedMwh"] == 394_200.0
    assert su["revenue"] == 10_512_000
    assert su["grossMargin"] == 10_512_000  # marginal_cost 0


def test_by_carrier_and_system_totals(solved_network):
    econ = build_generator_economics(solved_network)
    by_carrier = {row["carrier"]: row for row in econ["byCarrier"]}
    assert set(by_carrier) == {"coal", "gas"}  # load_shedding excluded from coal
    assert by_carrier["coal"]["grossMargin"] == 18_396_000
    assert by_carrier["gas"]["grossMargin"] == 2_190_000
    # Sorted by gross margin descending.
    assert econ["byCarrier"][0]["carrier"] == "coal"

    system = econ["system"]
    assert system["grossMargin"] == 18_396_000 + 2_190_000
    assert system["fixedCostHorizon"] == 50_000
    assert system["recoveryPct"] == pytest.approx(41172.0)
    assert system["generatorsRecovered"] == 1  # only g2 clears 100%


def test_no_prices_yields_zero_revenue(solved_network):
    # Drop the LMP frame → revenue collapses to zero, margins go negative by cost.
    solved_network.buses_t["marginal_price"] = pd.DataFrame(
        index=solved_network.snapshots
    )
    econ = build_generator_economics(solved_network)
    g = {row["name"]: row for row in econ["generators"]}
    assert g["g1"]["revenue"] == 0
    assert g["g1"]["grossMargin"] == -15_768_000
    assert g["g1"]["capturePrice"] == 0.0


def test_end_to_end_marginal_generator_earns_zero_margin():
    """Real solve (HiGHS): with spare gas capacity, the LMP equals gas's marginal
    cost, so the marginal unit's gross margin is zero — the textbook result, and a
    strong check that revenue uses the real nodal duals, not a proxy."""
    snaps = [f"2030-01-01T{h:02d}:00:00" for h in range(6)]
    model = {
        "buses": [{"name": "b"}],
        "carriers": [{"name": "gas"}, {"name": "backup"}],
        "snapshots": [{"snapshot": s} for s in snaps],
        "loads": [{"name": "L", "bus": "b", "p_set": 100.0}],
        "loads-p_set": [{"snapshot": s, "L": 100.0} for s in snaps],
        "generators": [
            {
                "name": "G_gas",
                "bus": "b",
                "carrier": "gas",
                "p_nom": 200.0,
                "marginal_cost": 10.0,
            },
            {
                "name": "G_backup",
                "bus": "b",
                "carrier": "backup",
                "p_nom": 200.0,
                "marginal_cost": 100.0,
            },
        ],
    }
    network, _ = build_network(model, {"discountRate": 0.0, "carbonPrice": 0.0}, {})
    network.optimize(solver_name="highs")

    econ = build_generator_economics(network)
    g = {row["name"]: row for row in econ["generators"]}
    assert g["G_gas"]["energyMwh"] == pytest.approx(600.0)  # 6 h × 100 MW
    assert g["G_gas"]["capturePrice"] == pytest.approx(10.0, abs=0.01)  # LMP = gas mc
    assert g["G_gas"]["grossMargin"] == pytest.approx(
        0.0, abs=1.0
    )  # marginal ⇒ zero margin
    assert g["G_backup"]["energyMwh"] == pytest.approx(0.0)  # never dispatched
