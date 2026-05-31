"""Test fixtures shared across importer test modules.

Provides:
- A minimal countries GeoJSON (Korea + a small "Test Land") so region.py
  can build an index without hitting the network.
- A small WRI GPPD CSV string with one row in Korea and one outside.
- An Overpass JSON payload with two substations and one line.
"""
from __future__ import annotations

import json
from pathlib import Path

# ── Country boundaries fixture ───────────────────────────────────────────────

# Two countries: South Korea (KOR) — a generous bounding box that covers the
# real country — and Test Land (TST), a small box far away. The polygons are
# rectangles, which is enough for point-in-polygon tests without shipping
# Natural Earth at test time.
COUNTRIES_GEOJSON: dict = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "properties": {"ADM0_A3": "KOR", "ADMIN": "South Korea"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [
                        [124.5, 33.0],
                        [131.5, 33.0],
                        [131.5, 39.0],
                        [124.5, 39.0],
                        [124.5, 33.0],
                    ]
                ],
            },
        },
        {
                        "type": "Feature",
            "properties": {"ADM0_A3": "TST", "ADMIN": "Test Land"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [
                        [-10.0, -10.0],
                        [10.0, -10.0],
                        [10.0, 10.0],
                        [-10.0, 10.0],
                        [-10.0, -10.0],
                    ]
                ],
            },
        },
    ],
}


def write_countries_fixture(target: Path) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(COUNTRIES_GEOJSON))
    return target


# ── WRI GPPD CSV fixture ─────────────────────────────────────────────────────

WRI_GPPD_CSV = (
    "country,country_long,name,gppd_idnr,capacity_mw,latitude,longitude,"
    "primary_fuel,commissioning_year,owner\n"
    "KOR,South Korea,Test Coal Plant,KOR0000001,500,37.5,127.0,Coal,1995,KEPCO\n"
    "KOR,South Korea,Test Wind Farm,KOR0000002,80,36.5,128.5,Wind,2018,KOWind Ltd.\n"
    "KOR,South Korea,Tiny Solar,KOR0000003,5,36.0,128.0,Solar,2021,SolarCo\n"
    "USA,United States,Outside Plant,USA0000001,200,40.0,-100.0,Gas,2010,Outside Inc.\n"
)


# ── Overpass JSON fixture ────────────────────────────────────────────────────

OVERPASS_PAYLOAD: dict = {
    "version": 0.6,
    "generator": "test-fixture",
    "elements": [
        {
            "type": "node",
            "id": 1,
            "lat": 37.55,
            "lon": 127.05,
            "tags": {
                "power": "substation",
                "voltage": "220000;110000",
                "name": "Seoul HV",
                "operator": "KEPCO",
            },
        },
        {
            "type": "node",
            "id": 2,
            "lat": 36.60,
            "lon": 128.55,
            "tags": {
                "power": "substation",
                "voltage": "220000",
                "name": "Andong HV",
                "operator": "KEPCO",
            },
        },
        {
            "type": "way",
            "id": 1001,
            "tags": {
                "power": "line",
                "voltage": "220000",
                "circuits": "2",
                "name": "Seoul–Andong 220 kV",
            },
            "geometry": [
                {"lat": 37.55, "lon": 127.05},
                {"lat": 37.0, "lon": 127.8},
                {"lat": 36.60, "lon": 128.55},
            ],
        },
        {
            "type": "way",
            "id": 1002,
            "tags": {
                "power": "line",
                "voltage": "66000",
                "name": "Low-voltage line (filtered out)",
            },
            "geometry": [
                {"lat": 37.5, "lon": 127.0},
                {"lat": 37.4, "lon": 127.1},
            ],
        },
    ],
}
