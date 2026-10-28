"""What each self-hosted demand series measures, its licence, and area naming (D2).

One place for the facts that go into the manifest and the importer's description, so a
number in the UI can be traced back to a stated definition. Nothing here does I/O.

All stored series share one convention: **MW, UTC, hour-beginning** (the timestamp is the
start of the hour the value covers, which is what PyPSA snapshot labels mean).
"""
from __future__ import annotations

import re

UNIT = "MW"
TIMEZONE = "UTC"
TIMESTAMP_CONVENTION = "hour-beginning"

SOURCES: dict[str, dict[str, str]] = {
    "opsd": {
        "label": "Open Power System Data - time series, 60 min",
        "measure": (
            "ENTSO-E Transparency 'Actual Total Load' (6.1.A) as cleaned and re-published by OPSD "
            "(variable load_actual_entsoe_transparency): the hourly load of the bidding zone / "
            "country as seen by the TSOs (ENTSO-E definition: net generation + imports - exports - "
            "pumped-storage pumping, so it includes grid losses; coverage of embedded / "
            "self-generation varies by TSO). Not the day-ahead forecast. For DE OPSD sums the four TSO control areas. Snapshot frozen at "
            "the OPSD release (the 2020-10-06 package ends 2020-09-30)."
        ),
        "licence": "MIT (OPSD processing); underlying data ENTSO-E Transparency Platform, reuse with attribution",
        "licence_url": "https://github.com/Open-Power-System-Data/time_series/blob/master/LICENSE.md",
        "attribution": "Open Power System Data, time series package; original data ENTSO-E Transparency Platform",
        "homepage": "https://data.open-power-system-data.org/time_series/",
    },
    "eia930": {
        "label": "EIA Form-930 Hourly Electric Grid Monitor - bulk balance files",
        "measure": (
            "Hourly demand of a US balancing authority (BA) as reported on Form EIA-930: the "
            "'Demand (MW) (Adjusted)' column (EIA's reported demand with missing hours imputed and "
            "outliers corrected), falling back to '(Imputed)' then the raw 'Demand (MW)'. Demand = "
            "net generation - total interchange in the BA's footprint. Source files are labelled "
            "'UTC Time at End of Hour' (hour-ending); shifted back one hour to hour-beginning on "
            "import, the same rule as the eia_demand importer (RI4)."
        ),
        "licence": "Public domain (US federal government work, EIA)",
        "licence_url": "https://www.eia.gov/about/copyrights_reuse.php",
        "attribution": "U.S. Energy Information Administration, Form EIA-930",
        "homepage": "https://www.eia.gov/electricity/gridmonitor/",
    },
    "entsoe": {
        "label": "ENTSO-E Transparency Platform - Actual Total Load (optional, needs token)",
        "measure": (
            "ENTSO-E 'Actual Total Load' (documentType A65, processType A16) of the national "
            "bidding zone / control area, sub-hourly points averaged to hourly (interval start). "
            "Germany is the DE-LU zone (Germany + Luxembourg). Same definition as OPSD's "
            "load_actual_entsoe_transparency, so the two series join on time."
        ),
        "licence": "ENTSO-E Transparency Platform terms: free reuse with source acknowledgement; API token required",
        "licence_url": "https://transparency.entsoe.eu/content/static_content/Static%20content/terms%20and%20conditions/terms%20and%20conditions.html",
        "attribution": "ENTSO-E Transparency Platform",
        "homepage": "https://transparency.entsoe.eu/",
    },
}

