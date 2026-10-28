"""Which generators are the load-shedding backstop.

Shedding is PyPSA's own (``n.optimize.add_load_shedding``, see ``network/load_shedding.py``): the generators are
identified by CARRIER (``SHED_CARRIER``). Runs stored before build version 4 hold Ragnarok's own per-bus generators
named ``load_shedding_<bus>``; the compat reader (:func:`is_shedding`) recognises those names too, and the price-elastic
demand blocks (``load_shedding_elastic_*``), which are shedding-style generators by construction.
"""
from __future__ import annotations

from typing import Any

import pandas as pd

#: Carrier of the shedding generators (``system_defaults.json`` ``load_shedding.carrier``).
SHED_CARRIER = "LoadShedding"
#: Names written by builds before 4 (one generator per bus) and by the price-elastic demand blocks.
LEGACY_PREFIX = "load_shedding_"
#: Suffix PyPSA's ``add_load_shedding`` gives the generators ("<bus> load shedding").
SUFFIX = " load shedding"


def shed_carrier() -> str:
    from ...app.config import load_system_defaults

    return str(load_system_defaults().get("load_shedding", {}).get("carrier") or SHED_CARRIER)


def is_shedding(name: Any, carrier: Any = None) -> bool:
    """True for a shedding generator: its carrier is the shedding carrier, or (compat) its name says so."""
    if carrier is not None and str(carrier) == shed_carrier():
        return True
    text = str(name)
    return text.startswith(LEGACY_PREFIX) or text.endswith(SUFFIX)


def shedding_names(generators: pd.DataFrame) -> list[str]:
    """Names of the shedding generators in a generators frame (carrier first, legacy names as a fallback)."""
    carriers = generators["carrier"] if "carrier" in generators.columns else pd.Series("", index=generators.index)
    return [str(n) for n in generators.index if is_shedding(n, carriers.get(n))]


def shedding_mask(generators: pd.DataFrame) -> pd.Series:
    """Boolean Series over ``generators.index``: True for a shedding generator (carrier first, legacy names as a fallback)."""
    carriers = generators["carrier"] if "carrier" in generators.columns else pd.Series("", index=generators.index)
    return pd.Series([is_shedding(n, carriers.get(n)) for n in generators.index], index=generators.index, dtype=bool)
