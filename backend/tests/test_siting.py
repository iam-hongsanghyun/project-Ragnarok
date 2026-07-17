"""Siting (location optimisation) — candidate maths and the /api/siting/scan trip.

Pins the pure geometry (haversine against the analytical meridian arc, grid
sampling bounds/counts, nearest-bus selection) and the fragment contract the
capacity-expansion solve relies on: candidates land extendable at zero
capacity, capped by ``p_nom_max``, with connection capex scaling with
distance.
"""
from __future__ import annotations

import math

import pytest

from backend.app.siting import (
    MAX_CANDIDATES,
    build_siting_fragment,
    haversine_km,
    nearest_bus,
    sample_grid,
)

# One degree of latitude along a meridian: 2πR/360 with R = 6371 km.
_DEG_KM = 2 * math.pi * 6371.0 / 360.0


# ── haversine ────────────────────────────────────────────────────────────────


def test_haversine_matches_meridian_arc() -> None:
    assert haversine_km(0.0, 0.0, 1.0, 0.0) == pytest.approx(_DEG_KM, rel=1e-6)
    assert haversine_km(10.0, 20.0, 10.0, 20.0) == 0.0
    # symmetric
    assert haversine_km(37.5, 127.0, 35.1, 129.0) == pytest.approx(
        haversine_km(35.1, 129.0, 37.5, 127.0), rel=1e-12
    )


def test_haversine_shrinks_longitude_with_latitude() -> None:
    # One degree of longitude at 60°N is about half the equatorial value.
    at_equator = haversine_km(0.0, 0.0, 0.0, 1.0)
    at_60n = haversine_km(60.0, 0.0, 60.0, 1.0)
    assert at_60n == pytest.approx(at_equator * math.cos(math.radians(60.0)), rel=1e-3)


# ── grid sampling ────────────────────────────────────────────────────────────


def test_sample_grid_single_point_is_centre() -> None:
    assert sample_grid((126.0, 34.0, 128.0, 38.0), 1) == [(36.0, 127.0)]


def test_sample_grid_counts_and_bounds() -> None:
    bbox = (126.0, 34.0, 128.0, 38.0)
    pts = sample_grid(bbox, 9)
    assert len(pts) == 9
    for lat, lon in pts:
        assert 34.0 < lat < 38.0
        assert 126.0 < lon < 128.0
    # all distinct
    assert len(set(pts)) == 9


def test_sample_grid_caps_at_max_candidates() -> None:
    pts = sample_grid((0.0, 0.0, 10.0, 10.0), 10_000)
    assert len(pts) == MAX_CANDIDATES


def test_sample_grid_degenerate_bbox_collapses_to_point() -> None:
    assert sample_grid((127.0, 36.0, 127.0, 36.0), 5) == [(36.0, 127.0)]


# ── nearest bus ──────────────────────────────────────────────────────────────


def _buses() -> list[dict]:
    return [
        {"name": "seoul", "x": 127.0, "y": 37.5},
        {"name": "busan", "x": 129.0, "y": 35.1},
        {"name": "no_coords", "x": "", "y": None},
    ]


def test_nearest_bus_picks_closest_and_skips_coordless() -> None:
    name, dist = nearest_bus(37.4, 127.1, _buses())
    assert name == "seoul"
    assert dist == pytest.approx(haversine_km(37.4, 127.1, 37.5, 127.0), abs=0.05)


def test_nearest_bus_raises_without_usable_bus() -> None:
    with pytest.raises(ValueError):
        nearest_bus(37.0, 127.0, [{"name": "x", "x": "", "y": ""}])


# ── fragment builder ─────────────────────────────────────────────────────────


def _site(lat: float, lon: float) -> dict:
    return {
        "lat": lat, "lon": lon,
        "time": ["2023-01-01T00:00", "2023-01-01T01:00", "2023-01-01T02:00"],
        "ghi": [0.0, 500.0, 1000.0],
        "wind_ms": [0.0, 12.0, 30.0],
    }


def _build(**overrides):
    kwargs = dict(
        technologies=["solar", "wind"],
        performance_ratio=1.0,
        site_capacity_mw=400.0,
        capital_cost_per_mw={"solar": 35000.0, "wind": 60000.0},
        connection_cost_per_mw_km=100.0,
    )
    kwargs.update(overrides)
    return build_siting_fragment([_site(37.4, 127.1), _site(35.2, 128.9)], _buses(), **kwargs)


