"""D1 — general importer cache, provenance log, source health probes."""
from __future__ import annotations

import json
import time

import pytest

from backend.app.importers import cache as icache
from backend.app.importers import provenance_log as plog
from backend.app.importers.protocol import Provenance


@pytest.fixture(autouse=True)
def _isolated_dirs(tmp_path, monkeypatch):
    monkeypatch.setenv("RAGNAROK_IMPORT_CACHE", str(tmp_path / "cache"))
    monkeypatch.setenv("RAGNAROK_PROVENANCE_LOG", str(tmp_path / "prov.jsonl"))


# ── General cache ────────────────────────────────────────────────────────────

def test_cache_roundtrip_and_miss() -> None:
    key = {"iso": "KOR", "from": "2023-01", "to": "2023-12"}
    assert icache.cache_get("ember", key) is None
    icache.cache_put("ember", key, {"rows": [1, 2, 3]})
    assert icache.cache_get("ember", key) == {"rows": [1, 2, 3]}
    # A different key misses.
    assert icache.cache_get("ember", {**key, "to": "2024-01"}) is None


def test_cache_ttl_expiry(monkeypatch) -> None:
    key = {"k": 1}
    icache.cache_put("ember", key, "payload", ttl_days=7)
    assert icache.cache_get("ember", key) == "payload"
    # Jump 8 days ahead → expired, deleted, miss.
    real_time = time.time
    monkeypatch.setattr(time, "time", lambda: real_time() + 8 * 86400)
    assert icache.cache_get("ember", key) is None
    monkeypatch.setattr(time, "time", real_time)
    assert icache.cache_get("ember", key) is None  # stays gone after expiry


def test_cache_immutable_never_expires(monkeypatch) -> None:
    key = {"k": 2}
    icache.cache_put("glofas", key, [1.0, 2.0])  # ttl None = forever
    real_time = time.time
    monkeypatch.setattr(time, "time", lambda: real_time() + 3650 * 86400)
    assert icache.cache_get("glofas", key) == [1.0, 2.0]


def test_cache_licence_guard_blocks_ninja() -> None:
    key = {"lat": 37.5, "lon": 127.0}
    icache.cache_put("renewables_ninja", key, {"cf": [0.5]})
    assert icache.cache_get("renewables_ninja", key) is None  # never cached


# ── Provenance log ───────────────────────────────────────────────────────────

def _prov(db: str = "ember_history") -> Provenance:
    return Provenance(db, "KOR", "South Korea", json.dumps({"y": 2023}),
                      "{}", "2026-07-02T00:00:00", json.dumps({"generation_history": 12}))


def test_provenance_versions_increment_and_read_newest_first() -> None:
    e1 = plog.record_import(_prov(), source_id="ember", dataset_ids=["ember_history"])
    e2 = plog.record_import(_prov("osm"), source_id="osm", dataset_ids=["osm"])
    assert e1["version"] == 1 and e2["version"] == 2
    recent = plog.recent_imports(limit=10)
    assert [r["version"] for r in recent] == [2, 1]  # newest first
    assert recent[0]["sourceId"] == "osm"
    assert recent[1]["countryIso"] == "KOR"


def test_provenance_endpoint() -> None:
    from fastapi.testclient import TestClient

    from backend.app.main import app

    plog.record_import(_prov(), source_id="ember", dataset_ids=["ember_history"])
    c = TestClient(app)
    r = c.get("/api/import/provenance?limit=5")
    assert r.status_code == 200
    assert r.json()["imports"][0]["sourceId"] == "ember"


# ── Health probes ────────────────────────────────────────────────────────────

def test_health_probe_classification(monkeypatch) -> None:
    import asyncio

    from backend.app.importers import health

    class _Resp:
        def __init__(self, status: int) -> None:
            self.status_code = status

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, follow_redirects=True):
            if "down" in url:
                raise ConnectionError("no route")
            if "auth" in url:
                return _Resp(401)
            if "broken" in url:
                return _Resp(503)
            return _Resp(200)

    monkeypatch.setattr(health.httpx, "AsyncClient", lambda **kw: _Client())
    monkeypatch.setattr(health, "HEALTH_PROBES", {
        "up": "https://x/ok", "keyed": "https://x/auth",
        "err": "https://x/broken", "dead": "https://x/down",
    })
    out = asyncio.run(health.check_sources())
    assert out["up"]["ok"] is True and out["up"]["status"] == 200
    assert out["keyed"]["ok"] is True and out["keyed"]["status"] == 401   # up, needs key
    assert out["err"]["ok"] is False and out["err"]["status"] == 503
    assert out["dead"]["ok"] is False and out["dead"]["error"] == "ConnectionError"


def test_health_endpoint_filters_sources(monkeypatch) -> None:
    import asyncio as _a

    from fastapi.testclient import TestClient

    from backend.app.importers import health
    from backend.app.main import app

    async def fake_check(ids=None):
        return {i: {"ok": True} for i in (ids or ["all"])}

    monkeypatch.setattr(health, "check_sources", fake_check)
    c = TestClient(app)
    r = c.get("/api/import/health?sources=osm,ember")
    assert r.status_code == 200
    assert set(r.json()["sources"]) == {"osm", "ember"}
    _ = _a  # silence unused in case of refactor
