"""Round trip of the public network -> workbook converter ``backend.pypsa.network.serialize.network_to_model``.

``build_network(model)`` then ``network_to_model`` must give back the workbook: every authored cell of every static and
series sheet survives (a column left at an infinite default, e.g. ``p_nom_max = inf``, is not emitted), and a second
round trip is exactly the first (the converter is idempotent on its own output).
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from backend.pypsa.network import build_network
from backend.pypsa.network.serialize import network_to_model
from backend.tests.test_training_checkpoints import (
    OPTIONS,
    SCENARIO,
    _model_from_example,
)

#: Sheets that are not the converter's to return: the schema stamp, and PyPSA's own type tables.
_NOT_ROUND_TRIPPED = {"RAGNAROK_Schema", "line_types", "transformer_types"}


def _is_default_inf(v: Any) -> bool:
    try:
        return math.isinf(float(v))
    except (TypeError, ValueError):
        return False


def _same(a: Any, b: Any) -> bool:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool):
        return bool(np.isclose(a, b, rtol=1e-9, atol=1e-12))
    return str(a) == str(b)


@pytest.mark.parametrize("example", ["three_bus", "renewables_storage"])
def test_round_trip_keeps_every_authored_cell(example: str, tmp_path: Path) -> None:
    model = _model_from_example(example, tmp_path)
    network, _ = build_network(model, SCENARIO, OPTIONS)
    back = network_to_model(network)

    assert len(back["snapshots"]) == len(model["snapshots"])
    static = [s for s in model if "-" not in s and s != "snapshots" and s not in _NOT_ROUND_TRIPPED and model[s]]
    series = [s for s in model if "-" in s and model[s]]
    assert static and series, "the example must exercise both static and series sheets"
    for sheet in static + series:
        assert sheet in back, f"{sheet} dropped by the converter"
        assert len(back[sheet]) == len(model[sheet]), f"{sheet}: row count changed"
        for i, (row_in, row_out) in enumerate(zip(model[sheet], back[sheet])):
            for col, v in row_in.items():
                if v in (None, "") or _is_default_inf(v):
                    continue
                assert col in row_out, f"{sheet}[{i}].{col} lost"
                assert _same(v, row_out[col]), f"{sheet}[{i}].{col}: {v!r} -> {row_out[col]!r}"


def test_converter_is_idempotent_on_its_own_output(tmp_path: Path) -> None:
    model = _model_from_example("renewables_storage", tmp_path)
    first = network_to_model(build_network(model, SCENARIO, OPTIONS)[0])
    second = network_to_model(build_network(first, SCENARIO, OPTIONS)[0])
    assert second.keys() == first.keys()
    for sheet in first:
        assert second[sheet] == first[sheet], f"{sheet} changed on the second round trip"


def test_main_alias_is_the_public_function() -> None:
    from backend.app.main import _network_to_model_json

    assert _network_to_model_json is network_to_model
