"""P18/P41/P42/P43: PyPSA-native I/O, MATPOWER import, export options, seasonal rating."""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import pypsa
import pytest
from fastapi.testclient import TestClient

from backend.app import session_store
from backend.app.main import app
from backend.pypsa.network import pypsa_io

client = TestClient(app)

CASE_M = """function mpc = case3
mpc.version = '2';
mpc.baseMVA = 100;
mpc.bus = [
 1 3 0 0 0 0 1 1 0 230 1 1.1 0.9;
 2 2 0 0 0 0 1 1 0 230 1 1.1 0.9;
 3 1 90 30 0 0 1 1 0 230 1 1.1 0.9;
];
mpc.gen = [
 1 0 0 300 -300 1 100 1 250 10 0 0 0 0 0 0 0 0 0 0 0;
 2 80 0 300 -300 1 100 1 200 10 0 0 0 0 0 0 0 0 0 0 0;
];
mpc.branch = [
 1 2 0.01 0.1 0 200 200 200 0 0 1 -360 360;
 2 3 0.01 0.1 0 200 200 200 0 0 1 -360 360;
 1 3 0.01 0.1 0 200 200 200 0 0 1 -360 360;
];
mpc.gencost = [
 2 0 0 2 20 0;
 2 0 0 2 30 0;
];
"""


@pytest.fixture()
def _session_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(session_store, "SESSION_DIR", tmp_path / "session")
    return tmp_path


def _net() -> pypsa.Network:
    n = pypsa.Network()
    n.set_snapshots(pd.date_range("2030-01-01", periods=4, freq="h"))
    n.add("Bus", ["a", "b"])
    n.add("Load", "L", bus="b", p_set=[10, 20, 30, 40])
    n.add("Generator", "g", bus="a", p_nom=100, marginal_cost=5)
    n.add("Line", "l", bus0="a", bus1="b", x=0.1, s_nom=100)
    return n


def test_matpower_m_matches_direct_pypower_import():
    ppc = pypsa_io.parse_matpower_m(CASE_M)
    assert ppc["baseMVA"] == 100.0 and ppc["bus"].shape == (3, 13) and ppc["branch"].shape == (3, 13)
    n = pypsa_io.network_from_matpower(CASE_M.encode(), "case3.m")
    ref = pypsa.Network()
    ref.import_from_pypower_ppc(ppc)
    assert len(n.buses) == 3 and len(n.lines) == 3 and len(n.generators) == 2
    np.testing.assert_allclose(n.lines["x"].to_numpy(), ref.lines["x"].to_numpy(), rtol=1e-12)
    np.testing.assert_allclose(n.loads["p_set"].to_numpy(), [90.0], rtol=1e-12)


def test_matpower_rejects_non_case():
    with pytest.raises(ValueError):
        pypsa_io.parse_matpower_m("hello")


def test_excel_and_csv_roundtrip_fidelity():
    n = _net()
    for fmt, loader in (("excel", pypsa_io.network_from_excel), ("csv", pypsa_io.network_from_csv_zip)):
        data, _media, _name = pypsa_io.export_network_bytes(n, fmt)
        back = loader(data)
        assert list(back.buses.index) == ["a", "b"]
        np.testing.assert_allclose(back.loads_t.p_set["L"].to_numpy(), [10, 20, 30, 40])
        assert back.lines.at["l", "x"] == pytest.approx(0.1)


def test_netcdf_options_compression_float32_standard_types(tmp_path):
    n = _net()
    plain, _, _ = pypsa_io.export_network_bytes(n, "netcdf")
    kw = pypsa_io.netcdf_export_kwargs(
        {"netcdfCompression": 5, "netcdfFloat32": True, "exportStandardTypes": True}
    )
    assert kw == {"export_standard_types": True, "float32": True,
                  "compression": {"zlib": True, "complevel": 5}}
    small, _, _ = pypsa_io.export_network_bytes(
        n, "netcdf", {"netcdfCompression": True, "netcdfFloat32": True}
    )
    assert len(small) < len(plain)
    p = tmp_path / "x.nc"
    p.write_bytes(small)
    back = pypsa.Network()
    back.import_from_netcdf(str(p))
    np.testing.assert_allclose(back.loads_t.p_set["L"].to_numpy(), [10, 20, 30, 40], rtol=1e-6)
    std = pypsa_io.export_network_bytes(n, "excel", {"exportStandardTypes": True})[0]
    assert len(std) > len(pypsa_io.export_network_bytes(n, "excel")[0])
    assert pypsa_io.netcdf_export_kwargs(None) == {}


