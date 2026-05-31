"""OPSD hourly load importer (Tier 1, no API key)."""
from __future__ import annotations

from ..._config import load_module_config_dict, meta_from_config
from .importer import OPSDLoadImporter


def build() -> OPSDLoadImporter:
    config = load_module_config_dict(__file__)
    meta = meta_from_config(config)
    return OPSDLoadImporter(meta=meta)


__all__ = ["OPSDLoadImporter", "build"]
