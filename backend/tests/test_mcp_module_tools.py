"""MCP tools added with the coverage audit: fuel-costs writes, plants / totals / budget reads, Forge fixes, RFNBO and P2X reads.

Two styles. End-to-end: the real ``RagnarokClient`` talks to the real FastAPI app through an ASGI transport, so a tool's
arguments, the endpoint's validation and the stored sheet are all exercised. Fake client: where only the tool's own shaping
(caps, truncation notices, argument checks) is under test.
"""
from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest

from backend.app import fuel_costs as fc
from backend.app import model_store
from backend.app.main import app
from backend.mcp import (
    server,
    tools_analysis,
    tools_p2x,
    tools_plants,
    tools_policy_modules,
    tools_results_extra,
)
from backend.mcp.client import Config, RagnarokAPIError, RagnarokClient
from backend.tests.test_fuel_costs import STAMPS, _model

SID = "test-mcp-module-tools"


@pytest.fixture()
def live(monkeypatch: pytest.MonkeyPatch, tmp_path: Any):
    """The MCP client wired to the in-process app, with a model loaded in session SID."""
    from backend.app.p2x import config_store

    monkeypatch.setattr(config_store, "data_root", lambda: tmp_path)   # the stored RFNBO settings never touch the real data dir
    monkeypatch.setenv("RAGNAROK_MCP_AUTONOMY", "guided")
    client = RagnarokClient(Config("http://test", SID, 30.0), transport=httpx.ASGITransport(app=app))
    monkeypatch.setattr(server, "_client", client)
    model_store.save_model(SID, _model(sheets=False))
    try:
        yield client
    finally:
        model_store.clear(SID)
        asyncio.run(client.aclose())


def run(coro: Any) -> Any:
    return asyncio.run(coro)


def sheet(name: str) -> list[dict[str, Any]]:
    return (model_store.get_sheet_page(SID, name, 0, 10_000) or {}).get("rows") or []


# ── fuel costs ──────────────────────────────────────────────────────────────────────

def test_set_fuel_price_constant_in_native_unit_and_read_back(live: RagnarokClient) -> None:
    out = run(tools_policy_modules.set_fuel_price("gas", price=8.0, unit="MMBtu"))
    assert out["kind"] == "constant" and out["thermalPrice"] == pytest.approx(27.297136)
    inputs = run(tools_policy_modules.get_fuel_inputs())
    assert inputs["prices"] == [{"carrier": "gas", "source": "flat", "value": pytest.approx(27.297136)}]
    assert inputs["nativeUnits"]["gas"] == "MMBtu" and inputs["active"] is True


def test_set_fuel_price_series_then_remove(live: RagnarokClient) -> None:
    series = [{"snapshot": s, "price": 30.0 + i} for i, s in enumerate(STAMPS)]
    out = run(tools_policy_modules.set_fuel_price("gas", series=series))
    assert out["kind"] == "series" and out["snapshots"] == 4 and out["mean"] == pytest.approx(31.5)
    assert [r["gas"] for r in sheet(fc.SHEET_PRICES)] == [30.0, 31.0, 32.0, 33.0]
    gone = run(tools_policy_modules.set_fuel_price("gas", remove=True))
    assert gone["removed"] == {"series": True, "flat": False} and sheet(fc.SHEET_PRICES) == []


def test_set_fuel_price_argument_and_server_errors_are_actionable(live: RagnarokClient) -> None:
    assert "exactly one of price" in run(tools_policy_modules.set_fuel_price("gas"))["error"]
    assert "exactly one of price" in run(tools_policy_modules.set_fuel_price("gas", price=1.0, series=[{"snapshot": STAMPS[0], "price": 1.0}]))["error"]
    with pytest.raises(RagnarokAPIError) as e:
        run(tools_policy_modules.set_fuel_price("power", price=1.0))
    assert e.value.status == 400 and "unknown carrier 'power'; valid:" in str(e.value)
    with pytest.raises(RagnarokAPIError, match="valid: MWh_th or MMBtu"):
        run(tools_policy_modules.set_fuel_price("gas", price=1.0, unit="bbl"))