def test_seasonal_rating_matches_native():
    n = _net()
    model = pypsa_io.model_from_network(n)
    out = pypsa_io.seasonal_rating_transform(
        model, {"l": {"summer": 80, "winter": 100}}, summer_months=[1], compose=False
    )
    rows = out["model"]["lines-s_max_pu"]
    assert len(rows) == 4 and all(r["l"] == pytest.approx(0.8) for r in rows)  # January = "summer"
    out2 = pypsa_io.seasonal_rating_transform(model, {"l": {"summer": 80, "winter": 100}}, summer_months=[7])
    assert all(r["l"] == pytest.approx(1.0) for r in out2["model"]["lines-s_max_pu"])
    with pytest.raises(ValueError):
        pypsa_io.seasonal_rating_transform(model, {"l": {"summer": -1, "winter": 100}})


def test_http_endpoints(_session_dir):
    n = _net()
    xl, _, _ = pypsa_io.export_network_bytes(n, "excel")
    r = client.post("/api/import/pypsa-excel", files={"file": ("n.xlsx", xl)})
    assert r.status_code == 200, r.text
    assert {x["name"] for x in r.json()["model"]["buses"]} == {"a", "b"}
    r = client.post("/api/import/matpower", files={"file": ("case3.m", CASE_M.encode())})
    assert r.status_code == 200, r.text
    assert len(r.json()["model"]["lines"]) == 3
    r = client.post("/api/import/pandapower", files={"file": ("n.json", b"{}")})
    assert r.status_code in (400, 501)
    caps = client.get("/api/import/pypsa-io/capabilities").json()
    assert "matpower" in caps["import"]
    # seasonal rating over HTTP on a session model
    model = pypsa_io.model_from_network(n)
    assert client.post("/api/session/model", json={
        "sessionId": "t1", "model": model, "filename": "c.xlsx", "scenarioName": "r"}).status_code == 200
    r = client.post("/api/transform/seasonal-rating", json={
        "sessionId": "t1", "ratings": {"l": {"summer": 50, "winter": 100}}, "summerMonths": [1]})
    assert r.status_code == 200, r.text
    assert r.json()["model"]["lines-s_max_pu"][0]["l"] == pytest.approx(0.5)
    r = client.post("/api/transform/seasonal-rating", json={
        "sessionId": "t1", "ratings": {"nope": {"summer": 50, "winter": 100}}})
    assert r.status_code == 400
    # export endpoints use the session model + options
    body = {"sessionId": "t1", "scenario": {"discountRate": 0.05},
            "options": {"exportStandardTypes": True}}
    r = client.post("/api/export/pypsa-csv", json=body)
    assert r.status_code == 200, r.text
    assert "buses.csv" in zipfile.ZipFile(io.BytesIO(r.content)).namelist()
    r = client.post("/api/export/pypsa-excel", json=body)
    assert r.status_code == 200 and len(r.content) > 1000
    body["options"] = {"netcdfCompression": True, "netcdfFloat32": True}
    r = client.post("/api/export/netcdf", json=body)
    assert r.status_code == 200 and len(r.content) > 100


def test_matpower_mat_matches_m():
    from scipy.io import savemat

    ppc = pypsa_io.parse_matpower_m(CASE_M)
    buf = io.BytesIO()
    savemat(buf, {"mpc": {k: v for k, v in ppc.items() if k != "version"}})
    n_mat = pypsa_io.network_from_matpower(buf.getvalue(), "case3.mat")
    n_m = pypsa_io.network_from_matpower(CASE_M.encode(), "case3.m")
    np.testing.assert_allclose(n_mat.lines["x"].to_numpy(), n_m.lines["x"].to_numpy(), rtol=1e-12)
    assert len(n_mat.generators) == 2
