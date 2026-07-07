"""Worker entry point: ``python -m physical_risk_worker.run_job <run_dir>``.

Reads ``<run_dir>/request.json``, runs CLIMADA, writes ``<run_dir>/result.json``
(shape: PhysicalRunOutput). Uses only the standard library + CLIMADA — never the
backend package.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from physical_risk_worker.physical import climada_available, compute_physical_risk


def _output(request: dict[str, Any], status: str, detail: str | None) -> dict[str, Any]:
    return {
        "status": status,
        "climate_scenario": request.get("climate_scenario", ""),
        "results": [],
        "detail": detail,
    }


def run(run_dir: Path) -> dict[str, Any]:
    """Execute a single run located in ``run_dir`` and persist its result."""
    request = json.loads((run_dir / "request.json").read_text(encoding="utf-8"))

    if not climada_available():
        output = _output(
            request,
            "engine_not_ready",
            "CLIMADA is not installed in this environment. Build the conda env "
            "from worker/physical_risk_worker/env_climada.yml.",
        )
    else:
        try:
            mode = request.get("mode")
            if mode == "cost_benefit":
                from physical_risk_worker.cost_benefit import compute_cost_benefit

                output = compute_cost_benefit(request)
            elif mode == "uncertainty":
                from physical_risk_worker.uncertainty import compute_uncertainty

                output = compute_uncertainty(request)
            elif mode == "litpop":
                from physical_risk_worker.litpop import compute_litpop_exposure

                output = compute_litpop_exposure(request)
            elif mode == "ingest":
                from physical_risk_worker.ingest import run_ingest

                output = run_ingest(request)
            elif mode == "supplychain":
                from physical_risk_worker.supplychain import compute_supplychain

                output = compute_supplychain(request)
            elif mode == "calibration":
                from physical_risk_worker.calibration import compute_calibration

                output = compute_calibration(request)
            elif mode == "forecast":
                from physical_risk_worker.forecast import compute_forecast

                output = compute_forecast(request)
            elif mode == "hazard_preview":
                from physical_risk_worker.hazard_preview import compute_hazard_preview

                request["out_dir"] = str(run_dir)  # the worker writes preview.png here
                output = compute_hazard_preview(request)
            else:
                output = compute_physical_risk(request)
        except Exception as exc:
            output = _output(request, "error", f"{type(exc).__name__}: {exc}")

    (run_dir / "result.json").write_text(json.dumps(output, indent=2), encoding="utf-8")
    return output


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python -m physical_risk_worker.run_job <run_dir>", file=sys.stderr)
        return 2
    run_dir = Path(argv[1]).resolve()
    if not (run_dir / "request.json").is_file():
        print(f"no request.json in {run_dir}", file=sys.stderr)
        return 1
    output = run(run_dir)
    print(f"run complete: status={output.get('status')} results={len(output.get('results', []))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