def test_fragment_candidates_are_extendable_from_zero() -> None:
    frag, candidates = _build()
    assert len(candidates) == 2
    gens = frag.sheets["generators"]
    assert len(gens) == 4  # 2 sites × 2 technologies
    for g in gens:
        assert g["p_nom"] == 0.0
        assert g["p_nom_extendable"] is True
        assert g["p_nom_max"] == 400.0
    by_carrier = {g["carrier"]: g for g in gens}
    assert by_carrier["solar"]["capital_cost"] == 35000.0
    assert by_carrier["wind"]["capital_cost"] == 60000.0


def test_fragment_connection_capex_scales_with_distance() -> None:
    frag, candidates = _build()
    links = {row["name"]: row for row in frag.sheets["links"]}
    for c in candidates:
        link = links[f"siting_conn_{c['id']}"]
        assert link["bus0"] == c["siteBus"]
        assert link["bus1"] == c["gridBus"]
        assert link["p_nom_extendable"] is True
        assert link["capital_cost"] == pytest.approx(100.0 * c["distanceKm"], abs=0.51)
    # site 1 is near Seoul, site 2 near Busan — nearest-bus wiring is per site
    assert candidates[0]["gridBus"] == "seoul"
    assert candidates[1]["gridBus"] == "busan"


def test_fragment_cf_series_align_with_generators() -> None:
    frag, _ = _build()
    rows = frag.sheets["generators-p_max_pu"]
    assert len(rows) == 3
    gen_names = {g["name"] for g in frag.sheets["generators"]}
    for row in rows:
        assert set(row) == {"snapshot"} | gen_names
    # η=1: ghi 500 → 0.5; wind 12 m/s → rated → 1.0
    assert rows[1]["siting_solar_1"] == pytest.approx(0.5)
    assert rows[1]["siting_wind_1"] == pytest.approx(1.0)
    assert rows[2]["siting_wind_1"] == 0.0  # 30 m/s → above cut-out


def test_fragment_shifts_snapshots_to_local_time() -> None:
    frag, _ = _build(utc_offset=9)
    assert frag.snapshots[0] == "2023-01-01 09:00"


def test_fragment_tiles_cf_onto_target_snapshots() -> None:
    """Target-snapshot mode: profiles land on the MODEL's labels, tiled.

    The fragment must introduce no new snapshots (so the solve window keeps its
    demand data) and repeat the fetched CF sequence to cover a longer window.
    """
    target = [f"2030-06-01 {h:02d}:00" for h in range(5)]
    frag, _ = build_siting_fragment(
        [_site(37.4, 127.1)], _buses(),
        technologies=["solar"], performance_ratio=1.0,
        capital_cost_per_mw={"solar": 1000.0},
        target_snapshots=target,
    )
    assert frag.snapshots == target
    rows = frag.sheets["generators-p_max_pu"]
    assert [r["snapshot"] for r in rows] == target
    # fetched cf = [0, 0.5, 1.0] tiled over 5 hours
    assert [r["siting_solar_1"] for r in rows] == pytest.approx([0.0, 0.5, 1.0, 0.0, 0.5])


def test_fragment_skips_sites_without_weather() -> None:
    empty = {"lat": 1.0, "lon": 1.0, "time": [], "ghi": [], "wind_ms": []}
    frag, candidates = build_siting_fragment(
        [empty, _site(37.4, 127.1)], _buses(),
        technologies=["solar"], capital_cost_per_mw={"solar": 1000.0},
    )
    assert len(candidates) == 1
    assert candidates[0]["gridBus"] == "seoul"
    assert len(frag.sheets["generators"]) == 1


def test_fragment_empty_when_no_weather_at_all() -> None:
    frag, candidates = build_siting_fragment(
        [{"lat": 1.0, "lon": 1.0, "time": []}], _buses(), technologies=["solar"],
    )
    assert candidates == []
    assert frag.sheets == {}


# ── HTTP endpoint ────────────────────────────────────────────────────────────


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch):
    from fastapi.testclient import TestClient

    from backend.app.main import app
    from backend.app.routers import siting as siting_router

    async def fake_fetch_point(http, lat, lon, date_from, date_to, source="open-meteo", secret=None):
        return {
            "time": ["2023-01-01T00:00", "2023-01-01T01:00"],
            "ghi": [0.0, 800.0],
            "wind_ms": [5.0, 13.0],
        }

    monkeypatch.setattr(siting_router, "fetch_point", fake_fetch_point)
    return TestClient(app)


