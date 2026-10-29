"""Area registry for the MCP tool surface: the single source of truth for "which tool is for what".

Every tool module declares, next to its tools, ``declare_areas({"tool_name": "area_id", ...})``. A test
(``backend/tests/test_mcp_catalogue.py``) fails when a registered tool has no area, when an area names a tool that
does not exist, and when the generated documentation block in ``docs/bifrost-agent.md`` is out of date.

This module imports nothing from :mod:`backend.mcp.server` (the server imports it), so it is safe to import first.
It holds three things:

* ``AREAS``      - the areas, in display order: purpose, entry-point tools, search keywords (EN + KO), recipes.
* ``TOOL_AREA``  - tool name -> area id, filled by ``declare_areas`` as the tool modules are imported.
* renderers      - the ``tool_catalogue`` tool output, the routing text in the server instructions, and the
  documentation block, all derived from the two above plus the live tool list (so descriptions never drift).
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

# A recipe is (request in words, ordered steps). A step is a tool name, optionally followed by "(args)"
# such as "add_plant(confirm=true)". The first word of every step must be a registered tool (tested).
Recipe = tuple[str, tuple[str, ...]]


@dataclass(frozen=True)
class Area:
    """One area of the tool surface."""

    id: str
    title: str
    purpose: str  # one line
    entry_points: tuple[str, ...]  # where to start
    keywords: str  # extra search words, English and Korean; shown by tool_catalogue and used by the routing eval
    recipes: tuple[Recipe, ...] = field(default_factory=tuple)


AREAS: dict[str, Area] = {
    a.id: a
    for a in (
        Area(
            "inspect",
            "Inspect the model",
            "Read what is loaded: sheets, component schema, series windows, validity checks. Never changes anything.",
            ("get_world_state", "check_model", "get_sheet_page"),
            "loaded model buses carriers snapshots sheet rows statistics validate check schema attribute "
            "모델 확인 시트 버스 검증 속성",
            (
                (
                    "what is loaded and is it right",
                    ("get_world_state", "check_model", "validate_model"),
                ),
                (
                    "look inside a sheet",
                    ("get_sheet_stats", "get_sheet_page", "derive_series"),
                ),
            ),
        ),
        Area(
            "build",
            "Build and edit components",
            "Add or change buses, generators, loads, lines, storage and any PyPSA component; bulk edits; piecewise cost curves.",
            ("add_generator", "edit_sheet", "forge_query", "add_component"),
            "add generator load line bus battery storage edit sheet cell bulk adjust capacity capital cost "
            "piecewise curve 발전기 부하 선로 배터리 저장 편집 용량",
            (
                (
                    "build a small network from scratch",
                    (
                        "add_bus",
                        "add_generator",
                        "add_load",
                        "add_line",
                        "set_snapshots",
                        "validate_model",
                    ),
                ),
                (
                    "bulk-change a column with a preview",
                    (
                        "adjust_values",
                        "adjust_values(confirm=true)",
                        "get_journal_diff",
                    ),
                ),
            ),
        ),
        Area(
            "composites",
            "Plants and composite builders (CCGT, OCGT, BESS, co-firing, P2X, hydrogen)",
            "Add one plant as a unit (CCGT/OCGT with part-load and start costs, gas+H2 co-firing, BESS battery) or a "
            "power-to-X hydrogen/ammonia/methanol chain, then read plant-level results (LCOH, H2 share, CO2 avoided).",
            ("list_plant_types", "add_plant", "build_p2x_chain", "get_plant_results"),
            "ccgt ocgt gas turbine combined cycle bess battery cofiring co-firing hydrogen h2 electrolyser ammonia "
            "methanol lcoh rfnbo conversion heat pump chp "
            "가스터빈 복합 배터리 수소 전해조 암모니아 혼소 생산 단가 플랜트 발전소",
            (
                (
                    "add a CCGT on bus X and solve",
                    (
                        "list_plant_types",
                        "add_plant",
                        "add_plant(confirm=true)",
                        "submit_solve",
                        "get_plant_results",
                    ),
                ),
                (
                    "hydrogen production cost (LCOH)",
                    (
                        "list_p2x_technologies",
                        "preview_p2x_chain",
                        "build_p2x_chain(confirm=true)",
                        "submit_solve",
                        "get_p2x_results",
                    ),
                ),
                (
                    "add a simple conversion link (heat pump, boiler, CHP)",
                    (
                        "list_conversions",
                        "add_conversion",
                        "add_conversion(confirm=true)",
                    ),
                ),
            ),
        ),
        Area(
            "time_ops",
            "Time units and operations",
            "Ramp rates, minimum up/down time and start-up times stated in hours or minutes; snapshot step and "
            "weightings; maintenance.",
            ("get_time_units", "set_time_units", "retarget_snapshots"),
            "ramp ramping unit commitment min up down time hours minutes snapshot step resolution weightings "
            "maintenance outage rolling horizon 램프 기동 정지 시간 스냅샷 정비",
            (
                (
                    "state a ramp limit in per-minute or hours",
                    ("get_time_units", "set_time_units", "preview_time_units"),
                ),
                (
                    "change the time step to 3 hours",
                    (
                        "retarget_snapshots",
                        "set_weightings_from_spacing",
                        "validate_model",
                    ),
                ),
            ),
        ),
        Area(
            "transforms",
            "Transforms (cluster, slice, merge, sample, reshape)",
            "Reduce or reshape the working model: spatial clustering, temporal clustering, window/bus slice, merge another "
            "model, test-run sampling, demand forecast, series scaling.",
            ("cluster_network", "temporal_cluster", "slice_model", "sample_workbook"),
            "cluster reduce aggregate slice window merge sample representative days forecast demand growth ev "
            "scale series 클러스터 축소 병합 샘플링 수요 예측",
            (
                (
                    "make the model small for a quick test",
                    (
                        "cluster_network",
                        "cluster_network(confirm=true)",
                        "slice_model",
                        "validate_model",
                    ),
                ),
                (
                    "project demand to 2040",
                    ("forecast_demand", "forecast_demand(confirm=true)", "check_model"),
                ),
            ),
        ),
        Area(
            "run",
            "Run and solve",
            "Queue solves, watch and cancel them, saved scenarios, run options and solver reference, stored-run housekeeping.",
            ("submit_solve", "get_queue", "describe_run_options", "submit_scenario"),
            "solve run optimise queue scenario solver options linear programming mip dispatch capacity expansion "
            "pathway multi-period lp 실행 최적화 시나리오 솔버",
            (
                (
                    "solve the working model and read the cost",
                    (
                        "validate_model",
                        "submit_solve",
                        "submit_solve(confirm=true)",
                        "get_queue",
                        "get_kpis",
                    ),
                ),
                (
                    "run saved scenarios as a batch",
                    (
                        "list_scenarios",
                        "submit_scenarios",
                        "submit_scenarios(confirm=true)",
                        "compare_runs",
                    ),
                ),
            ),
        ),
        Area(
            "results",
            "Results and analytics",
            "Read stored runs: KPIs, carrier mix, prices, cost, emissions, dispatch series, PyPSA statistics, comparison, reports.",
            ("list_runs", "get_kpis", "get_analytics", "get_report"),
            "results kpi cost emissions price dispatch generation capacity factor mix compare runs report statistics "
            "결과 비용 배출 가격 급전 비교 보고서",
            (
                (
                    "explain a run",
                    ("list_runs", "get_kpis", "get_analytics", "get_report"),
                ),
                (
                    "compare two runs",
                    ("list_runs", "compare_runs", "compare_run_statistics"),
                ),
            ),
        ),
        Area(
            "studies",
            "Reliability and market studies",
            "Adequacy (LOLE/EENS), reserves, forced-outage Monte Carlo, ramping, ELCC, LMP decomposition, procurement hedging; "
            "enabled as options on a normal solve.",
            ("describe_analytics", "optimize_procurement"),
            "adequacy reliability lole eens reserve outage monte carlo elcc lmp congestion procurement ppa hedge cvar "
            "신뢰도 예비력 공급 충분성 조달",
            (
                (
                    "run an adequacy and reserve study",
                    (
                        "describe_analytics",
                        "describe_run_options",
                        "submit_solve",
                        "submit_solve(confirm=true)",
                        "get_analytics",
                    ),
                ),
            ),
        ),
        Area(
            "policy",
            "Policy (carbon, budgets, constraints, demand response)",
            "Carbon price (flat or schedule), annual energy/emission budgets, custom constraint DSL, carrier growth limits, "
            "demand response; RFNBO is a run option.",
            (
                "set_carbon_price",
                "set_annual_budget",
                "set_custom_dsl",
                "apply_demand_response",
            ),
            "carbon price co2 emission cap budget constraint dsl demand response shiftable load growth limit "
            "탄소 가격 배출 상한 예산 제약 수요반응",
            (
                (
                    "price carbon and compare",
                    (
                        "set_carbon_price",
                        "set_carbon_price(confirm=true)",
                        "submit_scenario",
                        "compare_runs",
                    ),
                ),
                (
                    "cap a carrier's annual energy",
                    ("get_annual_budgets", "set_annual_budget", "apply_annual_budgets"),
                ),
            ),
        ),
        Area(
            "physical_risk",
            "Physical climate risk",
            "A separate subsystem (own session id): seed a portfolio from the model, set perils/climate/horizon, run, "
            "read damage, transition and finance results.",
            ("physical_risk_seed", "physical_risk_run", "physical_risk_report"),
            "physical risk climate flood heat wildfire peril ngfs rcp ssp damage transition premium "
            "물리적 기후 리스크 홍수 폭염",
            (
                (
                    "climate damage for the current model",
                    (
                        "physical_risk_seed",
                        "physical_risk_set_scenario",
                        "physical_risk_run",
                        "physical_risk_report",
                    ),
                ),
            ),
        ),
        Area(
            "siting",
            "Siting and screening",
            "Screen candidate solar/wind sites: scan a bounding box, upload site series, correlation, portfolio diversification, "
            "promote chosen sites into the model.",
            ("siting_scan", "upload_siting_dataset", "siting_portfolio_metrics"),
            "siting site screening solar wind capacity factor correlation complementarity portfolio diversification "
            "입지 풍력 태양광 상관",
            (
                (
                    "pick complementary wind and solar sites",
                    (
                        "validate_siting_dataset",
                        "upload_siting_dataset",
                        "siting_correlation",
                        "siting_optimise_portfolio",
                        "promote_siting_sites",
                    ),
                ),
            ),
        ),
        Area(
            "data",
            "Data import and export",
            "Bring data in (country models, starter packs, datasets, demand database, weather profiles, PyPSA-Earth, files) "
            "and write models and runs out.",
            (
                "list_starter_packs",
                "build_starter_pack",
                "import_dataset",
                "export_model",
            ),
            "import export download dataset country starter pack osm demand database weather profile netcdf xlsx "
            "workbook file pypsa-earth example 데이터 가져오기 내보내기 국가",
            (
                (
                    "a runnable model for a country",
                    (
                        "list_starter_packs",
                        "build_starter_pack",
                        "build_starter_pack(confirm=true)",
                        "check_model",
                    ),
                ),
                ("save the model to a file", ("export_workbook", "export_model")),
            ),
        ),
        Area(
            "session",
            "Session, journal, plugins",
            "Undo and journal of edits, clear session, server health and log, backend plugins and tab modules.",
            ("get_journal", "undo_journal_entry", "list_plugins", "get_server_info"),
            "undo journal revert history session clear server log health plugin tab module 되돌리기 이력 플러그인",
            (
                (
                    "undo a bad edit",
                    (
                        "get_journal",
                        "get_journal_diff",
                        "undo_journal_entry",
                        "undo_journal_entry(confirm=true)",
                    ),
                ),
                (
                    "run a plugin analysis on a run",
                    ("list_plugins", "get_plugin", "run_plugin_analysis"),
                ),
            ),
        ),
    )
}

# Recipes quoted in the server instructions (area id, index into that area's recipes). Order = display order.
_INSTRUCTION_RECIPES: tuple[tuple[str, int], ...] = (
    ("composites", 0),
    ("composites", 1),
    ("data", 0),
    ("build", 0),
    ("time_ops", 0),
    ("transforms", 0),
    ("run", 0),
    ("results", 0),
    ("studies", 0),
    ("policy", 0),
    ("physical_risk", 0),
)

TOOL_AREA: dict[str, str] = {}


def declare_areas(mapping: dict[str, str]) -> None:
    """Register ``{tool_name: area_id}``; called by each tool module next to its tools."""
    for tool, area in mapping.items():
        if area not in AREAS:
            raise ValueError(
                f"tool {tool!r}: unknown area {area!r}; valid: {', '.join(AREAS)}"
            )
        if tool in TOOL_AREA and TOOL_AREA[tool] != area:
            raise ValueError(
                f"tool {tool!r} declared in two areas: {TOOL_AREA[tool]!r} and {area!r}"
            )
        TOOL_AREA[tool] = area


# ── helpers over the live tool list (objects from FastMCP's tool manager) ───────────────────────────
def _first_sentence(text: str, limit: int = 110) -> str:
    text = " ".join((text or "").split())
    # sentence end: ". " (not after e.g / i.e / vs), " — ", or "; "
    protected = re.sub(r"\b(e\.g|i\.e|vs|etc)\.", lambda m: m.group(0).replace(".", "\x00"), text)
    m = re.search(r"(?<=[a-z0-9)\]'])\. |\s[—–]\s|; ", protected)
    s = text[: m.start() + 1] if m and m.start() > 25 else text
    s = s.rstrip(".;")
    return s if len(s) <= limit else s[: limit - 1].rstrip() + "…"


def _mode(tool: Any) -> str:
    """``R`` read-only, ``W+confirm`` writes behind confirm=true, ``W`` writes without a confirm argument."""
    ann = getattr(tool, "annotations", None)
    if ann is not None and ann.readOnlyHint:
        return "R"
    props = (getattr(tool, "parameters", None) or {}).get("properties", {})
    return "W+confirm" if "confirm" in props else "W"


def tools_by_area(tools: Iterable[Any]) -> dict[str, list[Any]]:
    out: dict[str, list[Any]] = {a: [] for a in AREAS}
    for t in tools:
        out.setdefault(TOOL_AREA.get(t.name, "?"), []).append(t)
    return out


def _recipe_text(recipe: Recipe) -> str:
    return f"{recipe[0]}: " + " -> ".join(recipe[1])


_MAX_CHARS = 7000


def render_catalogue(tools: Iterable[Any], area: str | None = None) -> str:
    """Text of the ``tool_catalogue`` tool: the area overview, or one area's tools and recipes."""
    groups = tools_by_area(tools)
    if area is None:
        lines = [
            "Ragnarok tool areas (call tool_catalogue(area=<id>) for one area's tools and recipes). "
            "R = read-only, W+confirm = writes, preview first then confirm=true, W = writes without a confirm argument.",
        ]
        for a in AREAS.values():
            lines.append(
                f"- {a.id} ({len(groups[a.id])} tools): {a.purpose} Start with: {', '.join(a.entry_points)}."
            )
        return "\n".join(lines)
    key = area.strip().lower().replace("-", "_").replace(" ", "_")
    if key not in AREAS:
        close = [k for k in AREAS if key and (key in k or k in key)]
        hint = f" Did you mean: {', '.join(close)}?" if close else ""
        raise ValueError(f'unknown area "{area}"; valid: {", ".join(AREAS)}.{hint}')
    a = AREAS[key]
    lines = [
        f"{a.id}: {a.title}. {a.purpose}",
        f"Search words: {a.keywords}",
        "Tools (mode, name: what it does):",
    ]
    for t in sorted(groups[key], key=lambda t: (t.name not in a.entry_points, t.name)):
        star = "*" if t.name in a.entry_points else " "
        lines.append(
            f"{star} [{_mode(t)}] {t.name}: {_first_sentence(t.description or '')}"
        )
    lines.append("(* = entry point)")
    lines.append("Recipes:")
    lines.extend(f"- {_recipe_text(r)}" for r in a.recipes)
    text = "\n".join(lines)
    if len(text) > _MAX_CHARS:
        text = (
            text[: _MAX_CHARS - 80].rsplit("\n", 1)[0]
            + "\n[truncated: call describe tools by name for the rest]"
        )
    return text


