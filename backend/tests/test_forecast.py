"""T1 statistical multi-year forecast — regression / ARIMA / Prophet.

Unit tests on ``estimate_growth_factor`` (synthetic 10 %/yr history) plus an
end-to-end HTTP check that the forecast endpoint fits the trend and scales the
base-year window onto the future year.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app import session_store, timeseries
from backend.app.main import app

client = TestClient(app)


@pytest.fixture()
def _session_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(session_store, "SESSION_DIR", tmp_path / "session")
    return tmp_path


def _history(rate: float = 0.10) -> dict[str, list[dict]]:
    """One snapshot per year 2018–2022, demand growing at ``rate``/yr."""
    base = 100.0
    rows = [
        {"snapshot": f"{2018 + i}-01-01 00:00", "L": base * (1 + rate) ** i}
        for i in range(5)
    ]
    return {"loads-p_set": rows}


def test_regression_recovers_the_growth_rate() -> None:
    factor, note = timeseries.estimate_growth_factor(_history(0.10), 2022, 2027, "regression")
    # 5 years of compounding at 10 %/yr → 1.1**5 ≈ 1.611.
    assert factor == pytest.approx(1.1 ** 5, rel=1e-3)
    assert "%/yr" in note


def test_arima_projects_growth() -> None:
    factor, _ = timeseries.estimate_growth_factor(_history(0.10), 2022, 2027, "arima")
    assert factor > 1.0  # an upward trend is projected forward


def test_prophet_projects_growth() -> None:
    factor, note = timeseries.estimate_growth_factor(_history(0.10), 2022, 2027, "prophet")
    assert factor > 1.0
    assert "Prophet" in note


def test_needs_at_least_three_years() -> None:
    two_years = {"loads-p_set": [
        {"snapshot": "2021-01-01 00:00", "L": 100.0},
        {"snapshot": "2022-01-01 00:00", "L": 110.0},
    ]}
    with pytest.raises(ValueError, match="at least 3 years"):
        timeseries.estimate_growth_factor(two_years, 2022, 2027, "regression")


def _load_history() -> None:
    rows = _history(0.10)["loads-p_set"]
    model = {
        "buses": [{"name": "b"}],
        "snapshots": [{"snapshot": r["snapshot"]} for r in rows],
        "loads": [{"name": "L", "bus": "b"}],
        "loads-p_set": rows,
    }
    assert client.post(
        "/api/session/model",
        json={"sessionId": "default", "model": model, "filename": "c.xlsx", "scenarioName": "ref"},
    ).status_code == 200


def test_forecast_endpoint_fits_and_projects(_session_dir: Path) -> None:
    _load_history()
    resp = client.post("/api/session/snapshots/forecast", json={
        "sessionId": "default", "fromYear": 2022, "toYear": 2027, "method": "regression",
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["method"] == "regression"
    assert body["growthFactor"] == pytest.approx(1.1 ** 5, rel=1e-2)
    assert "loads-p_set" in body["grown"]
    # The projected window is the 2022 base shifted to 2027, scaled by the factor.
    page = client.get("/api/session/sheet/loads-p_set", params={"limit": 100}).json()
    assert page["total"] == 1
    assert page["rows"][0]["snapshot"].startswith("2027")
    assert page["rows"][0]["L"] == pytest.approx(100.0 * 1.1 ** 4 * 1.1 ** 5, rel=1e-2)


def test_forecast_endpoint_rejects_short_history(_session_dir: Path) -> None:
    model = {
        "buses": [{"name": "b"}],
        "snapshots": [{"snapshot": "2022-01-01 00:00"}],
        "loads": [{"name": "L", "bus": "b"}],
        "loads-p_set": [{"snapshot": "2022-01-01 00:00", "L": 100.0}],
    }
    client.post("/api/session/model", json={"sessionId": "default", "model": model, "filename": "c.xlsx", "scenarioName": "ref"})
    resp = client.post("/api/session/snapshots/forecast", json={
        "sessionId": "default", "fromYear": 2022, "toYear": 2030, "method": "arima",
    })
    assert resp.status_code == 400
    assert "3 years" in resp.json()["detail"]
