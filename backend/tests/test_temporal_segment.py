"""P35: n.cluster.temporal.segment (needs tsam) through network_ops and the HTTP endpoint."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pypsa
import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app import session_store
from backend.pypsa import network_ops
from backend.pypsa.network import pypsa_io

pytest.importorskip("tsam")
client = TestClient(app)
HOURS = 240


def _model() -> dict:
    n = pypsa.Network()
    n.set_snapshots(pd.date_range("2020-01-01", periods=HOURS, freq="h"))
    rng = np.random.default_rng(0)
    n.add("Bus", "b")
    n.add("Load", "l", bus="b", p_set=rng.random(HOURS) * 10 + 5)
    n.add("Generator", "g", bus="b", p_nom=30, marginal_cost=3.0)
    return pypsa_io.model_from_network(n)


def test_segment_reduces_and_keeps_hours() -> None:
    out = network_ops.temporal_cluster(_model(), method="segment", num_segments=12)
    assert out["before"]["snapshots"] == HOURS
    assert out["after"]["snapshots"] == 12
    assert out["after"]["weightedHours"] == pytest.approx(HOURS)  # energy-correct weights


def test_segment_http(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(session_store, "SESSION_DIR", tmp_path / "session")
    sid = "seg1"
    assert client.post("/api/session/model", json={
        "sessionId": sid, "model": _model(), "filename": "c.xlsx", "scenarioName": "r"}).status_code == 200
    r = client.post("/api/transform/temporal", json={"sessionId": sid, "method": "segment", "numSegments": 8})
    assert r.status_code == 200, r.text
    assert r.json()["after"]["snapshots"] == 8


def test_segment_requires_positive_count() -> None:
    with pytest.raises(Exception, match="num_segments"):
        network_ops.temporal_cluster(_model(), method="segment", num_segments=0)