# OPSD region code (the prefix of ``<area>_load_actual_entsoe_transparency``) -> country name.
_OPSD_COUNTRY = {
    "AT": "Austria", "BE": "Belgium", "BG": "Bulgaria", "CH": "Switzerland", "CY": "Cyprus",
    "CZ": "Czechia", "DE": "Germany", "DK": "Denmark", "EE": "Estonia", "ES": "Spain",
    "FI": "Finland", "FR": "France", "GB": "Great Britain", "GR": "Greece", "HR": "Croatia",
    "HU": "Hungary", "IE": "Ireland", "IT": "Italy", "LT": "Lithuania", "LU": "Luxembourg",
    "LV": "Latvia", "ME": "Montenegro", "NL": "Netherlands", "NO": "Norway", "PL": "Poland",
    "PT": "Portugal", "RO": "Romania", "RS": "Serbia", "SE": "Sweden", "SI": "Slovenia",
    "SK": "Slovakia", "UA": "Ukraine",
}
ISO2_TO_ISO3 = {
    "AT": "AUT", "BE": "BEL", "BG": "BGR", "CH": "CHE", "CY": "CYP", "CZ": "CZE", "DE": "DEU",
    "DK": "DNK", "EE": "EST", "ES": "ESP", "FI": "FIN", "FR": "FRA", "GB": "GBR", "GR": "GRC",
    "HR": "HRV", "HU": "HUN", "IE": "IRL", "IT": "ITA", "LT": "LTU", "LU": "LUX", "LV": "LVA",
    "ME": "MNE", "NL": "NLD", "NO": "NOR", "PL": "POL", "PT": "PRT", "RO": "ROU", "RS": "SRB",
    "SE": "SWE", "SI": "SVN", "SK": "SVK", "UA": "UKR",
}
_OPSD_SPECIAL = {
    "DE_LU": "Germany + Luxembourg bidding zone",
    "GB_GBN": "Great Britain (England, Wales, Scotland)",
    "GB_NIR": "Northern Ireland",
    "GB_UKM": "United Kingdom (GB + Northern Ireland)",
    "IE_sem": "Single Electricity Market (Ireland + Northern Ireland)",
    "DE_50hertz": "Germany - 50Hertz control area",
    "DE_amprion": "Germany - Amprion control area",
    "DE_tennet": "Germany - TenneT DE control area",
    "DE_transnetbw": "Germany - TransnetBW control area",
}

# Every US BA in the EIA bulk file is US; the file carries codes only, so names come from
# the codes the eia_demand importer already documents, falling back to the code.
EIA_BA_NAMES = {
    "PJM": "PJM Interconnection", "MISO": "Midcontinent ISO", "CISO": "California ISO",
    "ERCO": "ERCOT (Texas)", "SWPP": "Southwest Power Pool", "NYIS": "New York ISO",
    "ISNE": "ISO New England", "FPL": "Florida Power & Light", "SOCO": "Southern Company",
    "TVA": "Tennessee Valley Authority", "DUK": "Duke Energy Carolinas",
    "BPAT": "Bonneville Power Administration",
}

ENTSOE_COUNTRY_NAMES = {  # ISO3 -> label; the EIC map itself lives in the entsoe_load importer
    "DEU": "Germany (DE-LU)", "GBR": "Great Britain", "FRA": "France",
}

_AREA_RE = re.compile(r"^[A-Za-z0-9_]+$")


def valid_area(area: str) -> bool:
    """Area codes become file names; only ``[A-Za-z0-9_]`` is allowed (no path tricks)."""
    return bool(_AREA_RE.match(area))


def area_label(source: str, area: str) -> str:
    if source == "opsd":
        if area in _OPSD_SPECIAL:
            return _OPSD_SPECIAL[area]
        head, _, tail = area.partition("_")
        name = _OPSD_COUNTRY.get(head, head)
        return f"{name} - zone {tail}" if tail else name
    if source == "eia930":
        return EIA_BA_NAMES.get(area, f"US balancing authority {area}")
    return ENTSOE_COUNTRY_NAMES.get(area, area)


def area_iso3(source: str, area: str) -> str:
    """ISO-3166 alpha-3 of the country an area belongs to ('' if unknown)."""
    if source == "eia930":
        return "USA"
    if source == "entsoe":
        return area.upper()
    return ISO2_TO_ISO3.get(area.partition("_")[0], "")


def is_primary(source: str, area: str) -> bool:
    """True for the national-level series (the one 'auto' picks for a country)."""
    if source == "opsd":
        return "_" not in area or area == "GB_GBN"
    return True
