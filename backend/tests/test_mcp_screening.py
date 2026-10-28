"""MCP tools of the Screening module: registration, read-only flags, confirm gating, request shaping.

A recording fake replaces the shared client (as in test_mcp_gui_reach.py); the tool coroutines
are called directly, no backend needed. The route-to-tool map is pinned so a new route cannot
ship without its tool.
"""
from __future__ import annotations

import asyncio
from typing import Any

import pytest

from backend.mcp import server
from backend.mcp import tools_screening as t
from backend.mcp.server import mcp

READ_ONLY = {
    "list_siting_datasets", "get_siting_dataset", "validate_siting_dataset", "siting_correlation",
    "siting_lagged_correlation", "siting_profiles", "siting_portfolio_metrics", "siting_optimise_portfolio",
    "siting_cluster_sites", "siting_region_series", "siting_region_structure",
}
GATED = {"upload_siting_dataset", "delete_siting_dataset", "promote_siting_sites"}


class Fake:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []

    async def screening_upload(self, series, series_name, *, sites, sites_name, validate_only, form):
        self.calls.append(("upload", validate_only, series, sites, form))
        return {"ok": True, "message": "Valid.", "report": {}} if validate_only else {"id": "ds_1", "sites": []}

    async def screening_list(self, kind=None):
        self.calls.append(("list", kind))
        return {"items": [], "total": 0}

    async def screening_get(self, dataset_id):
        self.calls.append(("get", dataset_id))
        return {"id": dataset_id}

    async def screening_delete(self, dataset_id):
        self.calls.append(("delete", dataset_id))
        return {"deleted": True}

    async def screening_post(self, route, body):
        self.calls.append(("post", route, body))
        if route == "correlation":
            return {"distance": [{"a": "x", "b": str(i)} for i in range(300)], "matrix": []}
        if route == "promote":
            return {"applied": body.get("apply"), "report": {"ok": True}, "counts": {"generators": 1}, "generators": ["g"], "meta": {"x": 1}}
        return {"route": route}


@pytest.fixture()
def fake(monkeypatch: pytest.MonkeyPatch) -> Fake:
    f = Fake()
    monkeypatch.setattr(server, "_client", f)
    monkeypatch.setenv("RAGNAROK_MCP_AUTONOMY", "guided")
    return f


def test_every_siting_screening_tool_is_registered_with_the_right_flag() -> None:
    by_name = {tool.name: tool for tool in asyncio.run(mcp.list_tools())}
    for name in READ_ONLY:
        assert by_name[name].annotations.readOnlyHint is True, name
    for name in GATED:
        assert by_name[name].annotations.readOnlyHint is False, name
        assert "confirm" in by_name[name].inputSchema["properties"], name


def test_every_route_has_a_tool() -> None:
    from backend.app.routers import screening

    routes = {(m, r.path.removeprefix("/api/screening")) for r in screening.router.routes
              for m in r.methods if m != "HEAD"}  # type: ignore[attr-defined]
    covered = {
        ("POST", "/validate"): "validate_siting_dataset", ("POST", "/datasets"): "upload_siting_dataset",
        ("GET", "/datasets"): "list_siting_datasets", ("GET", "/datasets/{dataset_id}"): "get_siting_dataset",
        ("DELETE", "/datasets/{dataset_id}"): "delete_siting_dataset", ("POST", "/correlation"): "siting_correlation",
        ("POST", "/lagged"): "siting_lagged_correlation", ("POST", "/profiles"): "siting_profiles",
        ("POST", "/metrics"): "siting_portfolio_metrics", ("POST", "/optimise"): "siting_optimise_portfolio",
        ("POST", "/cluster"): "siting_cluster_sites", ("POST", "/promote"): "promote_siting_sites",
        ("POST", "/regions"): "siting_region_series", ("POST", "/regions/structure"): "siting_region_structure",
    }
    assert routes == set(covered)
    names = {tool.name for tool in asyncio.run(mcp.list_tools())}
    assert set(covered.values()) <= names


def test_read_only_tools_shape_the_request_and_cap_inline_pairs(fake: Fake) -> None:
    out = asyncio.run(t.siting_correlation("ds_1", basis="monthly", method="spearman", anomaly=True,
                                           reference={"type": "load"}, utc_offset_hours=9))
    body = fake.calls[-1][2]
    assert body["datasetId"] == "ds_1" and body["basis"] == "monthly" and body["method"] == "spearman"
    assert body["anomaly"] is True and body["utcOffsetHours"] == 9 and body["reference"] == {"type": "load"}
    assert "rule" not in body  # unset options are not sent
    assert len(out["distance"]) == 200 and out["distanceTruncated"] == {"returned": 200, "total": 300}
    asyncio.run(t.siting_optimise_portfolio("ds_1", objective="max_mean", variance_cap=0.01, region_caps={"n": 0.5}))
    assert fake.calls[-1][1] == "optimise" and fake.calls[-1][2]["varianceCap"] == 0.01
    asyncio.run(t.siting_cluster_sites("ds_1", k=3))
    assert fake.calls[-1][1] == "cluster"
    asyncio.run(t.siting_lagged_correlation("ds_1", "W1", max_lag_hours=24))
    assert fake.calls[-1][2]["maxLagHours"] == 24
    asyncio.run(t.siting_profiles("ds_1"))
    assert fake.calls[-1][2]["includeSeries"] is False
    asyncio.run(t.siting_portfolio_metrics("ds_1", {"a": 1.0}))
    assert fake.calls[-1][1] == "metrics"


