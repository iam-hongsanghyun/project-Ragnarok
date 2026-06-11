"""Read all model settings and sheet data from dashboard.xlsx in one pass.

Public API
----------
read_dashboard(path) -> Dashboard
    Open dashboard.xlsx exactly once and return a ``Dashboard`` that carries
    everything the pipeline needs:  model settings, CC-merge rules, CF
    constraints, carbon-price value, and carrier emission intensities.

The ``Dashboard`` object is then passed to every downstream function so the
file is never re-opened.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class Settings:
    """Scalar configuration values from the ``network`` sheet."""

    model: str             # path to network Excel file
    base_year: int
    target_year: int
    target_load_twh: float
    snapshot_start: str    # normalised to dd/mm/yyyy HH:MM
    snapshot_length: int   # number of hours to simulate
    grid_mode: str = "as-is"    # "single" | "as-is" | "line_to_link" | "merge_line_transformer"
    single_bus: str = "KR"      # bus name used when grid_mode == "single"
    link_loss: float = 0.03     # fractional loss applied to line-derived links
    aggregate_by_region: bool = False   # True → collapse buses into regions
    region_column: str = "province"     # "province" | "group1" | "group2" | "group3" | "singlenode"
    aggregate_by_carrier: bool = False  # True → merge generators per (bus, carrier) using rules
    demand_redistribution: bool = False  # True → move annual demand between bus/region groups
    replace_generators: bool = False  # True → replace target-year plants with solar/wind
    replace_build_year: int = 0  # filter 2: only plants with build_year ≥ this are replaceable (0 → no filter)
    replace_follow: bool = False  # True → split by that year's solar:wind additions
    replace_solar_pct: float = 50.0  # direct solar share (%) when not following
    replace_wind_pct: float = 50.0   # direct wind share (%) when not following
    replace_all_carriers: bool = False  # True → bulk-reallocate all plants of replace_carriers
    replace_carriers: tuple = ()  # carriers selected for the dropdown filter / bulk reallocation
    replace_filter_column: str = ""  # extra attribute filter: generators sheet column name
    replace_filter_value: str = ""   # ... keep only generators whose column == this value
    marginal_cost_multiplier: bool = False  # True → scale generator marginal cost per carrier
    plot_map: bool = True       # True → save a network map PNG before optimisation
    cc_rule: bool = True        # False → skip CC merge
    carbonprice: bool = False
    carbonprice_scenario: str = ""
    currency_exchange: float = 1350.0   # model-currency units per carbon-price-currency unit
    constraints: bool = False
    constraints_attribute: str = "max_cf, min_cf"  # comma-separated list of active CF attributes


@dataclass
class Dashboard:
    """All data parsed from dashboard.xlsx in a single file open.

    Attributes:
        settings:           Scalar model parameters from the ``network`` sheet.
        cc_rules:           CC merge rules from ``CC_group`` sheet, or ``None``
                            if the sheet is absent.
        cf_constraints:     Capacity-factor constraints filtered for
                            ``settings.target_year``; empty DataFrame if none.
        carbon_price_usd:   Carbon price per tonne CO₂ for the target year, in
                            the carbon-price currency (field name is historical)
                            and selected scenario; 0.0 if not found.
        emission_intensity: Carrier → kg CO₂/MWh for ``settings.target_year``
                            from the wide-format ``emission_intensity`` sheet;
                            empty Series if the sheet is absent or the year has
                            no row (carbon price then has no effect).
    """

    settings: Settings
    cc_rules: pd.DataFrame | None
    cf_constraints: pd.DataFrame
    carbon_price_usd: float
    emission_intensity: pd.Series = field(
        default_factory=lambda: pd.Series(dtype=float)
    )
    # province → region/group mapping (province_mapping sheet). None when absent.
    province_mapping: pd.DataFrame | None = None
    # Generator merge rules for aggregate_by_carrier (static attributes).
    carrier_rules: pd.DataFrame | None = None
    # Generator merge rules for aggregate_by_carrier (time-series attributes).
    carrier_rules_t: pd.DataFrame | None = None
    # Region aggregation rules (aggregation_by_region sheet).
    # Columns: component, attribute, rule.  None when the sheet is absent.
    region_rules: pd.DataFrame | None = None
    # Demand redistribution moves (GUI table only — not read from xlsx).
    # Columns: from_resolution, from_value, to_resolution, to_value, amount_mwh.
    demand_redist_rules: pd.DataFrame | None = None
    # Generator replacements (GUI table only — not read from xlsx).
    # Required column: generator.  None when absent.
    generator_replacements: pd.DataFrame | None = None
    # Marginal-cost multipliers (GUI table only — not read from xlsx).
    # Columns: carrier, multiplier_pct (% of original).  None when absent.
    marginal_cost_rules: pd.DataFrame | None = None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _parse_optional_float(value: object, default: float = 0.0) -> float:
    """Parse an Excel cell as a float, returning *default* when blank/NaN/None.

    Treats ``None``, NaN, empty strings, and unparseable text as *default*.
    Used for optional numeric settings (e.g. the dashboard ``load`` cell —
    blank means "keep the original profile, do not rescale").
    """
    if value is None:
        return default
    if isinstance(value, float) and value != value:   # NaN
        return default
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if not s:
        return default
    try:
        return float(s)
    except ValueError:
        return default


def _parse_bool(value: object) -> bool:
    """Coerce an Excel cell value to ``bool``.

    Excel TRUE/FALSE arrive as Python ``bool``; string forms (``"True"``,
    ``"TRUE"``, ``"1"``, ``"yes"``) are also accepted.  Everything else
    (``"False"``, ``"0"``, ``"no"``, empty string, ``None``) → ``False``.
    """
    if isinstance(value, bool):
        return value
    return str(value).strip().upper() in ("TRUE", "1", "YES")


def _open_excel(path: Path) -> pd.ExcelFile:
    """Open *path* with the first available Excel engine."""
    for engine in ("calamine", "openpyxl"):
        try:
            return pd.ExcelFile(path, engine=engine)
        except ImportError:
            continue
    raise ImportError("Install python-calamine or openpyxl to read dashboard.xlsx")


def _parse_settings(xl: pd.ExcelFile) -> Settings:
    """Parse the ``network`` (or legacy ``Settings``) sheet into a Settings."""
    for candidate in ("network", "Network", "Settings"):
        if candidate in xl.sheet_names:
            sheet = candidate
            break
    else:
        sheet = xl.sheet_names[0]

    df = xl.parse(sheet, header=None)
    # Case-insensitive lookup: dashboard items are normalised to lowercase here,
    # so user edits like "CC_rule" or "Single_bus" still match the parser keys.
    lookup = {str(row[0]).strip().lower(): row[1] for _, row in df.iterrows()}

    raw_start = lookup["snapshot_start"]
    if hasattr(raw_start, "strftime"):
        snapshot_start = raw_start.strftime("%d/%m/%Y %H:%M")
    else:
        snapshot_start = str(raw_start).strip()

    return Settings(
        model=str(lookup["model"]).strip(),
        base_year=int(lookup["base_year"]),
        target_year=int(lookup["target_year"]),
        target_load_twh=_parse_optional_float(lookup.get("load"), default=0.0),
        snapshot_start=snapshot_start,
        snapshot_length=int(lookup["snapshot_length"]),
        grid_mode=str(lookup.get("grid_mode", "as-is")).strip().lower(),
        single_bus=str(lookup.get("single_bus", "KR")).strip(),
        link_loss=float(lookup.get("link_loss", 0.03)),
        aggregate_by_region=_parse_bool(lookup.get("aggregate_by_region", False)),
        region_column=str(lookup.get("region_column", "province")).strip().lower(),
        aggregate_by_carrier=_parse_bool(lookup.get("aggregate_by_carrier", False)),
        plot_map=_parse_bool(lookup.get("plot_map", True)),
        cc_rule=_parse_bool(lookup.get("cc_rule", True)),
        carbonprice=_parse_bool(lookup.get("carbonprice", False)),
        carbonprice_scenario=str(lookup.get("carbonprice_scenario", "")).strip(),
        currency_exchange=float(lookup.get("currency_exchange", 1350.0)),
        constraints=_parse_bool(lookup.get("constraints", False)),
        constraints_attribute=str(
            lookup.get("constraints_attribute", "max_cf, min_cf")
        ).strip(),
    )


def _parse_cc_rules(xl: pd.ExcelFile) -> pd.DataFrame | None:
    """Parse the ``CC_group`` sheet; returns ``None`` if absent."""
    if "CC_group" not in xl.sheet_names:
        return None

    df = xl.parse("CC_group")
    if df.empty:
        return None

    df.columns = df.columns.str.strip()
    if "attribute" not in df.columns or "rule" not in df.columns:
        raise ValueError(
            "CC_group sheet must have 'attribute' and 'rule' columns. "
            f"Found: {list(df.columns)}"
        )
    return df[["attribute", "rule"]].dropna(subset=["attribute", "rule"]).reset_index(drop=True)


def _parse_province_mapping(xl: pd.ExcelFile) -> pd.DataFrame | None:
    """Parse the ``province_mapping`` sheet; returns ``None`` if absent.

    Expected columns: ``short``, ``official``, and any number of group columns
    (``group1``, ``group2``, …, ``singlenode``).  ``short`` and ``official``
    are required; group columns are looked up by ``settings.region_column``
    at use-time.
    """
    for candidate in ("province_mapping", "Province_mapping", "ProvinceMapping"):
        if candidate in xl.sheet_names:
            sheet = candidate
            break
    else:
        return None

    df = xl.parse(sheet)
    if df.empty:
        return None

    df.columns = df.columns.str.strip().str.lower()
    if "short" not in df.columns or "official" not in df.columns:
        raise ValueError(
            f"{sheet} sheet must have 'short' and 'official' columns. "
            f"Found: {list(df.columns)}"
        )
    # Normalise whitespace in every text cell
    for col in df.columns:
        if df[col].dtype == object:
            df[col] = df[col].astype(str).str.strip().replace({"nan": pd.NA, "": pd.NA})
    return df.dropna(subset=["short", "official"]).reset_index(drop=True)


def _parse_carrier_rules(xl: pd.ExcelFile, sheet: str) -> pd.DataFrame | None:
    """Parse an ``attribute / rule`` rules sheet; returns ``None`` if absent."""
    if sheet not in xl.sheet_names:
        return None

    df = xl.parse(sheet)
    if df.empty:
        return None

    df.columns = df.columns.str.strip()
    if "attribute" not in df.columns or "rule" not in df.columns:
        raise ValueError(
            f"{sheet} sheet must have 'attribute' and 'rule' columns. "
            f"Found: {list(df.columns)}"
        )
    return df[["attribute", "rule"]].dropna(subset=["attribute", "rule"]).reset_index(drop=True)


def _parse_region_rules(xl: pd.ExcelFile) -> pd.DataFrame | None:
    """Parse the ``aggregation_by_region`` sheet; returns ``None`` if absent.

    Expected columns: ``component``, ``attribute``, ``rule``.  A ``description``
    column is allowed but ignored.  Each row specifies how a component attribute
    is reduced when multiple components collapse onto the same region.

    Special ``attribute`` value ``others`` acts as the per-component default
    for attributes not explicitly listed.

    Recognised rule values
    ----------------------
    ``sum``         Numeric sum.
    ``mean``        Unweighted mean.
    ``min``         Minimum.
    ``max``         Maximum.
    ``ignore``      Don't set the attribute; PyPSA uses its built-in default.
    ``default``     Explicit alias for ``ignore`` — clearer when the intent is
                    "use PyPSA's default value" rather than "discard".
    ``inf``         Set the attribute to positive infinity.
    ``-inf``        Set the attribute to negative infinity.
    ``oldest``      Minimum (alias for build-year semantics).
    ``newest``      Maximum.
    ``region``      Use the region name.
    ``carrier``     Use the carrier string.
    *literal*       Copy the rule string verbatim as the attribute value.
    """
    for candidate in ("aggregation_by_region", "aggregation_by_Region"):
        if candidate in xl.sheet_names:
            sheet = candidate
            break
    else:
        return None

    df = xl.parse(sheet)
    if df.empty:
        return None

    df.columns = df.columns.str.strip().str.lower()
    required = {"component", "attribute", "rule"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(
            f"{sheet} sheet must have columns {required}. "
            f"Found: {list(df.columns)}"
        )
    df = df[["component", "attribute", "rule"]].dropna(subset=["component", "attribute", "rule"])
    df["component"] = df["component"].astype(str).str.strip().str.lower()
    df["attribute"] = df["attribute"].astype(str).str.strip().str.lower()
    df["rule"]      = df["rule"].astype(str).str.strip().str.lower()
    return df.reset_index(drop=True)


def _parse_cf_constraints(xl: pd.ExcelFile, target_year: int) -> pd.DataFrame:
    """Parse the ``constraints`` sheet, filtered to *target_year*."""
    empty = pd.DataFrame(columns=["carrier", "attribute", "value"])

    if "constraints" not in xl.sheet_names:
        return empty

    df = xl.parse("constraints")
    if df.empty:
        return empty

    df.columns = df.columns.str.strip()
    required = {"carrier", "attribute", "year", "value"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(
            f"constraints sheet missing columns: {missing}. Found: {list(df.columns)}"
        )

    df["year"] = pd.to_numeric(df["year"], errors="coerce")
    df = df[df["year"] == target_year].copy()
    df = df.dropna(subset=["carrier", "attribute", "value"])
    df["carrier"] = df["carrier"].astype(str).str.strip()
    df["attribute"] = df["attribute"].astype(str).str.strip()
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = df.dropna(subset=["value"])

    return df[["carrier", "attribute", "value"]].reset_index(drop=True)


def _parse_carbon_price(
    xl: pd.ExcelFile,
    scenario: str,
    target_year: int,
) -> float:
    """Return carbon price per tonne CO₂ for *scenario* and *target_year*
    (in whatever currency the dashboard quotes it; converted to the model
    currency later via ``settings.currency_exchange``).

    The ``carbonprice_scenario`` sheet has its year values in the first column
    (regardless of what that column is named, e.g. ``$/tCO2``).
    """
    if "carbonprice_scenario" not in xl.sheet_names:
        return 0.0

    df = xl.parse("carbonprice_scenario")
    if df.empty:
        return 0.0

    df.columns = df.columns.str.strip()
    # First column contains year values — rename to "year" regardless of header
    year_col = df.columns[0]
    df = df.rename(columns={year_col: "year"})
    df["year"] = pd.to_numeric(df["year"], errors="coerce")

    scenario = str(scenario).strip()
    if scenario not in df.columns:
        return 0.0

    row = df[df["year"] == target_year]
    if row.empty:
        return 0.0

    val = row.iloc[0][scenario]
    return float(val) if pd.notna(val) else 0.0


def _parse_emission_intensity(xl: pd.ExcelFile, target_year: int) -> pd.Series:
    """Return carrier → kg CO₂/MWh for *target_year* from the ``emission_intensity`` sheet.

    Sheet format (long)::

        year | carrier    | value
        2024 | LNG        | 300
        2024 | bituminous | 820
        2025 | LNG        | 300
        ...
        2038 | LNG        | 263.26

    Only rows matching *target_year* are used.  The carrier name must match
    ``network.generators["carrier"]`` exactly.

    Args:
        xl:          Open :class:`pd.ExcelFile` handle.
        target_year: Year to filter on.

    Returns:
        Series indexed by carrier name, values in kg CO₂/MWh.
        Empty Series if the sheet is absent or no rows match *target_year*.
    """
    if "emission_intensity" not in xl.sheet_names:
        return pd.Series(dtype=float)

    df = xl.parse("emission_intensity")
    df.columns = df.columns.str.strip()

    required = {"year", "carrier", "value"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(
            f"emission_intensity sheet missing columns: {missing}. "
            f"Found: {list(df.columns)}"
        )

    df["year"] = pd.to_numeric(df["year"], errors="coerce")
    df = df[df["year"] == target_year].copy()
    if df.empty:
        return pd.Series(dtype=float)

    df = df.dropna(subset=["carrier", "value"])
    df["carrier"] = df["carrier"].astype(str).str.strip()
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = df.dropna(subset=["value"])

    return pd.Series(
        df["value"].values,
        index=df["carrier"],
        name="intensity_kg_MWh",
        dtype=float,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def read_dashboard(dashboard_path: str | Path) -> Dashboard:
    """Open *dashboard_path* exactly once and return a :class:`Dashboard`.

    All sheets are parsed in a single ``pd.ExcelFile`` open.  Downstream
    functions receive the ``Dashboard`` object — no function re-opens the file.

    Args:
        dashboard_path: Path to ``dashboard.xlsx``.

    Returns:
        :class:`Dashboard` with fully parsed settings and sheet data.
    """
    dashboard_path = Path(dashboard_path)
    xl = _open_excel(dashboard_path)

    settings = _parse_settings(xl)

    cc_rules = _parse_cc_rules(xl)
    cf_constraints = _parse_cf_constraints(xl, settings.target_year)
    carbon_price_usd = _parse_carbon_price(
        xl,
        scenario=settings.carbonprice_scenario,
        target_year=settings.target_year,
    )
    emission_intensity = _parse_emission_intensity(xl, settings.target_year)
    province_mapping = _parse_province_mapping(xl)
    carrier_rules = _parse_carrier_rules(xl, "aggregation_by_carrier")
    carrier_rules_t = _parse_carrier_rules(xl, "aggregation_by_carrier_t")
    region_rules = _parse_region_rules(xl)

    return Dashboard(
        settings=settings,
        cc_rules=cc_rules,
        cf_constraints=cf_constraints,
        carbon_price_usd=carbon_price_usd,
        emission_intensity=emission_intensity,
        province_mapping=province_mapping,
        carrier_rules=carrier_rules,
        carrier_rules_t=carrier_rules_t,
        region_rules=region_rules,
    )


# ---------------------------------------------------------------------------
# Backward-compatibility shim
# ---------------------------------------------------------------------------

def read_settings(dashboard_path: str | Path) -> Settings:
    """Return only the scalar :class:`Settings` from *dashboard_path*.

    Prefer :func:`read_dashboard` for new code — it parses all sheets at once.
    This shim is kept so existing callers continue to work.
    """
    return read_dashboard(dashboard_path).settings
