"""I4 — weather → renewable capacity-factor conversion (Open-Meteo importer).

Pins the pure conversion maths: solar from GHI, wind from a cubic power curve,
both clipped to a valid [0, 1] availability factor.
"""
from __future__ import annotations

import pytest
from shapely.geometry import box

from backend.app.importers.databases.openmeteo_renewable import build
from backend.app.importers.databases.openmeteo_renewable.conversion import (
    combined_ghi,
    mean_cf,
    solar_cf,
    wind_cf,
)
from backend.app.importers.protocol import ConvertOptions, Database, FetchResult, Region


def _result(techs: list[str]) -> FetchResult:
    region = Region("USA", "United States", box(-120.0, 30.0, -100.0, 40.0))
    payload = {
        "lat": 35.0,
        "lon": -110.0,
        "hourly": {
            "time": ["2023-01-01T00:00", "2023-01-01T01:00", "2023-01-01T02:00"],
            "shortwave_radiation": [0.0, 500.0, 1000.0],
            "wind_speed_100m": [0.0, 12.0, 30.0],
        },
    }
    filters = {"technologies": techs, "capacity_mw": 100.0, "performance_ratio": 0.9}
    return FetchResult("openmeteo_renewable", region, filters, payload)


def test_solar_cf_is_ghi_over_stc_times_pr() -> None:
    assert solar_cf([0.0, 500.0, 1000.0, 1200.0], performance_ratio=1.0) == [0.0, 0.5, 1.0, 1.0]
    # performance ratio scales, then clips
    assert solar_cf([0.0, 500.0, 1000.0], performance_ratio=0.9) == [0.0, 0.45, 0.9]


def test_solar_cf_handles_nan_as_zero() -> None:
    assert solar_cf([float("nan"), 1000.0], performance_ratio=1.0) == [0.0, 1.0]


def test_wind_cf_power_curve_regions() -> None:
    cf = wind_cf([0.0, 3.0, 7.5, 12.0, 20.0, 25.0, 26.0])
    # below cut-in → 0; at cut-in → 0; rated..cut-out → 1; above cut-out → 0
    assert cf[0] == 0.0
    assert cf[1] == 0.0
    assert cf[2] == pytest.approx((7.5**3 - 3.0**3) / (12.0**3 - 3.0**3), abs=1e-6)
    assert cf[3] == 1.0   # rated
    assert cf[4] == 1.0   # within rated..cut-out
    assert cf[5] == 1.0   # at cut-out
    assert cf[6] == 0.0   # above cut-out


def test_wind_cf_is_monotonic_on_the_ramp() -> None:
    ramp = wind_cf([3.0, 5.0, 7.0, 9.0, 11.0, 12.0])
    assert ramp == sorted(ramp)
    assert all(0.0 <= x <= 1.0 for x in ramp)


def test_mean_cf() -> None:
    assert mean_cf([0.0, 0.5, 1.0, 1.0]) == pytest.approx(0.625)
    assert mean_cf([]) == 0.0


def test_combined_ghi_fallback_chain() -> None:
    # prefer shortwave (total horizontal) when present
    assert combined_ghi([100.0, 200.0], [1.0, 2.0], [3.0, 4.0]) == [100.0, 200.0]
    # shortwave null → direct + diffuse
    assert combined_ghi([None, None], [10.0, 20.0], [5.0, 5.0]) == [15.0, 25.0]
    # only direct present → direct alone
    assert combined_ghi([None], [40.0], [None]) == [40.0]
    # nothing → 0
    assert combined_ghi([None], [None], [None]) == [0.0]


# ── to_sheets: a complete, runnable renewable fragment ──────────────────────────
def test_to_sheets_builds_runnable_renewable_fragment() -> None:
    frag = build().to_sheets(_result(["solar", "wind"]), ConvertOptions())
    assert set(frag.sheets) == {"carriers", "buses", "generators", "generators-p_max_pu"}

    # One bus at the region point; a solar + wind generator on it.
    assert [b["name"] for b in frag.sheets["buses"]] == ["re_USA"]
    gens = {g["name"]: g for g in frag.sheets["generators"]}
    assert set(gens) == {"solar_USA", "wind_USA"}
    assert gens["solar_USA"]["bus"] == "re_USA" and gens["solar_USA"]["carrier"] == "solar"
    assert gens["wind_USA"]["p_nom"] == 100.0

    # Carriers include the electricity bus carrier + the two techs.
    assert {c["name"] for c in frag.sheets["carriers"]} == {"AC", "solar", "wind"}

    # p_max_pu series match the conversion (solar PR=0.9; wind curve).
    rows = frag.sheets["generators-p_max_pu"]
    assert [r["snapshot"] for r in rows] == ["2023-01-01 00:00", "2023-01-01 01:00", "2023-01-01 02:00"]
    assert [r["solar_USA"] for r in rows] == [0.0, 0.45, 0.9]
    assert [r["wind_USA"] for r in rows] == [0.0, 1.0, 0.0]  # 0<cut-in, 12=rated, 30>cut-out
    assert frag.snapshots == [r["snapshot"] for r in rows]
    assert frag.provenance is not None


def test_to_sheets_respects_technology_selection() -> None:
    frag = build().to_sheets(_result(["solar"]), ConvertOptions())
    assert [g["name"] for g in frag.sheets["generators"]] == ["solar_USA"]
    assert all("wind_USA" not in r for r in frag.sheets["generators-p_max_pu"])


def test_module_conforms_to_database_protocol() -> None:
    db = build()
    assert isinstance(db, Database)
    assert db.meta.id == "openmeteo_renewable"
    assert not db.meta.requires_secrets  # keyless
