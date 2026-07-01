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


def _point(lat: float = 35.0, lon: float = -110.0) -> dict:
    # ghi is pre-computed by fetch.fetch_point (combined_ghi); to_sheets consumes it.
    return {
        "lat": lat, "lon": lon,
        "time": ["2023-01-01T00:00", "2023-01-01T01:00", "2023-01-01T02:00"],
        "ghi": [0.0, 500.0, 1000.0],
        "wind_ms": [0.0, 12.0, 30.0],
    }


def _result(techs: list[str], points: list[dict] | None = None) -> FetchResult:
    region = Region("USA", "United States", box(-120.0, 30.0, -100.0, 40.0))
    filters = {"technologies": techs, "capacity_mw": 100.0, "performance_ratio": 0.9}
    return FetchResult(
        "openmeteo_renewable", region, filters, {"points": points or [_point()]}
    )


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

    # One bus at the region point; a solar + wind generator on it. Names carry
    # the source tag (``om`` = Open-Meteo) so grouped providers can't collide.
    assert [b["name"] for b in frag.sheets["buses"]] == ["re_USA_om"]
    gens = {g["name"]: g for g in frag.sheets["generators"]}
    assert set(gens) == {"solar_USA_om", "wind_USA_om"}
    assert gens["solar_USA_om"]["bus"] == "re_USA_om" and gens["solar_USA_om"]["carrier"] == "solar"
    assert gens["wind_USA_om"]["p_nom"] == 100.0

    # Carriers include the electricity bus carrier + the two techs.
    assert {c["name"] for c in frag.sheets["carriers"]} == {"AC", "solar", "wind"}

    # p_max_pu series match the conversion (solar PR=0.9; wind curve).
    rows = frag.sheets["generators-p_max_pu"]
    assert [r["snapshot"] for r in rows] == ["2023-01-01 00:00", "2023-01-01 01:00", "2023-01-01 02:00"]
    assert [r["solar_USA_om"] for r in rows] == [0.0, 0.45, 0.9]
    assert [r["wind_USA_om"] for r in rows] == [0.0, 1.0, 0.0]  # 0<cut-in, 12=rated, 30>cut-out
    assert frag.snapshots == [r["snapshot"] for r in rows]
    assert frag.provenance is not None


def test_to_sheets_respects_technology_selection() -> None:
    frag = build().to_sheets(_result(["solar"]), ConvertOptions())
    assert [g["name"] for g in frag.sheets["generators"]] == ["solar_USA_om"]
    assert all("wind_USA_om" not in r for r in frag.sheets["generators-p_max_pu"])


def test_to_sheets_multi_point_creates_a_site_per_point() -> None:
    pts = [_point(35.0, -110.0), _point(38.0, -105.0)]
    frag = build().to_sheets(_result(["solar", "wind"], pts), ConvertOptions())
    assert {b["name"] for b in frag.sheets["buses"]} == {"re_USA_om_1", "re_USA_om_2"}
    assert {g["name"] for g in frag.sheets["generators"]} == {
        "solar_USA_om_1", "wind_USA_om_1", "solar_USA_om_2", "wind_USA_om_2"
    }
    # each site's generators sit on its own bus at its own coordinate
    g2 = {g["name"]: g for g in frag.sheets["generators"]}
    assert g2["solar_USA_om_2"]["bus"] == "re_USA_om_2" and g2["solar_USA_om_2"]["y"] == 38.0
    # one shared snapshot axis; every generator has a column
    row0 = frag.sheets["generators-p_max_pu"][0]
    assert {"solar_USA_om_1", "wind_USA_om_1", "solar_USA_om_2", "wind_USA_om_2"} <= set(row0)


def test_to_sheets_applies_utc_offset_to_snapshots() -> None:
    """utc_offset shifts snapshot labels from UTC to local time so the diurnal
    profile lines up with local demand (e.g. +9 for Korea)."""
    result = _result(["solar"])
    result.filters["utc_offset"] = 9
    frag = build().to_sheets(result, ConvertOptions())
    assert [r["snapshot"] for r in frag.sheets["generators-p_max_pu"]] == [
        "2023-01-01 09:00", "2023-01-01 10:00", "2023-01-01 11:00"
    ]


