"""Carrier-aware electricity dispatch mix for sector-coupled models (M1).

``electricity_dispatch_by_carrier`` must show a conversion Link's electricity
output under the Link's carrier (e.g. CCGT), exclude the fuel-supply generator
that sits on the gas bus, and leave single-carrier models exactly as they were.
"""
from __future__ import annotations

import pandas as pd
import pypsa

from backend.pypsa.results.dispatch import (
    dispatch_by_carrier,
    electricity_dispatch_by_carrier,
)


def _sector_network() -> pypsa.Network:
    """elec bus fed by wind (40 MW) + a CCGT Link burning gas (η=0.5 → 60 MW).

    Gas is produced by a supply generator on the gas bus. Load = 100 MW.
    """
    n = pypsa.Network()
    n.set_snapshots(pd.date_range("2030-01-01", periods=2, freq="h"))
    n.add("Bus", "elec", carrier="AC")
    n.add("Bus", "gas", carrier="gas")
    n.add("Carrier", "gas", co2_emissions=0.2)
    n.add("Carrier", "CCGT")
    n.add("Carrier", "wind")
    n.add("Generator", "gas_supply", bus="gas", carrier="gas", p_nom=1000)
    n.add("Generator", "wind", bus="elec", carrier="wind", p_nom=100)
    n.add("Load", "d", bus="elec", p_set=100)
    n.add("Link", "ccgt", bus0="gas", bus1="elec", carrier="CCGT", efficiency=0.5, p_nom=200)
    # Dispatch (no solve): wind 40, gas burned 120 → CCGT electricity 60.
    n.generators_t.p = pd.DataFrame({"gas_supply": [120.0, 120.0], "wind": [40.0, 40.0]}, index=n.snapshots)
    n.links_t.p0 = pd.DataFrame({"ccgt": [120.0, 120.0]}, index=n.snapshots)
    return n


def test_conversion_link_power_shows_under_its_carrier() -> None:
    n = _sector_network()
    mix = electricity_dispatch_by_carrier(n, n.generators_t.p)
    # CCGT electricity output (120 gas × 0.5) is attributed to the CCGT carrier.
    assert set(mix) == {"wind", "CCGT"}
    assert mix["CCGT"].tolist() == [60.0, 60.0]
    assert mix["wind"].tolist() == [40.0, 40.0]
    # The gas fuel-supply generator is NOT lumped into the electricity mix.
    assert "gas" not in mix
    # Supply matches demand (40 wind + 60 CCGT = 100 load).
    assert (mix["wind"] + mix["CCGT"]).tolist() == [100.0, 100.0]


def test_transmission_link_between_electricity_buses_is_not_supply() -> None:
    n = pypsa.Network()
    n.set_snapshots(pd.date_range("2030-01-01", periods=2, freq="h"))
    n.add("Bus", "a", carrier="AC")
    n.add("Bus", "b", carrier="AC")
    n.add("Carrier", "wind")
    n.add("Generator", "w", bus="a", carrier="wind", p_nom=100)
    n.add("Link", "hvdc", bus0="a", bus1="b", carrier="DC", efficiency=0.98, p_nom=100)
    n.generators_t.p = pd.DataFrame({"w": [50.0, 50.0]}, index=n.snapshots)
    n.links_t.p0 = pd.DataFrame({"hvdc": [30.0, 30.0]}, index=n.snapshots)
    mix = electricity_dispatch_by_carrier(n, n.generators_t.p)
    # An elec→elec link is transmission, not generation — no "DC" supply slice.
    assert set(mix) == {"wind"}
    assert mix["wind"].tolist() == [50.0, 50.0]


def test_single_carrier_model_is_unchanged() -> None:
    n = pypsa.Network()
    n.set_snapshots(pd.date_range("2030-01-01", periods=2, freq="h"))
    n.add("Bus", "elec", carrier="AC")
    n.add("Carrier", "wind")
    n.add("Carrier", "gas")
    n.add("Generator", "w", bus="elec", carrier="wind", p_nom=100)
    n.add("Generator", "g", bus="elec", carrier="gas", p_nom=100)
    n.generators_t.p = pd.DataFrame({"w": [40.0, 40.0], "g": [60.0, 60.0]}, index=n.snapshots)
    new = electricity_dispatch_by_carrier(n, n.generators_t.p)
    old = dispatch_by_carrier(n.generators_t.p, n.generators)
    assert set(new) == set(old)
    for carrier in old:
        assert new[carrier].tolist() == old[carrier].tolist()