def test_upload_is_gated_and_validates_first(fake: Fake) -> None:
    prev = asyncio.run(t.upload_siting_dataset("timestamp,a\n2019-01-01,0.1\n", "ds", sites=[{"name": "a", "lat": 1, "lon": 2, "technology": "solar"}]))
    assert prev["status"] == "preview" and prev["wouldSend"]["validation"]["ok"] is True
    assert [c[1] for c in fake.calls if c[0] == "upload"] == [True]  # validated only, nothing stored
    assert b"name,lat,lon,technology" in fake.calls[-1][3]
    done = asyncio.run(t.upload_siting_dataset("timestamp,a\n", "ds", sites_csv="name,lat,lon,technology\na,1,2,solar\n", confirm=True))
    assert done["id"] == "ds_1" and fake.calls[-1][1] is False


def test_delete_and_promote_are_gated(fake: Fake) -> None:
    assert asyncio.run(t.delete_siting_dataset("ds_1"))["status"] == "preview"
    assert not any(c[0] == "delete" for c in fake.calls)
    assert asyncio.run(t.delete_siting_dataset("ds_1", confirm=True)) == {"deleted": True}

    prev = asyncio.run(t.promote_siting_sites("ds_1", ["a"]))
    assert prev["status"] == "preview" and prev["wouldSend"]["report"] == {"ok": True}
    assert fake.calls[-1][2]["apply"] is False and fake.calls[-1][2]["includeFragment"] is False
    done = asyncio.run(t.promote_siting_sites("ds_1", ["a"], p_nom_mw={"a": 50}, confirm=True))
    assert fake.calls[-1][2]["apply"] is True and fake.calls[-1][2]["pNomMw"] == {"a": 50}
    assert done["applied"] is True and "meta" not in done


def test_auto_autonomy_skips_the_gate(fake: Fake, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAGNAROK_MCP_AUTONOMY", "auto")
    asyncio.run(t.promote_siting_sites("ds_1", ["a"]))
    assert fake.calls[-1][2]["apply"] is True


def test_region_level_is_sent_only_when_asked_and_region_tools_shape_the_request(fake: Fake) -> None:
    asyncio.run(t.siting_correlation("ds_1"))
    assert "level" not in fake.calls[-1][2] and "weighting" not in fake.calls[-1][2]  # site level: backend defaults
    asyncio.run(t.siting_correlation("ds_1", level="region", weighting="capacity", by_technology=True))
    body = fake.calls[-1][2]
    assert body["level"] == "region" and body["weighting"] == "capacity" and body["byTechnology"] is True
    asyncio.run(t.siting_optimise_portfolio("ds_1", level="region", region_caps={"north": 0.5}, site_weights={"a": 2.0}))
    assert fake.calls[-1][2]["siteWeights"] == {"a": 2.0} and fake.calls[-1][2]["regionCaps"] == {"north": 0.5}
    asyncio.run(t.siting_region_series("ds_1", regions=["north"], technology="wind"))
    assert fake.calls[-1][1] == "regions" and fake.calls[-1][2]["sites"] == ["north"] and fake.calls[-1][2]["technology"] == "wind"
    asyncio.run(t.siting_region_structure("ds_1", regions=["north", "south"], basis="monthly", anomaly=True))
    route, body = fake.calls[-1][1], fake.calls[-1][2]
    assert route == "regions/structure" and body["regions"] == ["north", "south"] and body["basis"] == "monthly"


def test_region_upload_sends_the_region_table_and_polygons(fake: Fake) -> None:
    poly = {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]}
    asyncio.run(t.upload_siting_dataset(
        "timestamp,N\n", "regions", kind="regions", regions=[{"name": "N", "lat": 1, "lon": 2, "geometry": poly}],
        geojson={"type": "FeatureCollection", "features": []}, confirm=True))
    call = fake.calls[-1]
    assert call[1] is False and call[4]["kind"] == "regions" and '"FeatureCollection"' in call[4]["geojson"]
    assert b'""type"": ""Polygon""' in call[3]  # the polygon travels as JSON text in a CSV cell
