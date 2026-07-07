"""Modeled-exposure builders — turn a country into a gridded CLIMADA ``Exposures``.

The platform's default exposure is the user's hand-placed point assets. This module
adds the *modeled* exposure sources CLIMADA / climada_petals can synthesise for a whole
country, so an impact run does not need a hand-built portfolio:

  - ``litpop``      LitPop nightlight × population value grid (CLIMADA).
  - ``blackmarble`` BlackMarble nightlight-only value grid (climada_petals).
  - ``gdp``         GDP2Asset gridded GDP-to-asset value (climada_petals).
  - ``crop``        CropProduction agricultural exposure (climada_petals, ISIMIP/SPAM).
  - ``osm``         OpenStreetMap building footprints (climada_petals osm-flex).

Most need external data that is login-gated (GPW for LitPop, BlackMarble tiles),
large (OSM ``.osm.pbf`` extracts), or scenario-specific (ISIMIP crop NetCDF). When the
data is absent we raise :class:`ExposureUnavailable` with an actionable message — the
same graceful-degradation contract the rest of the platform uses — instead of failing
opaquely. CLIMADA itself is imported lazily so this module stays importable (and its
help text testable) without the worker env.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

# Actionable "where to get the data" help per source. Kept climada-free at module level
# so the registry and messages are importable/testable without the CLIMADA worker env.
EXPOSURE_HELP: dict[str, str] = {
    "litpop": (
        "LitPop needs the GPW v4 population GeoTIFF (free NASA Earthdata login, no "
        "auto-download). Get gpw-v4-population-count-rev11_2020_30_sec_tif.zip from "
        "https://sedac.ciesin.columbia.edu/data/collection/gpw-v4 and unzip under "
        "~/climada/data/, then re-run."
    ),
    "blackmarble": (
        "BlackMarble needs NASA Black Marble nightlight tiles and the GPW population "
        "layer (Earthdata login). CLIMADA fetches the nightlights on first use; if that "
        "fails, download them manually into ~/climada/data/ and re-run."
    ),
    "gdp": (
        "GDP2Asset needs a gridded GDP NetCDF (e.g. the ISIMIP/Geiger asset-value grid). "
        "Place it under ~/climada/data/ and set the GDP2Asset path, then re-run."
    ),
    "crop": (
        "CropProduction needs an ISIMIP crop NetCDF (e.g. histsoc yield/area) or the "
        "SPAM raster. Download the ISIMIP product, drop it under ~/climada/data/, and "
        "use the crop-production importer; this source cannot be auto-fetched."
    ),
    "osm": (
        "OSM building exposure needs an OpenStreetMap extract: download a country "
        ".osm.pbf from https://download.geofabrik.de/ (open, no login) into "
        "~/climada/data/osm/, then re-run. Large countries can be multi-GB."
    ),
    "raster": (
        "No population/value raster found for this country. Use the Data tab to download "
        "WorldPop 1 km population for the portfolio's country (it lands in ~/climada/data), "
        "or drop a GeoTIFF there and set CLIMATERISK_EXPOSURE_RASTER, then re-run."
    ),
}

# Display metadata for the UI / result payloads.
EXPOSURE_SOURCES: dict[str, dict[str, str]] = {
    "litpop": {"label": "LitPop (nightlight × population)", "engine": "climada.LitPop"},
    "blackmarble": {"label": "BlackMarble (nightlights)", "engine": "petals.BlackMarble"},
    "gdp": {"label": "GDP2Asset (gridded GDP)", "engine": "petals.GDP2Asset"},
    "crop": {"label": "Crop production (ISIMIP/SPAM)", "engine": "petals.CropProduction"},
    "osm": {"label": "OSM buildings (osm-flex)", "engine": "petals.openstreetmap"},
    "raster": {
        "label": "Population/value raster (WorldPop/GHSL)",
        "engine": "climada.Exposures.from_raster",
    },
}

_HOME_CLIMADA = Path.home() / "climada" / "data"


def _resolve_exposure_raster(country: str) -> Path | None:
    """Find a population/value GeoTIFF for the modeled-exposure 'raster' source.

    Resolution order: explicit ``CLIMATERISK_EXPOSURE_RASTER`` env path → the WorldPop
    1 km file the Data tab downloads (``<iso3>_ppp_2020_1km_Aggregated.tif``) under
    ~/climada/data. Returns None if nothing is present (caller degrades gracefully).
    """
    import os

    explicit = os.environ.get("CLIMATERISK_EXPOSURE_RASTER")
    if explicit and Path(explicit).is_file():
        return Path(explicit)
    worldpop = _HOME_CLIMADA / f"{country.lower()}_ppp_2020_1km_Aggregated.tif"
    if worldpop.is_file():
        return worldpop
    return None


class ExposureUnavailable(Exception):
    """Raised when a modeled-exposure source's data is missing; carries actionable help."""

    def __init__(self, source: str, detail: str | None = None) -> None:
        self.source = source
        self.detail = detail or EXPOSURE_HELP.get(source, f"exposure source '{source}' unavailable")
        super().__init__(self.detail)


def build_exposure(source: str, country: str, res_arcsec: int = 300) -> Any:
    """Build a gridded CLIMADA ``Exposures`` for ``country`` from a modeled source.

    Args:
        source: one of :data:`EXPOSURE_SOURCES` keys.
        country: ISO3 country code.
        res_arcsec: target grid resolution (arc-seconds) where the source supports it.

    Returns:
        A CLIMADA ``Exposures`` with a ``value`` column.

    Raises:
        ExposureUnavailable: when the source is unknown or its data is absent.
    """
    if source not in EXPOSURE_SOURCES:
        raise ExposureUnavailable(source, f"unknown exposure source '{source}'")

    # Sources that require an explicit local data file we cannot synthesise here: fail fast
    # with the actionable message rather than a doomed call deep inside the library.
    if source in ("crop", "osm"):
        raise ExposureUnavailable(source)

    try:
        if source == "litpop":
            from climada.entity import LitPop

            return LitPop.from_countries(country, res_arcsec=res_arcsec)
        if source == "blackmarble":
            from climada_petals.entity.exposures.black_marble import BlackMarble

            exp = BlackMarble()
            exp.set_countries([country])
            return exp
        if source == "gdp":
            from climada_petals.entity.exposures.gdp_asset import GDP2Asset

            exp = GDP2Asset()
            exp.set_countries(countries=[country], res_arcsec=res_arcsec)
            return exp
        if source == "raster":
            raster = _resolve_exposure_raster(country)
            if raster is None:
                raise ExposureUnavailable("raster")  # actionable: no raster on disk
            from climada.entity import Exposures

            return Exposures.from_raster(str(raster))
    except ExposureUnavailable:
        raise
    except (FileNotFoundError, OSError) as exc:
        raise ExposureUnavailable(source, f"{EXPOSURE_HELP[source]} ({str(exc)[:120]})") from exc
    except Exception as exc:  # library-specific failures (missing tiles, bad config)
        detail = f"{EXPOSURE_HELP[source]} ({type(exc).__name__})"
        raise ExposureUnavailable(source, detail) from exc

    raise ExposureUnavailable(source)  # unreachable, keeps type-checkers happy
