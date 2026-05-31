"""OpenStreetMap power-infrastructure importer (via Overpass API)."""
from __future__ import annotations

from ..._config import load_module_config_dict, meta_from_config
from .importer import OSMImporter


def build() -> OSMImporter:
    config = load_module_config_dict(__file__)
    meta = meta_from_config(config)
    return OSMImporter(meta=meta)


__all__ = ["OSMImporter", "build"]
