"""Master model + derive-by-filter (backend/app/model_derive.py + routers/master.py).

Pure-function tests cover year selection, generic attribute filters, vintage
(build_year/lifetime) exclusion, bus/carrier cascades, and both exclusion modes
— the default ``deactivate`` (writes PyPSA's ``active = False``, keeps rows) and
``remove`` (hard-delete + series-column pruning). The HTTP tests cover the
master slot lifecycle (import via save, meta, distinct, derive → working
session, clear) against a temporary SESSION_DIR.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app import model_derive, model_store, session_store
from backend.app.main import app
from backend.app.routers.master import master_id

client = TestClient(app)


def _master_model() -> dict[str, list[dict]]:
    """Two-year master: 3 buses, 3 generators (one 2031 vintage), 1 line, 1 load."""
    snaps = [f"{y}-06-01 {h:02d}:00" for y in (2030, 2031) for h in range(3)]
    return {
        "buses": [
            {"name": "B1", "v_nom": 380.0, "country": "KR"},
            {"name": "B2", "v_nom": 220.0, "country": "KR"},
            {"name": "B3", "v_nom": 380.0, "country": "JP"},
        ],
        "carriers": [{"name": "wind"}, {"name": "gas"}, {"name": "solar"}],
        "generators": [
            {"name": "g_wind", "bus": "B1", "carrier": "wind", "p_nom": 100.0},
            {"name": "g_gas", "bus": "B2", "carrier": "gas", "p_nom": 50.0,
             "build_year": 2000, "lifetime": 25.0},
            {"name": "g_new", "bus": "B2", "carrier": "solar", "p_nom": 25.0,
             "build_year": 2031, "lifetime": 30.0},
        ],
        "lines": [{"name": "L1", "bus0": "B1", "bus1": "B3", "s_nom": 500.0}],
        "loads": [{"name": "d1", "bus": "B1", "p_set": 10.0}],
        "snapshots": [{"snapshot": s} for s in snaps],
        "generators-p_max_pu": [
            {"snapshot": s, "g_wind": 0.5, "g_new": 0.9} for s in snaps
        ],
    }


def _by_name(rows: list[dict], name: str) -> dict:
    return next(r for r in rows if r["name"] == name)


# ── pure: model_derive ──────────────────────────────────────────────────────────
def test_snapshot_years_and_component_sheets() -> None:
    m = _master_model()
    assert model_derive.snapshot_years(m) == [2030, 2031]
    assert set(model_derive.component_sheets(m)) == {"buses", "carriers", "generators", "lines", "loads"}


def test_active_sheets_from_schema() -> None:
    sheets = model_derive.active_sheets()
    assert "generators" in sheets and "lines" in sheets
    # PyPSA has no active flag on buses/carriers — the cascade handles those.
    assert "buses" not in sheets and "carriers" not in sheets


def test_derive_year_filter_trims_snapshots_and_series() -> None:
    derived, report = model_derive.derive_model(_master_model(), years=[2030])
    assert [r["snapshot"] for r in derived["snapshots"]] == [f"2030-06-01 {h:02d}:00" for h in range(3)]
    assert len(derived["generators-p_max_pu"]) == 3
    assert report["years"] == [2030]
    assert report["snapshots"] == 3


def test_derive_vintage_deactivates_by_build_year() -> None:
    derived, report = model_derive.derive_model(_master_model(), years=[2030])
    gens = derived["generators"]
    assert len(gens) == 3  # nothing deleted
    # g_new is built in 2031 → inactive in a 2030 model; g_gas retired 2025 → inactive.
    assert _by_name(gens, "g_new")["active"] is False
    assert _by_name(gens, "g_gas")["active"] is False
    assert _by_name(gens, "g_wind")["active"] is True
    # Series columns stay — the assets still exist, just inactive.
    assert set(derived["generators-p_max_pu"][0]) == {"snapshot", "g_wind", "g_new"}
    assert report["excluded"]["generators"] == 2
    # In 2031 the new build exists but the retired gas plant still doesn't.
    derived31, _ = model_derive.derive_model(_master_model(), years=[2031])
    assert _by_name(derived31["generators"], "g_new")["active"] is True
    assert _by_name(derived31["generators"], "g_gas")["active"] is False


def test_derive_bus_filter_keeps_buses_and_deactivates_dependants() -> None:
    flt = [{"sheet": "buses", "column": "country", "values": ["KR"]}]
    derived, report = model_derive.derive_model(_master_model(), filters=flt)
    # Buses have no PyPSA active flag: all rows stay, even the filtered-out one.
    assert {b["name"] for b in derived["buses"]} == {"B1", "B2", "B3"}
    assert all("active" not in b for b in derived["buses"])
    # L1 connects B1–B3; B3 (JP) is excluded, so the line is deactivated.
    assert _by_name(derived["lines"], "L1")["active"] is False
    assert report["excluded"]["lines"] == 1
    # Components on selected buses stay active (untouched sheets keep their
    # rows verbatim — the explicit column only appears where something changed).
    assert all(g.get("active", True) for g in derived["generators"])


def test_derive_carrier_filter_cascades_only_when_carriers_filtered() -> None:
    flt = [{"sheet": "carriers", "column": "name", "values": ["wind", "solar"]}]
    derived, _ = model_derive.derive_model(_master_model(), filters=flt)
    gens = derived["generators"]
    assert _by_name(gens, "g_gas")["active"] is False
    assert _by_name(gens, "g_wind")["active"] is True
    assert _by_name(gens, "g_new")["active"] is True
    # Carrier rows themselves stay (no active flag in PyPSA).
    assert {c["name"] for c in derived["carriers"]} == {"wind", "gas", "solar"}
    # Without a carriers filter, carrier values are not policed.
    derived2, _ = model_derive.derive_model(_master_model())
    assert all("active" not in g or g["active"] for g in derived2["generators"])


def test_derive_preserves_existing_inactive_rows() -> None:
    m = _master_model()
    m["generators"][0]["active"] = "FALSE"  # Excel-style string survives round-trips
    derived, _ = model_derive.derive_model(m, years=[2030])
    assert _by_name(derived["generators"], "g_wind")["active"] is False


def test_derive_numeric_value_matching() -> None:
    flt = [{"sheet": "buses", "column": "v_nom", "values": ["380.0"]}]
    derived, report = model_derive.derive_model(_master_model(), filters=flt)
    # B2 (220 kV) is excluded → its generators are deactivated via the cascade.
    gens = derived["generators"]
    assert _by_name(gens, "g_gas")["active"] is False
    assert _by_name(gens, "g_new")["active"] is False
    assert _by_name(gens, "g_wind")["active"] is True


def test_derive_remove_mode_deletes_and_prunes_series() -> None:
    derived, report = model_derive.derive_model(
        _master_model(), years=[2030],
        filters=[{"sheet": "buses", "column": "country", "values": ["KR"]}],
        mode="remove",
    )
    assert {b["name"] for b in derived["buses"]} == {"B1", "B2"}
    assert derived["lines"] == []  # L1 lost its B3 end
    assert {g["name"] for g in derived["generators"]} == {"g_wind"}  # vintage removed the rest
    assert set(derived["generators-p_max_pu"][0]) == {"snapshot", "g_wind"}
    assert report["mode"] == "remove"
    assert report["excluded"]["generators"] == 2


def test_derive_rejects_empty_selection() -> None:
    with pytest.raises(ValueError, match="leave no snapshots"):
        model_derive.derive_model(_master_model(), years=[1999])
    with pytest.raises(ValueError, match="No master model"):
        model_derive.derive_model({})


# ── HTTP: /api/session/master ───────────────────────────────────────────────────
@pytest.fixture()
def _session_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(session_store, "SESSION_DIR", tmp_path / "session")
    return tmp_path


def test_master_meta_empty_when_no_master(_session_dir: Path) -> None:
    assert client.get("/api/session/master/meta").json() == {}


def test_master_lifecycle_meta_distinct_derive_clear(_session_dir: Path) -> None:
    # Seed the master slot directly through the store (the /import endpoint is a
    # thin parse-then-save wrapper over the same call).
    model_store.save_model(master_id("default"), _master_model(), filename="master.xlsx")

    meta = client.get("/api/session/master/meta").json()
    assert meta["filename"] == "master.xlsx"
    assert meta["years"] == [2030, 2031]

    resp = client.get("/api/session/master/distinct", params={"sheet": "buses", "column": "country"})
    assert resp.json()["values"] == ["JP", "KR"]

    resp = client.post("/api/session/master/derive", json={
        "years": [2030],
        "filters": [{"sheet": "buses", "column": "country", "values": ["KR"]}],
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["report"]["years"] == [2030]
    assert body["report"]["mode"] == "deactivate"

    # The derive landed in the WORKING session (rows kept, flags set); the
    # master is untouched.
    working = model_store.load_full_model("default")
    assert len(working["snapshots"]) == 3
    assert len(working["generators"]) == 3
    inactive = {g["name"] for g in working["generators"] if not g.get("active", True)}
    assert inactive == {"g_gas", "g_new"}  # vintage exclusions in 2030
    master = model_store.load_full_model(master_id("default"))
    assert len(master["snapshots"]) == 6
    assert all("active" not in g for g in master["generators"])

    assert client.post("/api/session/master/clear").json() == {"cleared": True}
    assert client.get("/api/session/master/meta").json() == {}
    # Clearing the master must not clear the working model.
    assert model_store.load_full_model("default") is not None


def test_derive_400_when_no_master(_session_dir: Path) -> None:
    resp = client.post("/api/session/master/derive", json={"years": [2030]})
    assert resp.status_code == 400
    assert "master" in resp.json()["detail"].lower()
