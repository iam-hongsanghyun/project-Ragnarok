"""Shared async HTTP client for importer upstream fetches.

One ``httpx.AsyncClient`` per request context, wrapped with:

  • retry + exponential backoff on 429 / 5xx,
  • a sane User-Agent (Overpass and a few others 406 a missing one),
  • secret masking in any error message we raise (so a key never lands
    in the log buffer via an exception string).

The wrapper exposes ``get_text`` / ``get_json`` / ``post_text`` — the
small surface the importer modules actually need.
"""
from __future__ import annotations

import asyncio
from typing import Any

import httpx


DEFAULT_UA = "Ragnarok/0.1 (+https://github.com/PyPSA/PyPSA)"
DEFAULT_TIMEOUT = 180.0
DEFAULT_RETRIES = 3


def _mask(text: str, secrets: list[str]) -> str:
    out = text
    for s in secrets:
        if s:
            out = out.replace(s, "***")
    return out


class AsyncClientWrapper:
    """Thin retrying wrapper over httpx.AsyncClient."""

    def __init__(self, secrets: list[str] | None = None) -> None:
        self._secrets = [s for s in (secrets or []) if s]
        self._client = httpx.AsyncClient(
            timeout=DEFAULT_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": DEFAULT_UA, "Accept": "*/*"},
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        retries: int = DEFAULT_RETRIES,
    ) -> httpx.Response:
        backoff = 2.0
        last: Exception | None = None
        for attempt in range(1, retries + 1):
            try:
                resp = await self._client.request(
                    method, url, params=params, data=data, headers=headers
                )
                if resp.status_code in (429, 502, 503, 504) and attempt < retries:
                    await asyncio.sleep(backoff * attempt)
                    continue
                resp.raise_for_status()
                return resp
            except httpx.HTTPStatusError as exc:
                last = exc
                # 4xx (other than the retryable above) are terminal.
                raise RuntimeError(
                    _mask(
                        f"HTTP {exc.response.status_code} for "
                        f"{_mask(url, self._secrets)}",
                        self._secrets,
                    )
                ) from None
            except (httpx.TransportError, httpx.TimeoutException) as exc:
                last = exc
                if attempt < retries:
                    await asyncio.sleep(backoff * attempt)
                    continue
        raise RuntimeError(
            _mask(f"request failed for {url}: {last}", self._secrets)
        )

    async def get_text(
        self, url: str, *, params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> str:
        resp = await self._request("GET", url, params=params, headers=headers)
        return resp.text

    async def get_bytes(
        self, url: str, *, params: dict[str, Any] | None = None,
    ) -> bytes:
        resp = await self._request("GET", url, params=params)
        return resp.content

    async def get_json(
        self, url: str, *, params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        resp = await self._request("GET", url, params=params, headers=headers)
        return resp.json()

    async def post_text(
        self, url: str, *, data: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> str:
        resp = await self._request("POST", url, data=data, headers=headers)
        return resp.text
