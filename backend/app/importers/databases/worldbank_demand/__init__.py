"""World Bank annual electricity consumption importer."""
from __future__ import annotations

from ..._config import load_module_config_dict, meta_from_config
from .importer import WorldBankDemandImporter


def build() -> WorldBankDemandImporter:
    config = load_module_config_dict(__file__)
    meta = meta_from_config(config)
    return WorldBankDemandImporter(meta=meta)


__all__ = ["WorldBankDemandImporter", "build"]
