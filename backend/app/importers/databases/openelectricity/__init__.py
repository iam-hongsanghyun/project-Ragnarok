"""OpenElectricity (Australia) — hourly demand & renewable profiles (BYOK).

OpenElectricity (the platform formerly served at OpenNEM) exposes Australia's
NEM and WEM market data through a keyed REST API. Two datasets share the source:

  • demand  — the network's hourly operational demand → a Load + loads-p_set.
  • renewable profiles — hourly generation per fuel-tech group, peak-normalised
    into ``generators-p_max_pu`` for the variable-renewable techs (solar, wind).

Both call ``GET /v4/data/network/{network}`` with a Bearer token
(``openelectricity_key``). Timestamps come back in the network's local timezone;
we keep local wall-clock snapshots (so the diurnal shape lines up with local
demand). Get a free key at platform.openelectricity.org.au → Settings → API.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from ...context import ImportContext
from ...protocol import (
    ConvertOptions,
    Database,
    DatabaseMeta,
    FetchResult,
    Filter,
    PreviewSummary,
    Provenance,
    Region,
    WorkbookFragment,
)

_API = "https://api.openelectricity.org.au/v4"
_SOURCE_ID = "openelectricity"
_SOURCE_LABEL = "OpenElectricity (Australia, BYOK)"
_SECRET = "openelectricity_key"

# fueltech_group → PyPSA carrier, for the variable renewables we profile.
_VRE_FUELTECH = {"solar": "solar", "wind": "wind"}

_NETWORK_FILTER = Filter(
    id="network", label="Market", kind="select", default="NEM",
    options=[
        {"value": "NEM", "label": "NEM — National Electricity Market (east)"},
        {"value": "WEM", "label": "WEM — Wholesale Electricity Market (WA)"},
    ],
    description="Which Australian market to pull. The NEM covers the eastern states; "
                "the WEM covers south-west Western Australia.",
)
_DATE_FILTERS = [
    Filter(id="date_from", label="From", kind="date", default="2024-01-01",
           description="Start of the hourly window (inclusive, network-local time)."),
    Filter(id="date_to", label="To", kind="date", default="2024-01-07",
           description="End of the hourly window (inclusive). Keep it short — hourly data is large."),
]


def _network(filters: dict[str, Any]) -> str:
    net = str(filters.get("network") or "NEM").upper()
    return net if net in ("NEM", "WEM") else "NEM"


def _snapshot(ts: str) -> str:
    """OpenElectricity ISO stamp (``2024-09-01T00:00:00+10:00``) → local
    ``YYYY-MM-DD HH:00`` (offset dropped — keep local wall-clock)."""
    s = str(ts)
    return f"{s[0:10]} {s[11:13]}:00" if len(s) >= 13 else s


def _results_by_label(body: Any, metric: str, label_key: str | None) -> dict[str, list[tuple[str, float]]]:
    """Fold an APIV4 TimeSeries response into ``{label: [(snapshot, value)]}``.

    ``label_key`` selects the grouping column (e.g. ``fueltech_group``); when
    None every result folds under the metric name (a single ungrouped series).
    """
    out: dict[str, list[tuple[str, float]]] = {}
    for ts in (body or {}).get("data") or []:
        if metric and ts.get("metric") not in (metric, None):
            continue
        for res in ts.get("results") or []:
            cols = res.get("columns") or {}
            label = str(cols.get(label_key)) if label_key else metric
            if not label or label == "None":
                label = str(res.get("name") or metric)
            bucket = out.setdefault(label, [])
            for point in res.get("data") or []:
                if not isinstance(point, list) or len(point) < 2:
                    continue
                stamp, value = point[0], point[1]
                if value is None:
                    continue
                try:
                    bucket.append((_snapshot(str(stamp)), float(value)))
                except (TypeError, ValueError):
                    continue
    return out


async def _fetch(ctx: ImportContext, network: str, metrics: str, date_from: str, date_to: str,
                 extra: dict[str, str]) -> Any:
    token = ctx.require_secret(_SECRET)
    params = {
        "metrics": metrics, "interval": "1h",
        "date_start": f"{date_from}T00:00:00", "date_end": f"{date_to}T00:00:00",
        **extra,
    }
    try:
        return await ctx.http.get_json(
            f"{_API}/data/network/{network}", params=params,
            headers={"Authorization": f"Bearer {token}"},
        )
    except RuntimeError as exc:
        msg = str(exc)
        if "401" in msg or "403" in msg:
            raise PermissionError(
                "OpenElectricity rejected the API token. Check "
                f"'{_SECRET}' in Settings → API keys."
            ) from None
        raise RuntimeError(f"OpenElectricity request failed ({msg}).") from None


def _au_bus(region: Region, network: str) -> dict[str, Any]:
    try:
        c = region.polygon.centroid
        x, y = float(c.x), float(c.y)
    except Exception:
        x, y = 134.0, -25.0  # roughly central Australia
    return {"name": network, "x": x, "y": y, "carrier": "AC", "country": "AUS",
            "source": "OpenElectricity"}


# ── Demand dataset ────────────────────────────────────────────────────────────
_DEMAND_META = DatabaseMeta(
    id="openelectricity_demand",
    name="OpenElectricity — Australian hourly demand",
    short_name="AU demand",
    source_id=_SOURCE_ID, source_label=_SOURCE_LABEL,
    category="demand", subcategory="Hourly profiles",
    license="OpenElectricity API (free key, CC-BY-4.0 data)",
    homepage="https://openelectricity.org.au/",
    version_hint="OpenElectricity API v4",
    description=(
        "Hourly operational demand for the Australian NEM or WEM from the "
        "OpenElectricity API. Lands one network bus + a Load + hourly loads-p_set "
        "(network-local time). Needs a free OpenElectricity API key (Settings → API keys)."
    ),
    targets=["buses", "loads", "loads-p_set", "carriers"],
    country_coverage=["AUS"], requires_secrets=[_SECRET],
    filters=[_NETWORK_FILTER, *_DATE_FILTERS],
)


class OpenElectricityDemand:
    meta = _DEMAND_META

    async def fetch(self, region: Region, filters: dict[str, Any], ctx: ImportContext) -> FetchResult:
        net = _network(filters)
        df, dt = str(filters.get("date_from") or "2024-01-01"), str(filters.get("date_to") or "2024-01-07")
        body = await _fetch(ctx, net, "demand", df, dt, {"primary_grouping": "network"})
        series = _results_by_label(body, "demand", None)
        hourly = next(iter(series.values()), [])
        hourly.sort()
        return FetchResult(_DEMAND_META.id, region, dict(filters), {"network": net, "hourly": hourly})

    def preview(self, result: FetchResult) -> PreviewSummary:
        hourly = result.payload["hourly"]
        vals = [v for _, v in hourly]
        counts = {"loads": 1 if hourly else 0, "hours": len(hourly)}
        if vals:
            counts["peak_mw"] = int(round(max(vals)))
            counts["mean_mw"] = int(round(sum(vals) / len(vals)))
        return PreviewSummary(
            counts=counts,
            samples={"hours": [{"snapshot": s, "mw": round(v, 1)} for s, v in hourly[:24]]},
            notes=[f"{result.payload['network']}: {len(hourly)} hourly demand points (local time)."],
        )

    def to_sheets(self, result: FetchResult, options: ConvertOptions) -> WorkbookFragment:
        hourly = result.payload["hourly"]
        net = result.payload["network"]
        frag = WorkbookFragment()
        if hourly:
            load = f"{net}_demand"
            frag.sheets["carriers"] = [{"name": "AC"}]
            frag.sheets["buses"] = [_au_bus(result.region, net)]
            frag.sheets["loads"] = [{"name": load, "bus": net, "carrier": "AC", "country": "AUS",
                                     "source": "OpenElectricity (operational demand)"}]
            frag.sheets["loads-p_set"] = [{"snapshot": s, load: v} for s, v in hourly]
            frag.snapshots = [s for s, _ in hourly]
        frag.provenance = _prov(_DEMAND_META.id, result, options, frag)
        return frag


# ── Renewable-profiles dataset ────────────────────────────────────────────────
_GEN_META = DatabaseMeta(
    id="openelectricity_renewable",
    name="OpenElectricity — Australian measured renewable profiles",
    short_name="AU renewable profiles",
    source_id=_SOURCE_ID, source_label=_SOURCE_LABEL,
    depends_on=["openelectricity_demand"],
    category="generation", subcategory="Hourly profiles",
    license="OpenElectricity API (free key, CC-BY-4.0 data)",
    homepage="https://openelectricity.org.au/",
    version_hint="OpenElectricity API v4",
    description=(
        "Measured hourly solar & wind capacity-factor profiles for the Australian "
        "NEM/WEM — actual generation per fuel-tech group, peak-normalised into "
        "generators-p_max_pu. Lands aggregate solar/wind generators on the network "
        "bus. Needs a free OpenElectricity API key (Settings → API keys)."
    ),
    targets=["buses", "carriers", "generators", "generators-p_max_pu"],
    country_coverage=["AUS"], requires_secrets=[_SECRET],
    filters=[_NETWORK_FILTER, *_DATE_FILTERS],
)


class OpenElectricityRenewable:
    meta = _GEN_META

    async def fetch(self, region: Region, filters: dict[str, Any], ctx: ImportContext) -> FetchResult:
        net = _network(filters)
        df, dt = str(filters.get("date_from") or "2024-01-01"), str(filters.get("date_to") or "2024-01-07")
        body = await _fetch(ctx, net, "power", df, dt, {"secondary_grouping": "fueltech_group"})
        series = _results_by_label(body, "power", "fueltech_group")
        gen = {carrier: sorted(series[grp]) for grp, carrier in _VRE_FUELTECH.items() if series.get(grp)}
        return FetchResult(_GEN_META.id, region, dict(filters), {"network": net, "gen": gen})

    def _profiles(self, result: FetchResult) -> tuple[list[dict], list[str], list[dict], list[str]]:
        net = result.payload["network"]
        gen: dict[str, list[tuple[str, float]]] = result.payload["gen"]
        snaps = sorted({s for series in gen.values() for s, _ in series})
        gen_rows: list[dict] = []
        cf_by_gen: dict[str, dict[str, float]] = {}
        notes: list[str] = []
        for carrier, series in gen.items():
            peak = max((v for _, v in series), default=0.0)
            if peak <= 0:
                continue
            name = f"{net}_{carrier}"
            cf_by_gen[name] = {s: max(0.0, min(1.0, v / peak)) for s, v in series}
            gen_rows.append({"name": name, "bus": net, "carrier": carrier,
                             "p_nom": round(peak, 3), "p_min_pu": 0, "p_max_pu": 1,
                             "source": "OpenElectricity (measured generation, peak-normalised)"})
            mean = sum(cf_by_gen[name].values()) / len(cf_by_gen[name]) if cf_by_gen[name] else 0.0
            notes.append(f"{carrier}: mean CF ≈ {mean:.2f} (÷ window peak).")
        rows = [
            {"snapshot": s, **{n: round(cf[s], 4) for n, cf in cf_by_gen.items() if s in cf}}
            for s in snaps
        ]
        return gen_rows, snaps, rows, notes

    def preview(self, result: FetchResult) -> PreviewSummary:
        gen_rows, snaps, _rows, notes = self._profiles(result)
        return PreviewSummary(
            counts={"generators": len(gen_rows), "hours": len(snaps)},
            samples={"generators": [{"name": g["name"], "carrier": g["carrier"]} for g in gen_rows]},
            notes=[f"{result.payload['network']}: {len(gen_rows)} renewable carrier(s), {len(snaps)} hours.", *notes],
        )

    def to_sheets(self, result: FetchResult, options: ConvertOptions) -> WorkbookFragment:
        gen_rows, snaps, rows, _notes = self._profiles(result)
        frag = WorkbookFragment()
        if gen_rows and snaps:
            frag.sheets["carriers"] = [{"name": "AC"}] + [{"name": c} for c in sorted({g["carrier"] for g in gen_rows})]
            frag.sheets["buses"] = [_au_bus(result.region, result.payload["network"])]
            frag.sheets["generators"] = gen_rows
            frag.sheets["generators-p_max_pu"] = rows
            frag.snapshots = snaps
        frag.provenance = _prov(_GEN_META.id, result, options, frag)
        return frag


def _prov(db_id: str, result: FetchResult, options: ConvertOptions, frag: WorkbookFragment) -> Provenance:
    return Provenance(
        db_id, result.region.country_iso, result.region.country_name,
        json.dumps(result.filters, sort_keys=True, default=str),
        json.dumps(options.__dict__, sort_keys=True, default=str),
        datetime.now(timezone.utc).isoformat(timespec="seconds"),
        json.dumps({s: len(r) for s, r in frag.sheets.items()}, sort_keys=True),
    )


def build() -> Database:
    return OpenElectricityDemand()


def build_renewable() -> Database:
    return OpenElectricityRenewable()
