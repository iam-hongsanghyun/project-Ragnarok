"""Siting — power-system location optimisation as capacity expansion.

Location optimisation in PyPSA is capacity expansion with a *spatial* candidate
set: put an extendable, zero-capacity generator at every candidate site (each
with its own weather-driven capacity-factor profile and its own grid-connection
cost) and let the ordinary expansion LP decide where — and how much — to build.
Sites that end the solve at zero built capacity are rejected locations.

This package holds the pure candidate maths (:mod:`.core`): grid sampling over
a bounding box, nearest-bus assignment via haversine distance, and conversion
of fetched per-site weather into a :class:`~backend.app.importers.protocol.
WorkbookFragment` of extendable candidate assets. Weather fetching reuses the
Open-Meteo importer's cached ``fetch_point`` (keyless, any coordinate); the
HTTP surface is ``POST /api/siting/scan`` (see ``app/routers/siting.py``).
"""
from .core import (
    MAX_CANDIDATES,
    build_siting_fragment,
    haversine_km,
    nearest_bus,
    sample_grid,
)

__all__ = [
    "MAX_CANDIDATES",
    "build_siting_fragment",
    "haversine_km",
    "nearest_bus",
    "sample_grid",
]
