"""Thin async HTTP client for the running Ragnarok backend.

The MCP server is a *client* of Ragnarok's REST API — it never imports backend
internals (keeps this subpackage extractable) and never spins up its own app
(the session store, queue, and runs live in the long-running uvicorn process it
talks to). One method per endpoint the tool catalog needs, plus two apply
helpers for the build/transform endpoints that *return* a model/sheets without
persisting them.

Config comes from the environment:

* ``RAGNAROK_API_BASE``   — base URL of the running backend (default ``http://127.0.0.1:8000``)
* ``RAGNAROK_SESSION_ID`` — the working-model session. Defaults to ``bifrost``,
  a dedicated agent session that won't touch the web UI's ``default`` session.
  Set it to ``default`` to share (and watch live in) the UI's working model.
* ``RAGNAROK_HTTP_TIMEOUT`` — per-request timeout seconds (default ``120``)
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import Any

import httpx

_RETRY_STATUS = {502, 503, 504}
_MAX_RETRIES = 2


class RagnarokAPIError(RuntimeError):
    """A non-2xx response from the backend, carrying its ``detail`` message."""

    def __init__(self, status: int, detail: str, *, method: str, path: str) -> None:
        self.status = status
        self.detail = detail
        super().__init__(f"{method} {path} → HTTP {status}: {detail}")


@dataclass(frozen=True)
class Config:
    api_base: str
    session_id: str
    timeout: float

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            api_base=os.environ.get(
                "RAGNAROK_API_BASE", "http://127.0.0.1:8000"
            ).rstrip("/"),
            session_id=os.environ.get("RAGNAROK_SESSION_ID", "bifrost"),
            timeout=float(os.environ.get("RAGNAROK_HTTP_TIMEOUT", "120")),
        )


class RagnarokClient:
    """Async wrapper over the Ragnarok API. One instance per server process."""

    def __init__(self, config: Config | None = None) -> None:
        self.config = config or Config.from_env()
        self._client = httpx.AsyncClient(
            base_url=self.config.api_base,
            timeout=self.config.timeout,
            headers={"User-Agent": "ragnarok-mcp/0.1", "Accept": "application/json"},
        )

    @property
    def session_id(self) -> str:
        return self.config.session_id

    async def aclose(self) -> None:
        await self._client.aclose()

    # ── low-level request with light retry/backoff on transient 5xx ────────────
    async def _request(self, method: str, path: str, **kw: Any) -> Any:
        last: Exception | None = None
        for attempt in range(_MAX_RETRIES + 1):
            try:
                resp = await self._client.request(method, path, **kw)
            except (httpx.ConnectError, httpx.ReadError) as exc:
                last = exc
                if attempt < _MAX_RETRIES:
                    await asyncio.sleep(0.5 * (attempt + 1))
                    continue
                raise RagnarokAPIError(
                    0,
                    f"cannot reach backend at {self.config.api_base} ({type(exc).__name__})",
                    method=method,
                    path=path,
                ) from exc
            if resp.status_code in _RETRY_STATUS and attempt < _MAX_RETRIES:
                await asyncio.sleep(0.5 * (attempt + 1))
                continue
            if resp.status_code >= 400:
                detail = _error_detail(resp)
                raise RagnarokAPIError(
                    resp.status_code, detail, method=method, path=path
                )
            if not resp.content:
                return {}
            return resp.json()
        raise last or RuntimeError("unreachable")

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return await self._request("GET", path, params=_clean(params))

    async def _post(self, path: str, json: dict[str, Any] | None = None) -> Any:
        return await self._request("POST", path, json=json or {})

    async def _patch(self, path: str, json: dict[str, Any]) -> Any:
        return await self._request("PATCH", path, json=json)

    def _sid_body(self, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        """A POST/PATCH body seeded with this session's ``sessionId``."""
        body: dict[str, Any] = {"sessionId": self.session_id}
        if extra:
            body.update({k: v for k, v in extra.items() if v is not None})
        return body

    # ── introspect / read-only ─────────────────────────────────────────────────
    async def list_importers(self) -> Any:
        return await self._get("/api/import/sources")

    async def source_health(self, sources: str | None = None) -> Any:
        return await self._get("/api/import/health", {"sources": sources})

    async def get_meta(self) -> Any:
        return await self._get("/api/session/meta", {"session_id": self.session_id})

    async def get_sheet_page(
        self, name: str, offset: int = 0, limit: int | None = None
    ) -> Any:
        return await self._get(
            f"/api/session/sheet/{name}",
            {"session_id": self.session_id, "offset": offset, "limit": limit},
        )

    async def get_sheet_stats(self, name: str, columns: str | None = None) -> Any:
        return await self._get(
            f"/api/session/sheet/{name}/stats",
            {"session_id": self.session_id, "columns": columns},
        )

    async def derive_series(self, name: str, mode: str, **params: Any) -> Any:
        q = {"session_id": self.session_id, "mode": mode, **params}
        return await self._get(f"/api/session/sheet/{name}/derive", q)

    async def load_full_model(
        self, static_only: bool = False
    ) -> dict[str, list[dict[str, Any]]]:
        out = await self._get(
            "/api/session/model/full",
            {"session_id": self.session_id, "staticOnly": static_only},
        )
        return out.get("model") or {}

    async def list_runs(self) -> Any:
        return await self._get("/api/runs")

    async def get_analytics(self, name: str) -> Any:
        return await self._get(f"/api/runs/{name}/analytics")

    async def get_derived(self, name: str, metric: str, **params: Any) -> Any:
        return await self._get(f"/api/runs/{name}/derived/{metric}", params)

    async def get_queue(self) -> Any:
        return await self._get("/api/queue")

    # ── model edits / transforms (each returns the API response verbatim) ──────
    async def patch_sheet(self, name: str, ops: list[dict[str, Any]]) -> Any:
        return await self._patch(
            f"/api/session/sheet/{name}", {"sessionId": self.session_id, "ops": ops}
        )

    async def retarget_snapshots(
        self, start: str, end: str, step_hours: float = 1.0, fill: str = "tile"
    ) -> Any:
        return await self._post(
            "/api/session/snapshots/retarget",
            self._sid_body(
                {"start": start, "end": end, "stepHours": step_hours, "fill": fill}
            ),
        )

    async def forecast_demand(self, from_year: int, to_year: int, **kw: Any) -> Any:
        body = self._sid_body({"fromYear": from_year, "toYear": to_year})
        body.update({k: v for k, v in kw.items() if v is not None})
        return await self._post("/api/session/snapshots/forecast", body)

    async def driver_forecast(self, from_year: int, to_year: int, **kw: Any) -> Any:
        body = self._sid_body({"fromYear": from_year, "toYear": to_year})
        body.update({k: v for k, v in kw.items() if v is not None})
        return await self._post("/api/session/snapshots/driver-forecast", body)

    async def ev_reshape_demand(self, fleet_size: float, **kw: Any) -> Any:
        body = self._sid_body({"fleetSize": fleet_size})
        body.update({k: v for k, v in kw.items() if v is not None})
        return await self._post("/api/session/snapshots/ev-demand", body)

    async def cluster_network(self, n_clusters: int, **kw: Any) -> Any:
        body = self._sid_body({"nClusters": n_clusters})
        body.update({k: v for k, v in kw.items() if v is not None})
        return await self._post("/api/transform/cluster", body)

    async def attach_renewable_profiles(self, **kw: Any) -> Any:
        return await self._post("/api/transform/renewable-profiles", self._sid_body(kw))

    async def attach_hydro_inflow(self, **kw: Any) -> Any:
        return await self._post("/api/transform/hydro-inflow", self._sid_body(kw))

    async def import_dataset(
        self,
        country_iso: str,
        dataset_ids: list[str],
        filters: dict[str, Any] | None = None,
    ) -> Any:
        return await self._post(
            "/api/import/run",
            {
                "country_iso": country_iso,
                "dataset_ids": dataset_ids,
                "filters": filters or {},
            },
        )

    async def one_click_model(self, iso3: str) -> Any:
        return await self._post(f"/api/import/location-model/{iso3}", {})

    async def build_starter_pack(self, iso3: str, year: str) -> Any:
        return await self._post(f"/api/import/starter-packs/{iso3}/{year}/build", {})

    async def submit_solve(
        self,
        scenario: dict[str, Any] | None = None,
        options: dict[str, Any] | None = None,
    ) -> Any:
        body: dict[str, Any] = {
            "sessionId": self.session_id,
            "scenario": scenario or {},
        }
        if options is not None:
            body["options"] = options
        return await self._post("/api/queue", body)

    # ── apply helpers — persist a build/transform result into the session ──────
    async def save_model(self, model: dict[str, list[dict[str, Any]]]) -> Any:
        """Replace the session's working model (used after a fresh build)."""
        return await self._post(
            "/api/session/model", {"model": model, "sessionId": self.session_id}
        )

    async def merge_sheets(self, sheets: dict[str, list[dict[str, Any]]]) -> Any:
        """Merge sheets into the current working model (used after import/transform)."""
        model = await self.load_full_model()
        model.update(sheets)
        return await self.save_model(model)


def _clean(params: dict[str, Any] | None) -> dict[str, Any] | None:
    """Drop ``None`` values so they don't serialize as the string ``"None"``."""
    if not params:
        return None
    return {k: v for k, v in params.items() if v is not None}


def _error_detail(resp: httpx.Response) -> str:
    try:
        body = resp.json()
        if isinstance(body, dict) and "detail" in body:
            return str(body["detail"])
    except Exception:  # noqa: BLE001 — non-JSON error body
        pass
    return resp.text[:500] or f"HTTP {resp.status_code}"