def test_pvgis_and_nasa_are_distinct_datasets_of_one_source() -> None:
    from backend.app.importers.databases.openmeteo_renewable import (
        build_nasa_power,
        build_pvgis,
    )

    om, pvgis_db, nasa = build(), build_pvgis(), build_nasa_power()
    # Three datasets, one shared source group.
    assert {om.meta.id, pvgis_db.meta.id, nasa.meta.id} == {
        "openmeteo_renewable", "pvgis_renewable", "nasa_power_renewable"
    }
    assert om.meta.source_id == pvgis_db.meta.source_id == nasa.meta.source_id
    # Source-tagged names keep multi-selected providers from colliding.
    pv_gens = {g["name"] for g in pvgis_db.to_sheets(_result(["solar"]), ConvertOptions()).sheets["generators"]}
    assert pv_gens == {"solar_USA_pvgis"}


def test_module_conforms_to_database_protocol() -> None:
    db = build()
    assert isinstance(db, Database)
    assert db.meta.id == "openmeteo_renewable"
    assert not db.meta.requires_secrets  # keyless


# ── attach-to-fleet transform logic ─────────────────────────────────────────────
def test_resolve_targets_uses_gen_then_bus_coord_and_skips_non_renewable() -> None:
    from backend.app.importers.databases.openmeteo_renewable.attach import (
        classify,
        resolve_targets,
    )
    assert classify("solar") == "solar" and classify("onwind") == "wind" and classify("gas") is None

    model = {
        "buses": [
            {"name": "b1", "x": 127.0, "y": 37.5},   # gives wind1 its coord
            {"name": "b2"},                            # no coords
        ],
        "generators": [
            {"name": "solar1", "carrier": "solar", "bus": "b2", "x": 10.0, "y": 20.0},  # own coord
            {"name": "wind1", "carrier": "onwind", "bus": "b1"},                          # bus coord
            {"name": "gas1", "carrier": "gas", "bus": "b1"},                              # not renewable
            {"name": "solar2", "carrier": "solar", "bus": "b2"},                          # no coord → skipped
        ],
    }
    targets, skipped = resolve_targets(model)
    by = {t[0]: t for t in targets}
    assert set(by) == {"solar1", "wind1"}
    assert by["solar1"][1:] == ("solar", 20.0, 10.0)   # (kind, lat, lon) from own x/y
    assert by["wind1"][1:] == ("wind", 37.5, 127.0)    # inherited from bus b1
    assert skipped == ["solar2"]


def test_build_profile_rows_attaches_cf_per_generator() -> None:
    from backend.app.importers.databases.openmeteo_renewable.attach import (
        build_profile_rows,
        point_key,
    )
    targets = [("solar1", "solar", 20.0, 10.0), ("wind1", "wind", 37.5, 127.0)]
    point_by_key = {
        point_key(20.0, 10.0): {"time": ["2022-01-01T00:00", "2022-01-01T01:00"], "ghi": [1000.0, 0.0], "wind_ms": [0.0, 0.0]},
        point_key(37.5, 127.0): {"time": ["2022-01-01T00:00", "2022-01-01T01:00"], "ghi": [0.0, 0.0], "wind_ms": [12.0, 0.0]},
    }
    rows, snapshots, attached = build_profile_rows(targets, point_by_key, performance_ratio=0.9)
    assert set(attached) == {"solar1", "wind1"}
    assert snapshots == ["2022-01-01 00:00", "2022-01-01 01:00"]
    assert rows[0]["solar1"] == 0.9   # GHI 1000 × PR 0.9
    assert rows[0]["wind1"] == 1.0    # 12 m/s = rated
    assert rows[1]["solar1"] == 0.0 and rows[1]["wind1"] == 0.0


def test_merge_profile_rows_unions_by_snapshot_new_cols_win() -> None:
    from backend.app.importers.databases.openmeteo_renewable.attach import merge_profile_rows
    existing = [{"snapshot": "2022-01-01 00:00", "wind_old": 0.5}]
    new = [
        {"snapshot": "2022-01-01 00:00", "solar1": 0.9},
        {"snapshot": "2022-01-01 01:00", "solar1": 0.3},
    ]
    merged = merge_profile_rows(existing, new)
    assert [r["snapshot"] for r in merged] == ["2022-01-01 00:00", "2022-01-01 01:00"]
    assert merged[0] == {"snapshot": "2022-01-01 00:00", "wind_old": 0.5, "solar1": 0.9}
    assert merged[1] == {"snapshot": "2022-01-01 01:00", "solar1": 0.3}


