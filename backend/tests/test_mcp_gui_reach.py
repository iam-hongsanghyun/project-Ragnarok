"""Tests for the MCP tools that cover the rest of the GUI's reach (examples,
importer catalog, secrets, master, plugins, siting, PyPSA-Earth) and for
submit_solve reporting its OWN run.

Same approach as test_mcp_server.py: a recording fake replaces the shared client
and the tool coroutines are called directly — no backend needed.
"""

from __future__ import annotations

import asyncio
import io
import zipfile
from typing import Any

from backend.mcp import server


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []
        self.queue_job: dict[str, Any] = {"id": "j1", "status": "done", "runName": "mine"}

    def called(self, name: str) -> bool:
        return any(c[0] == name for c in self.calls)

    def last(self, name: str) -> tuple[Any, ...]:
        return next(c for c in reversed(self.calls) if c[0] == name)

    async def load_example(self, example_id: str) -> dict:
        self.calls.append(("load_example", example_id))
        return {"filename": example_id}

    async def put_import_secret(self, name: str, value: str) -> dict:
        self.calls.append(("put_import_secret", name, value))
        return {"name": name, "stored": bool(value)}

    async def install_plugin(self, data: bytes, filename: str) -> dict:
        self.calls.append(("install_plugin", data, filename))
        return {"id": "p1"}

    async def load_full_model(self, static_only: bool = False) -> dict:
        self.calls.append(("load_full_model", static_only))
        return {"buses": [{"name": "b1", "x": 127.0, "y": 37.5}, {"name": "nocoord"}]}

    async def get_sheet_page(self, name: str, offset: int = 0, limit: int = 100) -> dict:
        self.calls.append(("get_sheet_page", name))
        return {"rows": [{"snapshot": "2024-01-01T00:00:00"}, {"snapshot": "2024-01-01T01:00:00"}]}

    async def siting_scan(self, req: dict) -> dict:
        self.calls.append(("siting_scan", req))
        return {"candidates": [{"id": "c1"}], "preview": {}, "fragment": {"sheets": {"generators": []}}}

    async def apply_fragment(self, fragment: dict) -> dict:
        self.calls.append(("apply_fragment", fragment))
        return {}

    async def save_model(self, model: dict) -> dict:
        self.calls.append(("save_model", sorted(model)))
        return {}

    async def pypsa_earth_build_result(self, job_id: str) -> dict:
        self.calls.append(("pypsa_earth_build_result", job_id))
        return {"fragment": {"sheets": {"buses": [{"name": "x"}]}}, "counts": {"buses": 1}}

    async def submit_solve(self, scenario=None, options=None) -> dict:
        self.calls.append(("submit_solve",))
        return {"id": "j1", "status": "queued"}

    async def get_queue(self) -> dict:
        return {"jobs": [self.queue_job]}

    async def list_runs(self) -> dict:
        self.calls.append(("list_runs",))
        return {"runs": [{"name": "someone_elses_newer_run"}]}

    async def get_analytics(self, name: str) -> dict:
        self.calls.append(("get_analytics", name))
        return {"run": name}


def _install(monkeypatch, autonomy: str = "guided") -> FakeClient:
    fake = FakeClient()
    monkeypatch.setattr(server, "_client", fake)
    monkeypatch.setenv("RAGNAROK_MCP_AUTONOMY", autonomy)
    return fake


def test_load_example_gates_then_loads(monkeypatch) -> None:
    fake = _install(monkeypatch)
    assert asyncio.run(server.load_example("demo"))["status"] == "preview"
    assert not fake.called("load_example")
    assert asyncio.run(server.load_example("demo", confirm=True))["status"] == "loaded"
    assert fake.last("load_example") == ("load_example", "demo")


def test_secret_preview_never_echoes_the_value(monkeypatch) -> None:
    fake = _install(monkeypatch)
    out = asyncio.run(server.set_import_secret("entsoe_token", "SEKRET"))
    assert out["status"] == "preview" and "SEKRET" not in repr(out)
    assert not fake.called("put_import_secret")


def test_install_plugin_zips_a_directory(monkeypatch, tmp_path) -> None:
    fake = _install(monkeypatch, "auto")
    (tmp_path / "plug").mkdir()
    (tmp_path / "plug" / "manifest.json").write_text('{"id": "p1"}')
    (tmp_path / "plug" / "plugin.py").write_text("def analyze(r, c):\n    return {}\n")
    asyncio.run(server.install_plugin(str(tmp_path / "plug")))
    _, data, filename = fake.last("install_plugin")
    assert filename == "plug.zip"
    assert sorted(zipfile.ZipFile(io.BytesIO(data)).namelist()) == ["manifest.json", "plugin.py"]


def test_install_plugin_rejects_other_files(monkeypatch, tmp_path) -> None:
    _install(monkeypatch, "auto")
    f = tmp_path / "x.txt"
    f.write_text("no")
    assert "error" in asyncio.run(server.install_plugin(str(f)))


def test_siting_scan_uses_model_buses_and_window(monkeypatch) -> None:
    fake = _install(monkeypatch)
    out = asyncio.run(server.siting_scan(bbox=[126, 37, 128, 38]))
    assert out["status"] == "scanned" and not fake.called("apply_fragment")
    req = fake.last("siting_scan")[1]
    assert req["buses"] == [{"name": "b1", "x": 127.0, "y": 37.5}]
    assert req["targetSnapshots"] == ["2024-01-01T00:00:00", "2024-01-01T01:00:00"]


def test_siting_scan_apply_gates_then_merges(monkeypatch) -> None:
    fake = _install(monkeypatch)
    assert asyncio.run(server.siting_scan(bbox=[126, 37, 128, 38], apply=True))["status"] == "preview"
    assert not fake.called("siting_scan")
    out = asyncio.run(server.siting_scan(bbox=[126, 37, 128, 38], apply=True, confirm=True))
    assert out["status"] == "applied" and fake.called("apply_fragment")


def test_pypsa_earth_apply_replace_vs_merge(monkeypatch) -> None:
    fake = _install(monkeypatch, "auto")
    asyncio.run(server.pypsa_earth_apply("job"))
    assert fake.called("save_model") and not fake.called("apply_fragment")
    asyncio.run(server.pypsa_earth_apply("job", replace=False))
    assert fake.called("apply_fragment")


def test_submit_solve_reports_its_own_run(monkeypatch) -> None:
    fake = _install(monkeypatch, "auto")
    out = asyncio.run(server.submit_solve(timeout_s=10))
    assert out["runName"] == "mine"
    assert not fake.called("list_runs"), "must not guess the newest run"


def test_submit_solve_unstored_result_is_not_misattributed(monkeypatch) -> None:
    fake = _install(monkeypatch, "auto")
    fake.queue_job = {"id": "j1", "status": "done", "runName": None}
    out = asyncio.run(server.submit_solve(timeout_s=10))
    assert "runName" not in out and "not stored" in out["note"]
    assert not fake.called("get_analytics")
