"""WRI Global Power Plant Database importer."""
from __future__ import annotations

from ..._config import load_module_config_dict, meta_from_config
from .importer import WRIGPPDImporter


def build() -> WRIGPPDImporter:
    config = load_module_config_dict(__file__)
    meta = meta_from_config(config)
    return WRIGPPDImporter(meta=meta)


__all__ = ["WRIGPPDImporter", "build"]