# ── server instructions ────────────────────────────────────────────────────────────────────────────
_INSTRUCTIONS_HEAD = (
    "Drive a PyPSA power-system model in Ragnarok: introspect the loaded model, import/build data, edit and "
    "transform sheets, solve, and read results. All tools act on one shared working session, visible live in the "
    "Ragnarok web UI. Read-only tools are safe to call freely. Mutating tools (imports, edits, transforms, "
    "solves) may return a PREVIEW first: re-call the same tool with confirm=true to apply. That is the "
    "human-in-the-loop guard, not an error.\n\n"
    "Finding the right tool: call tool_catalogue() for the areas, tool_catalogue(area) for that area's tools "
    "(one line each, read vs write) and ready-made recipes. Do this whenever unsure instead of guessing a name. "
    "Area entry points:\n"
)

_INSTRUCTIONS_TAIL = (
    "\n\nSolve-mode analytics: seven reliability/market studies (reserves, forced-outage Monte Carlo, ramping, "
    "correlated sampling, ELCC, convergence sampling, LMP decomposition) ride the same solve: call "
    "describe_analytics for their option keys, then enable them via submit_solve's options. RFNBO and co-firing "
    "limits are run options too (describe_run_options).\n\n"
    "Physical risk has its OWN server-minted session id; every physical_risk_* tool defaults to the seeded "
    "session. Follow the climate-damage recipe above."
)


