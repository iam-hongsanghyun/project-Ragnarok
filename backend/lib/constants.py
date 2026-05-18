from __future__ import annotations

import pypsa

DEFAULT_CARRIER_PALETTE: list[str] = [
    "#4e79a7", "#f28e2b", "#e15759", "#76b7b2", "#59a14f",
    "#edc948", "#b07aa1", "#ff9da7", "#9c755f", "#bab0ab",
    "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
    "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf",
    "#393b79", "#637939", "#8c6d31", "#843c39", "#7b4173",
    "#3182bd", "#31a354", "#756bb1", "#636363", "#e6550d",
]


def _normalize_carrier_key(value: str) -> str:
    return value.strip().lower()


def default_carrier_color(carrier: str) -> str:
    key = _normalize_carrier_key(carrier)
    if not key:
        return "#94a3b8"
    hash_value = 0
    for char in key:
        hash_value = ord(char) + ((hash_value << 5) - hash_value)
    return DEFAULT_CARRIER_PALETTE[abs(hash_value) % len(DEFAULT_CARRIER_PALETTE)]


def carrier_color(network: pypsa.Network, carrier: str) -> str:
    if carrier in network.carriers.index and "color" in network.carriers.columns:
        value = str(network.carriers.at[carrier, "color"] or "").strip()
        if value:
            return value
    return default_carrier_color(carrier)
