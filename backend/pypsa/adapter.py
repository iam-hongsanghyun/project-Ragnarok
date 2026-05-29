"""PyPSA reference backend adapter.

Wraps the existing :func:`backend.pypsa.results.run_pypsa` end-to-end pipeline
(pre-build plugins → build → solve → extract → post-solve) behind the
:class:`~backend.app.backends.base.Backend` interface. No solve logic lives
here — this is purely the adapter that names PyPSA as a backend and reports
what it can do.
"""
from __future__ import annotations

from typing import Any

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
            # Study modes this backend can run today. Power-flow-only modes
            # ("pf"/"lpf") are roadmapped, not yet implemented.
            "studyModes": ["optimize"],
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
            },
        }

    def run(
        self,
        model: dict[str, list[dict[str, Any]]],
        scenario: dict[str, Any],
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return run_pypsa(model, scenario, options or {})