def test_manual_autonomy_previews_and_a_series_preview_is_not_the_whole_series(live: RagnarokClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAGNAROK_MCP_AUTONOMY", "manual")
    series = [{"snapshot": f"2030-01-{d:02d}", "price": 1.0} for d in range(1, 29)] * 10
    out = run(tools_policy_modules.set_fuel_price("gas", series=series))
    assert out["status"] == "preview" and out["wouldSend"]["series"]["points"] == 280
    assert len(out["wouldSend"]["series"]["first"]) == 3 and len(str(out)) < 2000
    assert sheet(fc.SHEET_PRICES) == []                                   # nothing written
    done = run(tools_policy_modules.set_fuel_price("gas", price=5.0, confirm=True))
    assert done["kind"] == "constant"
    assert run(tools_policy_modules.set_vom("Generator", 3.0, name="coal"))["status"] == "preview"
    assert run(tools_policy_modules.set_fuel_price_scenario("high", "gas", multiplier=1.2))["status"] == "preview"


def test_set_vom_and_scenario_price_end_to_end(live: RagnarokClient) -> None:
    run(tools_policy_modules.set_vom("Generator", 3.0, name="coal"))
    run(tools_policy_modules.set_vom("Link", 2.0, carrier="CCGT"))
    assert sheet(fc.SHEET_VOM) == [{"component": "Generator", "name": "coal", "vom": 3.0}, {"component": "Link", "carrier": "CCGT", "vom": 2.0}]
    run(tools_policy_modules.set_vom("Link", carrier="CCGT", remove=True))
    assert len(sheet(fc.SHEET_VOM)) == 1
    assert "give vom" in run(tools_policy_modules.set_vom("Generator", name="coal"))["error"]
    with pytest.raises(RagnarokAPIError, match="no Generator named 'nope'; valid: 'coal'"):
        run(tools_policy_modules.set_vom("Generator", 1.0, name="nope"))
    run(tools_policy_modules.set_fuel_price_scenario("high", "gas", multiplier=1.5))
    run(tools_policy_modules.set_fuel_price_scenario("high", "gas", price=40.0, snapshot=STAMPS[1]))
    assert len(sheet(fc.SHEET_PRICE_SCENARIOS)) == 2
    assert "give a price" in run(tools_policy_modules.set_fuel_price_scenario("high", "gas"))["error"]
    run(tools_policy_modules.set_fuel_price_scenario("high", "gas", remove=True))
    assert [r["snapshot"] for r in sheet(fc.SHEET_PRICE_SCENARIOS)] == [STAMPS[1]]


def test_get_fuel_costs_follows_what_the_write_tools_set(live: RagnarokClient) -> None:
    run(tools_policy_modules.set_fuel_price("coal", price=40.0))
    run(tools_policy_modules.set_vom("Generator", 4.0, name="coal"))
    body = run(tools_policy_modules.get_fuel_costs())
    coal = next(u for u in body["units"] if u["name"] == "coal")
    assert coal["marginalCost"]["newMean"] == pytest.approx(40.0 / 0.4 + 4.0)


# ── Forge fixes ─────────────────────────────────────────────────────────────────────

def _overnight_model() -> dict[str, Any]:
    m = _model(sheets=False)
    m["generators"][0]["overnight_cost"] = 1000.0
    m["generators"][0]["p_nom_max"] = 1e12
    return m


def test_fill_discount_rate_previews_then_writes(live: RagnarokClient) -> None:
    model_store.save_model(SID, _overnight_model())
    out = run(tools_analysis.fill_discount_rate(0.07))             # guided: not cheap -> preview
    assert out["status"] == "preview" and out["wouldChange"]["sheets"] == {"generators": 2}
    assert "discount_rate" not in model_store.load_full_model(SID, static_only=True)["generators"][0]
    done = run(tools_analysis.fill_discount_rate(0.07, confirm=True))
    assert done["applied"] is True
    assert model_store.load_full_model(SID, static_only=True)["generators"][0]["discount_rate"] == 0.07
    again = run(tools_analysis.fill_discount_rate(0.07, confirm=True))
    assert again["status"] == "nothing to change"


def test_clean_placeholder_bounds_previews_then_writes(live: RagnarokClient) -> None:
    model_store.save_model(SID, _overnight_model())
    out = run(tools_analysis.clean_placeholder_bounds())
    assert out["status"] == "preview" and out["wouldChange"]["sheets"] == {"generators": 2}
    run(tools_analysis.clean_placeholder_bounds(confirm=True))
    assert model_store.load_full_model(SID, static_only=True)["generators"][0].get("p_nom_max") in (None, "")


# ── RFNBO and P2X reads ─────────────────────────────────────────────────────────────

def test_rfnbo_config_roundtrip_check_and_defaults(live: RagnarokClient) -> None:
    assert run(tools_p2x.get_rfnbo_config())["config"] is None
    stored = run(tools_p2x.set_rfnbo_config({"enabled": False, "temporal": "monthly"}))
    assert stored["config"]["temporal"] == "monthly"
    assert run(tools_p2x.get_rfnbo_config())["config"]["temporal"] == "monthly"
    checks = run(tools_p2x.check_rfnbo())
    assert checks["regulation"].startswith("Commission Delegated Regulation") and "additionality" in checks
    with pytest.raises(RagnarokAPIError) as e:
        run(tools_p2x.set_rfnbo_config({"temporal": "weekly"}))
    assert e.value.status == 400
    defaults = run(tools_p2x.get_p2x_chain_defaults())
    assert "H2" in defaults["products"] and "spec" in defaults


def test_set_rfnbo_config_manual_preview(live: RagnarokClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAGNAROK_MCP_AUTONOMY", "manual")
    assert run(tools_p2x.set_rfnbo_config({"enabled": True}))["status"] == "preview"
    assert run(tools_p2x.get_rfnbo_config())["config"] is None


# ── plants, totals, budgets (fake client: only the tool's own shaping) ──────────────

class Fake:
    def __init__(self, replies: dict[str, Any]) -> None:
        self.replies, self.session_id, self.calls = replies, "s", []

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        self.calls.append((path, params))
        return self.replies[path]

    async def _post(self, path: str, body: dict[str, Any] | None = None) -> Any:
        self.calls.append((path, body))
        return self.replies[path]


def test_list_plants_is_compact_and_capped(monkeypatch: pytest.MonkeyPatch) -> None:
    plants = [{"plantId": f"p{i}", "type": "ccgt" if i % 2 else "bess", "bus": "b", "spec": {"big": list(range(50))},
               "components": [{"sheet": "generators", "name": f"g{i}"}], "capacityMwEl": 100.0} for i in range(120)]
    monkeypatch.setattr(server, "_client", Fake({"/api/build/plants": {"plants": plants, "total": 120}}))
    out = run(tools_plants.list_plants())
    assert out["total"] == 120 and out["returned"] == 50 and "Showing 50 of 120" in out["truncated"]
    assert "spec" not in out["plants"][0] and out["plants"][0]["componentCount"] == 1
    assert len(str(out)) < 15_000
    only = run(tools_plants.list_plants(plant_type="ccgt", include_spec=True, limit=5))
    assert only["total"] == 60 and only["returned"] == 5 and "spec" in only["plants"][0]
    assert "truncated" not in run(tools_plants.list_plants(plant_type="bess", limit=100))


def test_get_run_totals_ranks_caps_and_validates(monkeypatch: pytest.MonkeyPatch) -> None:
    gens = {f"g{i}": {"energyMwh": float(i), "operatingCost": 10.0 - i, "carbonCost": 0.0} for i in range(200)}
    reply = {"run": "r", "period": None, "modeledHours": 8760.0, "weights": [1.0] * 8760, "generators": gens, "buses": {}, "processes": {}}
    monkeypatch.setattr(server, "_client", Fake({"/api/runs/r/derived": reply}))
    out = run(tools_results_extra.get_run_totals("r", sort_by="energyMwh", limit=3))
    assert list(out["items"]) == ["g199", "g198", "g197"] and out["total"] == 200 and out["sortedBy"] == "energyMwh"
    assert "top 3 of 200 generators" in out["truncated"] and "weights" not in out and "8760 values" in out["weightsHint"]
    assert len(str(run(tools_results_extra.get_run_totals("r")))) < 12_000
    assert "unknown sort_by" in run(tools_results_extra.get_run_totals("r", sort_by="mwh"))["error"]
    assert "unknown group" in run(tools_results_extra.get_run_totals("r", group="lines"))["error"]
    assert len(run(tools_results_extra.get_run_totals("r", include_weights=True))["weights"]) == 8760


def test_get_annual_budgets_sheet_and_run_modes(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = Fake({
        "/api/annual-budgets": {"sheet": "RAGNAROK_AnnualBudgets", "rows": [{"component": "generators"}]},
        "/api/annual-budgets/preview": {"table": [{"value": 1.0}], "notes": []},
        "/api/runs/r/annual-budgets": {"run": "r", "items": [{"binding": True}], "total": 1},
    })
    monkeypatch.setattr(server, "_client", fake)
    both = run(tools_policy_modules.get_annual_budgets())
    assert both["rows"] == [{"component": "generators"}] and both["table"] == [{"value": 1.0}]
    assert run(tools_policy_modules.get_annual_budgets(run_name="r"))["items"] == [{"binding": True}]
