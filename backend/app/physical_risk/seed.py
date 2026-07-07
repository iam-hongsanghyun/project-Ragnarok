"""Seed a physical-risk :class:`Portfolio` from a Ragnarok PyPSA model dict.

Pure and testable: no I/O, no store access. One :class:`Asset` per generator and
per storage_unit, located at its bus ``x`` (lon) / ``y`` (lat). Units whose bus
lacks coordinates are skipped (flagged in the returned notes).
"""
from __future__ import annotations

import math
from typing import Any

from pydantic import ValidationError

from .entities import Asset, Portfolio, VulnerabilityClass

# carrier substring -> vulnerability class. First match wins; DEFAULT otherwise.
# Keeps the fuel taxonomy small and obvious — refined by the real library later.
_CARRIER_CLASS_RULES: tuple[tuple[str, str], ...] = (
    ("wind", VulnerabilityClass.RENEWABLE.value),
    ("solar", VulnerabilityClass.RENEWABLE.value),
    ("pv", VulnerabilityClass.RENEWABLE.value),
    ("hydro", VulnerabilityClass.HYDRO.value),
    ("ror", VulnerabilityClass.HYDRO.value),
    ("run_of_river", VulnerabilityClass.HYDRO.value),
    ("coal", VulnerabilityClass.THERMAL.value),
    ("lignite", VulnerabilityClass.THERMAL.value),
    ("gas", VulnerabilityClass.THERMAL.value),
    ("ocgt", VulnerabilityClass.THERMAL.value),
    ("ccgt", VulnerabilityClass.THERMAL.value),
    ("oil", VulnerabilityClass.THERMAL.value),
    ("nuclear", VulnerabilityClass.THERMAL.value),
    ("biomass", VulnerabilityClass.THERMAL.value),
    ("geothermal", VulnerabilityClass.THERMAL.value),
    ("battery", VulnerabilityClass.GRID.value),
    ("storage", VulnerabilityClass.GRID.value),
    ("h2", VulnerabilityClass.GRID.value),
    ("hydrogen", VulnerabilityClass.GRID.value),
)


def vulnerability_class_for(carrier: str) -> str:
    """Map a PyPSA carrier to a vulnerability-class id (DEFAULT when unmatched)."""
    c = (carrier or "").strip().lower()
    for needle, vclass in _CARRIER_CLASS_RULES:
        if needle in c:
            return vclass
    return VulnerabilityClass.DEFAULT.value


def _num(value: Any) -> float | None:
    """Coerce a cell to a finite float, or None if blank / non-numeric / NaN / inf."""
    if value is None or value == "":
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _bus_coords(model: dict[str, list[dict[str, Any]]]) -> dict[str, tuple[float, float]]:
    """Map bus name -> (lon, lat) for buses carrying valid WGS84 ``x``/``y``.

    Buses whose coordinates fall outside the geographic range (e.g. a projected
    CRS in metres, as some PyPSA-Eur workflows store) are treated as
    unplaceable and dropped here — their units are then skipped and flagged
    downstream, rather than crashing the seed on the ``Asset`` lat/lon bounds.
    """
    coords: dict[str, tuple[float, float]] = {}
    for row in model.get("buses", []) or []:
        name = str(row.get("name", "")).strip()
        if not name:
            continue
        lon = _num(row.get("x"))
        lat = _num(row.get("y"))
        if lon is None or lat is None:
            continue
        if not (-180.0 <= lon <= 180.0 and -90.0 <= lat <= 90.0):
            continue
        coords[name] = (lon, lat)
    return coords


def _asset_value(row: dict[str, Any], default_value_per_mw: float) -> float:
    """Asset value at risk.

    ``capital_cost * p_nom`` when both present and > 0, else
    ``default_value_per_mw * p_nom``. Falls back to 0 when p_nom is missing or
    negative (a negative rating is meaningless for value-at-risk, and a negative
    value would violate ``Asset.value``'s ``ge=0`` bound).
    """
    p_nom = max(0.0, _num(row.get("p_nom")) or 0.0)
    capital_cost = _num(row.get("capital_cost"))
    if capital_cost is not None and capital_cost > 0 and p_nom > 0:
        return round(capital_cost * p_nom, 2)
    return round(max(0.0, default_value_per_mw) * p_nom, 2)


def _assets_from_sheet(
    model: dict[str, list[dict[str, Any]]],
    sheet: str,
    kind: str,
    coords: dict[str, tuple[float, float]],
    *,
    default_value_per_mw: float,
    currency: str,
    notes: list[str],
) -> list[Asset]:
    """Build one Asset per row of ``sheet`` that has a resolvable bus location."""
    assets: list[Asset] = []
    for row in model.get(sheet, []) or []:
        name = str(row.get("name", "")).strip()
        if not name:
            continue
        bus = str(row.get("bus", "")).strip()
        loc = coords.get(bus)
        if loc is None:
            notes.append(f"{kind} '{name}' skipped: bus '{bus}' has no x/y coordinates.")
            continue
        lon, lat = loc
        carrier = str(row.get("carrier", "")).strip()
        try:
            asset = Asset(
                name=name,
                kind=kind,
                lat=lat,
                lon=lon,
                value=_asset_value(row, default_value_per_mw),
                currency=currency,
                vulnerabilityClass=vulnerability_class_for(carrier),
                carrier=carrier,
            )
        except ValidationError:
            # Belt-and-suspenders: one malformed row must never 500 the whole
            # seed — skip it and flag, consistent with the missing-coord path.
            notes.append(f"{kind} '{name}' skipped: could not build a valid asset from its row.")
            continue
        assets.append(asset)
    return assets


def portfolio_from_model(
    model: dict[str, list[dict[str, Any]]],
    *,
    default_value_per_mw: float,
    currency: str,
) -> tuple[Portfolio, list[str]]:
    """Map a Ragnarok PyPSA model dict onto a physical-risk :class:`Portfolio`.

    One :class:`Asset` per generator and per storage_unit. Returns the portfolio
    plus a list of human-readable notes for units that could not be placed.
    """
    coords = _bus_coords(model)
    notes: list[str] = []
    assets: list[Asset] = []
    assets += _assets_from_sheet(
        model, "generators", "generator", coords,
        default_value_per_mw=default_value_per_mw, currency=currency, notes=notes,
    )
    assets += _assets_from_sheet(
        model, "storage_units", "storage", coords,
        default_value_per_mw=default_value_per_mw, currency=currency, notes=notes,
    )
    return Portfolio(assets=assets), notes
