"""Physical-risk module hooks (see :mod:`backend.app.module_hooks`)."""
from __future__ import annotations

from typing import Any

from backend.app import module_hooks as mh


def _uplift(data: dict[str, Any]) -> dict[str, Any]:
    """Opt-in physical-risk -> forced-outage-rate coupling: if ``options.outageMcConfig.physicalRiskUplift`` is
    set, inject ``options.outageMcConfig.forRateUplift`` from the referenced session's latest completed run
    before the snapshot is frozen. No-op unless the config opts in; never raises."""
    from backend.app import physical_risk_uplift

    data["options"] = physical_risk_uplift.apply_physical_risk_uplift(data.get("options"))
    return data


mh.register("submit", "physical-risk-uplift", _uplift, module="physical-risk", order=30)