def _payload(**overrides) -> dict:
    payload = {
        "bbox": [126.0, 34.0, 128.0, 38.0],
        "technologies": ["solar"],
        "gridPoints": 4,
        "buses": [{"name": "seoul", "x": 127.0, "y": 37.5}],
        "siteCapacityMw": 200.0,
        "capitalCostPerMw": {"solar": 40000.0},
        "connectionCostPerMwKm": 50.0,
    }
    payload.update(overrides)
    return payload


def test_scan_returns_candidates_preview_and_fragment(client) -> None:
    resp = client.post("/api/siting/scan", json=_payload())
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["candidates"]) == 4
    assert body["preview"]["counts"]["sites"] == 4
    frag = body["fragment"]
    assert len(frag["sheets"]["generators"]) == 4
    assert len(frag["sheets"]["links"]) == 4
    assert frag["snapshots"] == ["2023-01-01 00:00", "2023-01-01 01:00"]
    for c in body["candidates"]:
        assert c["gridBus"] == "seoul"
        assert c["meanCf"]["solar"] > 0.0


def test_siting_solve_prefers_near_site_over_far_site() -> None:
    """End-to-end: the expansion LP sites capacity by connection cost.

    Two candidate sites with IDENTICAL resource (rated wind, CF = 1 all hours)
    but different grid distance; a 100 MW flat load and expensive gas backup at
    the grid bus. The optimum serves the load from the near candidate: capex is
    generator + rate × distance, so with equal CF the near site strictly
    dominates and the far site must stay unbuilt.
    """
    from backend.pypsa.results import run_pypsa

    hours = [f"2023-01-01T{h:02d}:00" for h in range(24)]
    rated = {"time": hours, "ghi": [0.0] * 24, "wind_ms": [12.0] * 24}
    grid = [{"name": "grid", "x": 127.0, "y": 36.0}]
    frag, candidates = build_siting_fragment(
        [{"lat": 36.0, "lon": 127.5, **rated}, {"lat": 36.0, "lon": 130.0, **rated}],
        grid,
        technologies=["wind"],
        site_capacity_mw=400.0,
        capital_cost_per_mw={"wind": 5000.0},
        connection_cost_per_mw_km=100.0,
    )
    near, far = candidates
    assert near["distanceKm"] < far["distanceKm"]

    model = {
        "snapshots": [{"snapshot": s} for s in frag.snapshots],
        "carriers": frag.sheets["carriers"] + [{"name": "gas"}],
        "buses": grid + frag.sheets["buses"],
        "generators": frag.sheets["generators"] + [
            {"name": "gas", "bus": "grid", "carrier": "gas", "p_nom": 1000, "marginal_cost": 200},
        ],
        "links": frag.sheets["links"],
        "generators-p_max_pu": frag.sheets["generators-p_max_pu"],
        "loads": [{"name": "L", "bus": "grid"}],
        "loads-p_set": [{"snapshot": s, "L": 100.0} for s in frag.snapshots],
    }
    res = run_pypsa(model, {"discountRate": 0.05}, {"snapshotWeight": 1})
    built = {r["name"]: r["p_nom_opt_mw"] for r in (res.get("expansionResults") or [])}
    assert built["siting_wind_1"] == pytest.approx(100.0, abs=1.0)   # near: serves the load
    assert built["siting_wind_2"] == pytest.approx(0.0, abs=1.0)     # far: rejected location
    assert built["siting_conn_1"] == pytest.approx(100.0, abs=1.0)   # connection sized with it


def test_scan_rejects_bad_inputs(client) -> None:
    assert client.post("/api/siting/scan", json=_payload(bbox=[1, 2, 3])).status_code == 422
    assert client.post("/api/siting/scan", json=_payload(buses=[])).status_code == 422
    assert client.post("/api/siting/scan", json=_payload(technologies=["coal"])).status_code == 422
    assert client.post("/api/siting/scan", json=_payload(weatherSource="nope")).status_code == 422
    assert client.post("/api/siting/scan", json=_payload(siteCapacityMw=0)).status_code == 422
    assert client.post("/api/siting/scan", json=_payload(bbox=[128.0, 34.0, 126.0, 38.0])).status_code == 422