# ── source adapters (offline parsing) ──────────────────────────────────────────
class _FakeHttp:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    async def get_json(self, url: str, params: dict | None = None) -> dict:
        return self.payload


def test_pvgis_adapter_parses_time_ghi_wind() -> None:
    import asyncio

    from backend.app.importers.databases.openmeteo_renewable.sources import pvgis

    payload = {"outputs": {"hourly": [
        {"time": "20180101:0010", "Gb(i)": 100.0, "Gd(i)": 50.0, "Gr(i)": 0.0, "WS10m": 10.0},
        {"time": "20180101:0110", "Gb(i)": 0.0, "Gd(i)": 0.0, "Gr(i)": 0.0, "WS10m": 0.0},
    ]}}
    r = asyncio.run(pvgis(_FakeHttp(payload), 45.0, 8.0, "2018-01-01", "2018-01-01", None))
    assert r["time"] == ["2018-01-01 00:00", "2018-01-01 01:00"]
    assert r["ghi"] == [150.0, 0.0]                       # Gb + Gd + Gr
    assert r["wind_ms"][0] == pytest.approx(10.0 * (10.0 ** (1 / 7)), rel=1e-3)  # 10m → 100m


def test_pvgis_clamps_out_of_range_year_and_restamps() -> None:
    """Requesting 2022 (out of PVGIS's 2005–2020 range) fetches the nearest
    available year and re-stamps the timestamps back to 2022 so snapshots match
    the requested window — instead of the raw 400 the API returns."""
    import asyncio

    from backend.app.importers.databases.openmeteo_renewable.sources import pvgis

    # A real fetch would return 2020 data (the clamped year); re-stamp → 2022.
    payload = {"outputs": {"hourly": [
        {"time": "20200101:0010", "Gb(i)": 200.0, "Gd(i)": 0.0, "Gr(i)": 0.0, "WS10m": 5.0},
        {"time": "20200601:0010", "Gb(i)": 0.0, "Gd(i)": 0.0, "Gr(i)": 0.0, "WS10m": 5.0},
    ]}}
    r = asyncio.run(pvgis(_FakeHttp(payload), 45.0, 8.0, "2022-01-01", "2022-01-31", None))
    # Only the January hour survives the clip; its year is re-stamped to 2022.
    assert r["time"] == ["2022-01-01 00:00"]
    assert r["ghi"] == [200.0]


def test_nasa_power_adapter_parses_and_handles_missing() -> None:
    import asyncio

    from backend.app.importers.databases.openmeteo_renewable.sources import nasa_power

    payload = {"properties": {"parameter": {
        "ALLSKY_SFC_SW_DWN": {"2022010100": 800.0, "2022010101": -999.0},
        "WS50M": {"2022010100": 5.0, "2022010101": 5.0},
    }}}
    r = asyncio.run(nasa_power(_FakeHttp(payload), 45.0, 8.0, "2022-01-01", "2022-01-01", None))
    assert r["time"] == ["2022-01-01 00:00", "2022-01-01 01:00"]
    assert r["ghi"] == [800.0, 0.0]                       # -999 → 0
    assert r["wind_ms"][0] == pytest.approx(5.0 * (2.0 ** (1 / 7)), rel=1e-3)  # 50m → 100m


def test_cache_snap_and_roundtrip(tmp_path, monkeypatch) -> None:
    from backend.app.importers.databases.openmeteo_renewable import cache

    # snap to the 0.1° grid so nearby points share an entry
    assert cache.snap(37.54) == 37.5
    assert cache.snap(37.56) == 37.6
    assert cache.cache_key(37.54, 127.01, "2022-01-01", "2022-01-31", "v") == \
        cache.cache_key(37.55, 127.02, "2022-01-01", "2022-01-31", "v")  # same grid cell

    monkeypatch.setenv("RAGNAROK_WEATHER_CACHE", str(tmp_path))
    key = cache.cache_key(10.0, 20.0, "2022-01-01", "2022-01-02", "v")
    assert cache.get(key) is None
    cache.put(key, {"time": ["t"], "ghi": [1.0], "wind_ms": [2.0]})
    assert cache.get(key) == {"time": ["t"], "ghi": [1.0], "wind_ms": [2.0]}
