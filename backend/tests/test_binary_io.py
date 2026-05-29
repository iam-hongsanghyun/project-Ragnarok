"""Pin the netCDF / HDF5 export + import endpoints."""
from __future__ import annotations

import io
from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app


client = TestClient(app)


def _payload() -> dict[str, Any]:
    model = {
        "buses": [{"name": "b0", "v_nom": 380.0}, {"name": "b1", "v_nom": 380.0}],
        "snapshots": [{"snapshot": "2025-01-01T00:00:00"}],
        "carriers": [{"name": "gas", "co2_emissions": 0.4}],
        "generators": [
            {"name": "g", "bus": "b0", "carrier": "gas", "p_nom": 100.0, "marginal_cost": 20.0}
        ],
        "loads": [{"name": "L", "bus": "b1", "p_set": 80.0}],
    }
    return {"model": model, "scenario": {"discountRate": 0.05}, "options": {}}


@pytest.mark.parametrize("fmt,suffix,mime", [
    ("netcdf", ".nc", "application/x-netcdf"),
    ("hdf5", ".h5", "application/x-hdf5"),
])
def test_round_trip(fmt: str, suffix: str, mime: str) -> None:
    """Export → import must preserve buses + generators identities."""
    r = client.post(f"/api/export/{fmt}", json=_payload())
    assert r.status_code == 200, r.text
    assert len(r.content) > 0
    data = r.content

    files = {"file": (f"test{suffix}", io.BytesIO(data), mime)}
    r = client.post(f"/api/import/{fmt}", files=files)
    assert r.status_code == 200, r.text
    model = r.json()["model"]

    assert {row["name"] for row in model["buses"]} == {"b0", "b1"}
    assert {row["name"] for row in model["generators"]} == {"g"}
    gen = model["generators"][0]
    assert gen["bus"] == "b0"
    assert float(gen["p_nom"]) == 100.0
    assert float(gen["marginal_cost"]) == 20.0
