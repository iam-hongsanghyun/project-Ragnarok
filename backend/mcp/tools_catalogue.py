"""Task routing: the ``tool_catalogue`` tool.

Read-only. Without ``area`` it lists the areas of the tool surface (purpose, tool count, entry points); with an area it
lists that area's tools, one line each with read/write mode, plus recipes (ordered tool calls for common requests).
Everything is derived from :mod:`backend.mcp.catalogue` and the live tool list, so it cannot drift from the tools.
"""

from __future__ import annotations

from .catalogue import AREAS, declare_areas, render_catalogue
from .server import _RO, mcp


@mcp.tool(
    annotations=_RO,
    description=(
        "Find the right Ragnarok tool for a task. Call it when unsure which tool to use. No area: the areas "
        "(inspect, build, composites, time_ops, transforms, run, results, studies, policy, physical_risk, siting, "
        "data, session) with purpose, tool count and entry-point tools. With area: that area's tools, one line each "
        "(read-only vs writes / needs confirm=true) plus ready-made recipes of ordered calls, e.g. add a CCGT or "
        "battery and solve, hydrogen cost, ramp rates and time step, carbon price, clustering, import a country."
    ),
)
async def tool_catalogue(area: str | None = None) -> str:
    """``area``: one of the area ids above, or omit for the overview."""
    tools = mcp._tool_manager.list_tools()
    try:
        return render_catalogue(tools, area)
    except ValueError as exc:  # unknown area: a sentence the model can act on
        return f"error: {exc}"


declare_areas({"tool_catalogue": "session"})
_ = AREAS  # areas are validated at declare time
