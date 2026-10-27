"""PyPSA reference backend adapter.

Wraps the existing :func:`backend.pypsa.results.run_pypsa` end-to-end pipeline
(pre-build plugins → build → solve → extract → post-solve) behind the
:class:`~backend.app.backends.base.Backend` interface. No solve logic lives
here — this is purely the adapter that names PyPSA as a backend and reports
what it can do.
"""
from __future__ import annotations

from typing import Any

from .optimise_options import optimise_option_catalogue, solver_capabilities
from .results import run_pypsa


class PypsaBackend:
    """The default Ragnarok backend, built on PyPSA + HiGHS."""

    name = "pypsa"
    label = "PyPSA"

    def capabilities(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "solver": "HiGHS",
            # Study modes this backend can run. "pf" = AC Newton-Raphson power
            # flow, "lpf" = linear (DC) power flow — both via the powerFlowConfig
            # option (network physics, not optimisation).
            "studyModes": ["optimize", "pf", "lpf"],
            "features": {
                "singlePeriod": True,
                "pathway": True,
                "rollingHorizon": True,
                "stochastic": True,
                "securityConstrained": True,
                "customConstraints": True,
                "globalConstraints": True,
                "carbonPrice": True,
                "loadShedding": True,
                "unitCommitment": True,
                "powerFlow": True,
                "cvarRisk": True,
                "iterativeTransmissionExpansion": True,
                "mgaDirections": True,
                "acFeasibilityAfterOptimise": True,
                "twoStage": True,
            },
            # P20/P45: installed solvers + the n.optimize option keys (see
            # backend/pypsa/optimise_options.py); the GUI Solver settings and the MCP
            # describe_run_options both read these.
            "solvers": solver_capabilities(),
            "optimiseOptions": optimise_option_catalogue()["keys"],
        }

    def run(
        self,
        model: dict[str, list[dict[str, Any]]],
        scenario: dict[str, Any],
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return run_pypsa(model, scenario, options or {})
