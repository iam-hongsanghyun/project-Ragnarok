"""P42: pandapower import through the isolated .venv-pandapower subprocess."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.pypsa.network import pypsa_io

client = TestClient(app)
FIXTURE = Path(__file__).parent / "fixtures" / "pandapower_example_simple.json"  # pandapower.networks.example_simple()

needs_env = pytest.mark.skipif(
    pypsa_io.pandapower_python() is None,
    reason="isolated pandapower venv missing (run backend/scripts/setup_pandapower_env.sh)",
)


@needs_env
def test_example_simple_maps_to_pypsa() -> None:
    n = pypsa_io.network_from_pandapower_json(FIXTURE.read_text())
    assert (len(n.buses), len(n.lines), len(n.transformers), len(n.loads)) == (5, 4, 1, 1)
    assert len(n.generators) == 3  # ext_grid + gen + sgen
    assert set(n.buses.v_nom) == {110.0, 20.0}
    # standard-typed branches keep their pandapower type; PyPSA derives x/s_nom from its catalogue
    assert n.transformers.type.iloc[0] == "25 MVA 110/20 kV"
    assert (n.lines.type != "").all()
    n.calculate_dependent_values()
    assert (n.lines.x > 0).all()
    assert n.transformers.s_nom.iloc[0] == pytest.approx(25.0)


@needs_env
def test_endpoint_end_to_end() -> None:
    r = client.post("/api/import/pandapower", files={"file": ("n.json", FIXTURE.read_bytes())})
    assert r.status_code == 200, r.text
    model = r.json()["model"]
    assert model["buses"] and model["lines"] and model["transformers"]


@needs_env
def test_garbage_json_is_400() -> None:
    r = client.post("/api/import/pandapower", files={"file": ("n.json", b"{}")})
    assert r.status_code == 400


def test_missing_env_is_501(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pypsa_io, "pandapower_python", lambda: None)
    r = client.post("/api/import/pandapower", files={"file": ("n.json", b"{}")})
    assert r.status_code == 501
    assert "setup_pandapower_env" in r.json()["detail"]


def test_duplicate_and_null_names_are_made_unique() -> None:
    split = {"columns": ["index", "name", "bus"], "data": [[0, None, 1], [1, "x", 1], [2, "x", 1]]}
    net = pypsa_io._net_from_dump({"f_hz": 50, "tables": {"load": split}})
    assert list(net.load.name) == ["load 0", "load 1", "load 2"]