def build_instructions() -> str:
    """The server instructions: routing map per area, the confirm convention, recipes."""
    lines = [f"- {a.title}: {', '.join(a.entry_points)}" for a in AREAS.values()]
    recipes = []
    for area_id, idx in _INSTRUCTION_RECIPES:
        recipes.append(f"- {_recipe_text(AREAS[area_id].recipes[idx])}")
    return (
        _INSTRUCTIONS_HEAD
        + "\n".join(lines)
        + "\n\nRecipes (steps marked (confirm=true) are the second call "
        "of a preview/confirm pair):\n" + "\n".join(recipes) + _INSTRUCTIONS_TAIL
    )


# ── generated documentation block ──────────────────────────────────────────────────────────────────
DOC_START = "<!-- tool-catalogue:start (generated by scripts/gen_mcp_catalogue_doc.py; do not edit by hand) -->"
DOC_END = "<!-- tool-catalogue:end -->"


def render_doc_block(tools: Iterable[Any]) -> str:
    """Markdown tables of every tool by area, derived from the registry and the live descriptions."""
    tools = list(tools)
    groups = tools_by_area(tools)
    out = [
        DOC_START,
        "",
        f"The server has {len(tools)} tools in {len(AREAS)} areas "
        "(mode: R read-only, W+confirm preview then confirm=true, W writes without confirm).",
        "",
        "| Area | Tools | Start with |",
        "|---|---|---|",
    ]
    for a in AREAS.values():
        out.append(
            f"| `{a.id}` | {len(groups[a.id])} | {', '.join(f'`{e}`' for e in a.entry_points)} |"
        )
    for a in AREAS.values():
        out += [
            "",
            f"**`{a.id}`** - {a.title}. {a.purpose}",
            "",
            "| Tool | Mode | What it does |",
            "|---|---|---|",
        ]
        for t in sorted(groups[a.id], key=lambda t: t.name):
            out.append(
                f"| `{t.name}` | {_mode(t)} | {_first_sentence(t.description or '', 140).replace('|', chr(92) + '|')} |"
            )
        out += ["", "Recipes:", ""] + [f"- {_recipe_text(r)}" for r in a.recipes]
    out += ["", DOC_END]
    return "\n".join(out)
