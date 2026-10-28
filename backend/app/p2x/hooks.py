"""P2X module hooks (see :mod:`backend.app.module_hooks`): RFNBO matching and the session RFNBO settings."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import HTTPException

from backend.app import module_hooks as mh

MODULE = "p2x"


def _prepare(ctx: mh.RunContext) -> Callable[[Any, Any], None] | None:
    """RFNBO hourly-or-monthly matching (Delegated Reg. (EU) 2023/1184 Art. 6), resolved BEFORE the solve so
    a mis-designated chain is a 400 and not a silent zero-electrolyser run."""
    from . import rfnbo

    try:
        plan = rfnbo.resolve_plan(ctx.model, ctx.options.get("rfnboConfig"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not plan:
        return None
    if ctx.stochastic is not None and ctx.stochastic.enabled:
        raise HTTPException(status_code=400, detail="RFNBO matching cannot be combined with stochastic scenarios.")

    def contribute(n: Any, snapshots: Any) -> None:
        # electrolyser electricity <= designated RES output per period
        rfnbo.apply_rfnbo_constraints(n, plan, snapshots, ctx.notes)

    return contribute


def _session_rfnbo(data: dict[str, Any]) -> dict[str, Any]:
    """The RFNBO matching settings chosen in the P2X tab ride with a run that sets none itself."""
    from . import config_store

    data["options"] = config_store.apply_session_rfnbo(data.get("sessionId"), data.get("options"))
    return data


mh.register("constraints", "p2x-rfnbo", _prepare, module=MODULE, order=50)
mh.register("submit", "p2x-session-rfnbo", _session_rfnbo, module=MODULE, order=40)
