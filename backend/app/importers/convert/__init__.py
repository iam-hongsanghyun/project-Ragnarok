"""Cross-database conversion helpers.

Each database module emits raw rows; helpers here build the final
``WorkbookFragment`` (carriers union, name dedupe, provenance row) and pick
electrical defaults from the shared PyPSA standard-types catalogue.
"""
from __future__ import annotations

from .carriers import (
    carrier_defaults_for,
    load_carrier_defaults,
    map_fuel_to_carrier,
)
from .sheets import (
    build_provenance,
    dedupe_name,
    merge_carriers_into_fragment,
    slugify_name,
)
from .standard_types import (
    default_line_type_for_voltage,
    line_params_for_voltage,
    line_type_table,
)

__all__ = [
    "build_provenance",
    "carrier_defaults_for",
    "dedupe_name",
    "default_line_type_for_voltage",
    "line_params_for_voltage",
    "line_type_table",
    "load_carrier_defaults",
    "map_fuel_to_carrier",
    "merge_carriers_into_fragment",
    "slugify_name",
]
