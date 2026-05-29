"""Regression tests for ``backend.pypsa.results.full_outputs.build_full_outputs``.

The frontend's ``deriveAssetDetails`` reads time-series outputs from
``outputs.series['<list_name>-<attr>']``. For components whose dynamic frame
is *not* exposed as ``network.<list_name>_t`` (notably ``processes`` in PyPSA
1.2+), the schema-driven extractor must fall back to ``comp.dynamic`` so the
frontend still receives the data.
"""
from __future__ import annotations

import pypsa

from backend.pypsa.results.full_outputs import build_full_outputs


def test_processes_time_series_extracted_via_dynamic_fallback() -> None:
    """A process with assigned ``p0`` time-series must appear in ``outputs.series``.

    ``processes`` does not expose a top-level ``network.processes_t`` accessor
    in PyPSA 1.2.x — the dynamic frame is only reachable via
    ``network.c.processes.dynamic``. ``build_full_outputs`` must use that
    fallback so the frontend asset-details builder can render the process card.
    """
    network = pypsa.Network()
    network.add("Bus", "b0")
    network.add("Bus", "b1")
    network.set_snapshots(["2025-01-01 00:00", "2025-01-01 01:00"])
    network.add("Process", "electrolyser", bus0="b0", bus1="b1", p_nom=100.0)

    # Manually populate p0/p1 — we don't run the solver here, we just want to
    # prove the extractor sees the dynamic frames at all.
    network.c.processes.dynamic.p0["electrolyser"] = [10.0, 20.0]
    network.c.processes.dynamic.p1["electrolyser"] = [-9.5, -19.0]

    outputs = build_full_outputs(network)

    assert "processes-p0" in outputs["series"], (
        "Expected processes-p0 in outputs.series; got keys: "
        + repr(sorted(outputs["series"].keys()))
    )
    assert "processes-p1" in outputs["series"]
    p0_rows = outputs["series"]["processes-p0"]
    assert len(p0_rows) == 2
    assert p0_rows[0]["electrolyser"] == 10.0
    assert p0_rows[1]["electrolyser"] == 20.0
