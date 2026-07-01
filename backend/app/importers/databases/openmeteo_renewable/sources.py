"""Weather sources for renewable capacity factors (I4).

Each adapter fetches one point and returns a normalised
``{"time": [...], "ghi": [W/m²], "wind_ms": [m/s @100m]}`` dict so the rest of
the pipeline (conversion, importer, attach transform) is source-agnostic. Wind is
extrapolated to a 100 m hub height with the 1/7 power law when the source reports
a lower measurement height. Timestamps are normalised to ``"YYYY-MM-DD HH:MM"``.

Sources:
  • open-meteo — global ERA5, keyless (the default).
  • pvgis      — EU JRC SARAH/ERA5, keyless; GHI = Gb(i)+Gd(i)+Gr(i), wind @10 m.
  • nasa-power — NASA POWER, keyless; ALLSKY_SFC_SW_DWN (Wh/m² ≡ W/m² hourly),
                 wind @50 m.
"""
from __future__ import annotations

from typing import Any

from .conversion import combined_ghi

_HUB_HEIGHT = 100.0
_WIND_ALPHA = 1.0 / 7.0  # 1/7 power-law shear exponent


def _extrapolate_wind(speeds: list[Any], from_height: float) -> list[float]:
    """Scale wind speeds from ``from_height`` to the 100 m hub height."""
    factor = (_HUB_HEIGHT / from_height) ** _WIND_ALPHA
    out: list[float] = []
    for v in speeds:
        try:
            f = float(v)
        except (TypeError, ValueError):
            out.append(0.0)
            continue
        out.append(0.0 if f <= -900 else f * factor)  # NASA uses -999 for missing
    return out


# ── Open-Meteo (default, keyless, global ERA5) ────────────────────────────────
_OM_URL = "https://archive-api.open-meteo.com/v1/archive"
_OM_VARS = "shortwave_radiation,direct_radiation,diffuse_radiation,wind_speed_100m"


async def open_meteo(http: Any, lat: float, lon: float, date_from: str, date_to: str, secret: str | None) -> dict[str, Any]:
    body = await http.get_json(_OM_URL, params={
        "latitude": lat, "longitude": lon, "start_date": date_from, "end_date": date_to,
        "hourly": _OM_VARS, "wind_speed_unit": "ms", "timezone": "UTC",
    })
    h = (body or {}).get("hourly") or {}
    return {
        "time": [str(t).replace("T", " ") for t in (h.get("time") or [])],
        "ghi": combined_ghi(h.get("shortwave_radiation"), h.get("direct_radiation"), h.get("diffuse_radiation")),
        "wind_ms": [None if v is None else float(v) for v in (h.get("wind_speed_100m") or [])],
    }


# ── PVGIS (EU JRC, keyless) ───────────────────────────────────────────────────
_PVGIS_URL = "https://re.jrc.ec.europa.eu/api/v5_2/seriescalc"


def _pvgis_time(t: str) -> str:
    # "20200101:1210" → "2020-01-01 12:00" (snap the satellite :10 to the hour)
    s = str(t)
    return f"{s[0:4]}-{s[4:6]}-{s[6:8]} {s[9:11]}:00"


async def pvgis(http: Any, lat: float, lon: float, date_from: str, date_to: str, secret: str | None) -> dict[str, Any]:
    y0, y1 = int(date_from[:4]), int(date_to[:4])
    body = await http.get_json(_PVGIS_URL, params={
        "lat": lat, "lon": lon, "startyear": y0, "endyear": y1,
        "outputformat": "json", "pvcalculation": 0, "components": 1,
        "angle": 0, "aspect": 0,  # horizontal plane → GHI
    })
    hourly = (((body or {}).get("outputs") or {}).get("hourly")) or []
    times = [_pvgis_time(r.get("time", "")) for r in hourly]
    ghi = [
        float(r.get("Gb(i)") or 0.0) + float(r.get("Gd(i)") or 0.0) + float(r.get("Gr(i)") or 0.0)
        for r in hourly
    ]
    wind = _extrapolate_wind([r.get("WS10m") for r in hourly], from_height=10.0)
    kept = _clip_to_range(times, ghi, wind, date_from, date_to)
    return kept


# ── NASA POWER (keyless, global) ──────────────────────────────────────────────
_NASA_URL = "https://power.larc.nasa.gov/api/temporal/hourly/point"


def _nasa_time(k: str) -> str:
    # "2020060110" → "2020-06-01 10:00"
    return f"{k[0:4]}-{k[4:6]}-{k[6:8]} {k[8:10]}:00"


async def nasa_power(http: Any, lat: float, lon: float, date_from: str, date_to: str, secret: str | None) -> dict[str, Any]:
    body = await http.get_json(_NASA_URL, params={
        "parameters": "ALLSKY_SFC_SW_DWN,WS50M", "community": "RE",
        "latitude": lat, "longitude": lon,
        "start": date_from.replace("-", ""), "end": date_to.replace("-", ""),
        "format": "JSON",
    })
    param = (((body or {}).get("properties") or {}).get("parameter")) or {}
    ghi_map = param.get("ALLSKY_SFC_SW_DWN") or {}
    ws_map = param.get("WS50M") or {}
    keys = sorted(ghi_map.keys())
    times = [_nasa_time(k) for k in keys]
    ghi = [max(0.0, float(ghi_map[k])) if float(ghi_map[k]) > -900 else 0.0 for k in keys]
    wind = _extrapolate_wind([ws_map.get(k) for k in keys], from_height=50.0)
    return {"time": times, "ghi": ghi, "wind_ms": wind}


def _clip_to_range(times: list[str], ghi: list[float], wind: list[float], date_from: str, date_to: str) -> dict[str, Any]:
    """Keep only hours within [date_from, date_to] (PVGIS returns whole years)."""
    lo, hi = date_from[:10], date_to[:10]
    out_t: list[str] = []
    out_g: list[float] = []
    out_w: list[float] = []
    for t, g, w in zip(times, ghi, wind):
        if lo <= t[:10] <= hi:
            out_t.append(t)
            out_g.append(g)
            out_w.append(w)
    return {"time": out_t, "ghi": out_g, "wind_ms": out_w}


# Source registry. ``requires_secret`` names a BYOK key (none are keyless-only here).
SOURCES: dict[str, Any] = {
    "open-meteo": open_meteo,
    "pvgis": pvgis,
    "nasa-power": nasa_power,
}
SOURCE_SECRET: dict[str, str] = {}  # keyless sources only for now
DEFAULT_SOURCE = "open-meteo"
