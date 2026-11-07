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
            "Read what is loaded: sheets, component schema, series windows, validity and grid-topology checks. Never changes anything.",
            ("get_world_state", "check_model", "get_sheet_page"),
            "loaded model buses carriers snapshots sheet rows statistics validate check schema attribute topology "
            "consistency ptdf subnetwork 모델 확인 시트 버스 검증 속성 점검",
            (
                (
                    "what is loaded and is it right",
                    ("get_world_state", "check_model", "validate_model"),
                ),
                (
                    "look inside a sheet",
                    ("get_sheet_stats", "get_sheet_page", "derive_series"),
                ),
                (
                    "check the grid structure before a solve",
                    ("consistency_check", "network_analysis", "validate_model"),
                ),
            ),
        ),
        Area(
            "data",
            "Data import",
            "Bring data in: country models and starter packs, importer datasets, the demand database, weather-derived "
            "profiles, PyPSA-Earth builds, importer API keys.",
            (
                "list_starter_packs",
                "build_starter_pack",
                "import_dataset",
                "one_click_model",
            ),
            "import download dataset country starter pack osm power plants demand database weather renewable profile "
            "hydro inflow pypsa-earth api key source health 데이터 가져오기 국가 발전소 수요 데이터베이스 날씨 프로파일",
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
                (
                    "build a model from data, check it and solve",
                    (
                        "list_starter_packs",
                        "build_starter_pack(confirm=true)",
                        "check_model",
                        "validate_model",
                        "submit_solve(confirm=true)",
                        "get_kpis",
                    ),
                ),
                (
                    "pick datasets for a country yourself",
                    (
                        "list_importers",
                        "list_import_databases",
                        "import_dataset",
                        "import_dataset(confirm=true)",
                    ),
                ),
                (
                    "add weather-based solar and wind profiles to the fleet",
                    (
                        "attach_renewable_profiles",
                        "attach_renewable_profiles(confirm=true)",
                        "check_model",
                    ),
                ),
                (
                    "take demand from the demand database",
                    (
                        "list_demand_db",
                        "get_demand_db_slice",
                        "import_demand_db(confirm=true)",
                    ),
                ),
                (
                    "build a country grid with PyPSA-Earth",
                    (
                        "pypsa_earth_status",
                        "pypsa_earth_build(confirm=true)",
                        "pypsa_earth_build_status",
                        "pypsa_earth_apply(confirm=true)",
                    ),
                ),
            ),
        ),
        Area(
            "files",
            "Files, projects and examples",
            "Save and load the model as a project file (.db, model + every setting), workbook, project zip, PyPSA netCDF / HDF5 / "
            "Excel / CSV or a MATPOWER / pandapower case; author a project file from another tool; export a stored run; the "
            "multi-year master model; bundled examples.",
            ("export_workbook", "import_project", "export_model", "load_example"),
            "export save file workbook xlsx netcdf hdf5 csv zip project matpower pandapower import example sample network "
            "master multi-year result download project.db sqlite db project-file author build void pipeline format guide "
            "파일 내보내기 저장 불러오기 예제 프로젝트 프로젝트파일 만들기 형식 가이드",
            (
                ("save the model to a file", ("export_workbook", "export_model")),
                (
                    "open a PyPSA or grid-model file",
                    (
                        "pypsa_io_capabilities",
                        "import_pypsa_native",
                        "import_pypsa_native(confirm=true)",
                        "check_model",
                    ),
                ),
                (
                    "export a stored run for someone else",
                    ("list_runs", "export_run"),
                ),
                (
                    "start from a bundled example",
                    ("list_examples", "load_example", "load_example(confirm=true)", "check_model"),
                ),
                (
                    "make a Ragnarok project file from another tool (VOID, a script)",
                    ("describe_project_file", "get_project_template", "build_project_file", "import_project(confirm=true)", "check_model"),
                ),
                (
                    "save the whole project, settings included",
                    ("export_project_file",),
                ),
                (
                    "keep a multi-year master and work on one year",
                    ("import_master(confirm=true)", "get_master_meta", "derive_from_master", "derive_from_master(confirm=true)"),
                ),
            ),
        ),
        Area(
            "build",
            "Build and edit components",
            "Add or change buses, generators, loads, lines, storage and any PyPSA component; bulk edits; piecewise cost curves; "
            "Forge fixes (discount rate, placeholder bounds).",
            ("add_generator", "edit_sheet", "forge_query", "add_component"),
            "add generator load line bus battery storage edit sheet cell bulk adjust capacity capital cost discount rate "
            "overnight cost placeholder bound piecewise curve 발전기 부하 선로 배터리 저장 편집 용량 할인율",
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
                (
                    "clean an imported model: annuity rate and placeholder bounds",
                    (
                        "check_model",
                        "fill_discount_rate",
                        "fill_discount_rate(confirm=true)",
                        "clean_placeholder_bounds",
                        "clean_placeholder_bounds(confirm=true)",
                    ),
                ),
            ),
        ),
        Area(
            "composites",
            "Plants and composite builders (CCGT, OCGT, BESS, co-firing, conversions)",
            "Add one plant as a unit (CCGT / OCGT with part-load and start costs, gas + H2 co-firing, BESS battery) or a "
            "sector-coupling conversion, list and edit the plants in the model, place a composite on several buses, "
            "read plant-level results.",
            ("list_plants", "list_plant_types", "add_plant", "place_composite", "get_plant_results"),
            "plant ccgt ocgt gas turbine combined cycle bess battery cofiring co-firing conversion heat pump boiler chp "
            "composite template place copy paste detach sync 가스터빈 복합 배터리 혼소 플랜트 발전소 변환",
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
                    "see which plants exist and change one",
                    (
                        "list_plants",
                        "edit_plant",
                        "edit_plant(confirm=true)",
                        "get_plant_results",
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
                (
                    "put a composite on several buses, or keep it as a template",
                    (
                        "list_composite_templates",
                        "save_composite_template",
                        "save_composite_template(confirm=true)",
                        "place_composite",
                        "place_composite(confirm=true)",
                    ),
                ),
                (
                    "detach a composite into plain rows, or re-sync edited sheet rows",
                    (
                        "detach_composite",
                        "detach_composite(confirm=true)",
                        "sync_composites",
                        "sync_composites(confirm=true)",
                    ),
                ),
            ),
        ),
        Area(
            "p2x",
            "Power-to-X (hydrogen, ammonia, methanol, e-fuel)",
            "Technology data, preview and build of an electrolyser / storage / synthesis chain, RFNBO settings and pre-solve checks, "
            "LCOH / LCOA / LCOM results of a stored run.",
            ("list_p2x_technologies", "preview_p2x_chain", "build_p2x_chain", "get_p2x_results"),
            "p2x power-to-x hydrogen h2 electrolyser electrolysis ammonia methanol e-fuel lcoh lcoa lcom rfnbo additionality "
            "temporal matching hourly monthly 수소 생산 단가 전해조 암모니아 메탄올 재생연료",
            (
                (
                    "hydrogen production cost (LCOH)",
                    (
                        "list_p2x_technologies",
                        "get_p2x_chain_defaults",
                        "preview_p2x_chain",
                        "build_p2x_chain(confirm=true)",
                        "submit_solve",
                        "get_p2x_results",
                    ),
                ),
                (
                    "RFNBO-compliant hydrogen",
                    (
                        "get_rfnbo_config",
                        "set_rfnbo_config",
                        "check_rfnbo",
                        "build_p2x_chain(confirm=true)",
                        "submit_solve(confirm=true)",
                        "get_p2x_results",
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
            "maintenance outage rolling horizon control panel switch toggle on off disable constraint filter carrier "
            "램프 기동 정지 시간 스냅샷 정비 스위치 제약 끄기 켜기",
            (
                (
                    "state a ramp limit in per-minute or hours",
                    ("get_time_units", "set_time_units", "preview_time_units"),
                ),
                (
                    "switch ramp limits off for coal and gas without deleting the values",
                    ("get_control_switches", "get_column_values", "set_control_switches", "submit_solve(confirm=true)"),
                ),
                (
                    "change the time step to 3 hours",
                    (
                        "retarget_snapshots",
                        "set_weightings_from_spacing",
                        "validate_model",
                    ),
                ),
                (
                    "schedule maintenance",
                    ("set_maintenance", "set_maintenance(confirm=true)", "get_study_result"),
                ),
            ),
        ),
        Area(
            "transforms",
            "Transforms (cluster, slice, merge, sample, reshape)",
            "Reduce or reshape the working model: spatial clustering, temporal clustering, window/bus slice, merge another "
            "model, test-run sampling, demand forecast, series scaling, derive a year from the master.",
            ("cluster_network", "temporal_cluster", "slice_model", "sample_workbook"),
            "cluster reduce aggregate slice window merge sample representative days forecast demand growth ev "
            "scale series master derive 클러스터 축소 병합 샘플링 수요 예측",
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
            "fuel_costs",
            "Fuel prices and variable O&M",
            "Fuel prices per carrier (a constant or a series, in MWh_thermal or the fuel's native unit), variable O&M, per-scenario fuel "
            "prices for stochastic runs: marginal cost = fuel / efficiency + VOM. Read the inputs, preview the resulting costs.",
            ("get_fuel_inputs", "set_fuel_price", "set_vom", "get_fuel_costs"),
            "fuel price gas coal oil biomass uranium mmbtu tonne thermal vom variable o&m marginal cost heat rate efficiency "
            "scenario high low smp 연료 가격 가스 석탄 변동 운영비 한계비용 시계열 시나리오 열효율",
            (
                (
                    "gas price series and VOM",
                    (
                        "get_fuel_inputs",
                        "set_fuel_price",
                        "set_vom",
                        "get_fuel_costs",
                        "submit_solve(confirm=true)",
                        "get_study_result",
                    ),
                ),
                (
                    "high and low gas price scenarios",
                    (
                        "set_fuel_price_scenario",
                        "get_fuel_costs",
                        "describe_run_options",
                        "submit_solve(confirm=true)",
                        "get_study_result",
                    ),
                ),
                (
                    "gas price and carbon price together",
                    (
                        "set_fuel_price",
                        "set_carbon_price",
                        "get_fuel_costs",
                        "submit_scenario(confirm=true)",
                        "compare_runs",
                    ),
                ),
            ),
        ),
        Area(
            "policy",
            "Policy (carbon, budgets, constraints, demand response)",
            "Carbon price (flat or schedule), annual energy/emission budgets, custom constraint DSL, carrier growth limits, "
            "demand response; RFNBO is under p2x, fuel prices under fuel_costs.",
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
                    "cap a carrier's annual energy and see whether it bound",
                    (
                        "get_annual_budgets",
                        "set_annual_budget",
                        "apply_annual_budgets",
                        "submit_solve(confirm=true)",
                        "get_annual_budgets",
                    ),
                ),
                (
                    "add a CO2 cap or a generation limit as a constraint",
                    ("set_custom_dsl", "set_custom_dsl(confirm=true)", "submit_solve"),
                ),
                (
                    "let demand shift in time",
                    ("get_demand_response", "apply_demand_response", "apply_demand_response(confirm=true)", "get_study_result"),
                ),
            ),
        ),
        Area(
            "run",
            "Run and solve",
            "Queue solves (deterministic, stochastic, pathway, rolling and the other modes), watch and cancel them, saved scenarios, "
            "run options and solver reference, stored-run housekeeping.",
            ("submit_solve", "get_queue", "describe_run_options", "submit_scenario"),
            "solve run optimise queue scenario solver options linear programming mip dispatch capacity expansion "
            "pathway multi-period stochastic rolling horizon sclopf mga lp run settings window carbon price discount load shedding "
            "period budget monthly limit 실행 최적화 시나리오 솔버 확률론 다기간 롤링 실행설정 윈도우 월별 제약",
            (
                (
                    "set how the project runs (window, rolling, carbon price, solver)",
                    ("get_run_settings", "set_run_settings", "set_run_settings(confirm=true)", "submit_solve"),
                ),
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
                (
                    "stochastic scenarios with an expected cost",
                    (
                        "describe_run_options(key=options.stochasticConfig)",
                        "submit_solve(confirm=true)",
                        "get_study_result",
                    ),
                ),
                (
                    "multi-period capacity expansion (pathway)",
                    (
                        "describe_run_options(key=options.pathwayConfig)",
                        "submit_solve(confirm=true)",
                        "get_period_results",
                    ),
                ),
                (
                    "rolling-horizon dispatch",
                    (
                        "make_noncyclic_for_rolling",
                        "describe_run_options(key=options.rollingConfig)",
                        "submit_solve(confirm=true)",
                        "get_kpis",
                    ),
                ),
            ),
        ),
        Area(
            "results",
            "Results and analytics",
            "Read stored runs: KPIs, carrier mix, prices, cost, emissions, dispatch series, weighted per-asset totals, PyPSA statistics, "
            "comparison, reports.",
            ("list_runs", "get_kpis", "get_analytics", "get_report"),
            "results kpi cost emissions price dispatch generation capacity factor mix compare runs report statistics "
            "totals asset company pathway period 결과 비용 배출 가격 급전 비교 보고서",
            (
                (
                    "explain a run",
                    ("list_runs", "get_kpis", "get_analytics", "get_report"),
                ),
                (
                    "compare two runs",
                    ("list_runs", "compare_runs", "compare_run_statistics"),
                ),
                (
                    "who produced what, and at what cost",
                    ("get_run_totals", "get_asset_details", "compare_companies"),
                ),
            ),
        ),
        Area(
            "studies",
            "Reliability, market and company studies",
            "Studies that ride a normal solve as options: adequacy (LOLE / EENS), reserves, outage Monte Carlo, ELCC, LMP decomposition, "
            "price formation, merchant revenue, bid strategy, PPA, ESS, company finance, stochastic, near-optimal; procurement hedging.",
            ("describe_studies", "get_study_result", "describe_analytics", "optimize_procurement"),
            "study adequacy reliability lole eens reserve outage monte carlo elcc lmp congestion price formation merchant bid ppa "
            "ess asset swap company finance npv irr stochastic mga near-optimal procurement hedge cvar "
            "신뢰도 예비력 공급 충분성 조달 시장 연구 분석",
            (
                (
                    "run an adequacy and reserve study",
                    (
                        "describe_studies",
                        "describe_run_options",
                        "submit_solve",
                        "submit_solve(confirm=true)",
                        "get_study_result",
                    ),
                ),
                (
                    "merchant revenue or PPA value of one owner",
                    (
                        "describe_studies(study=merchant)",
                        "submit_solve(confirm=true)",
                        "get_study_result",
                        "compare_companies",
                    ),
                ),
                (
                    "what sets the price (price formation, LMP components)",
                    (
                        "submit_solve(confirm=true)",
                        "get_study_result(study=price-formation)",
                        "get_study_result(study=lmp-decomposition)",
                    ),
                ),
                (
                    "storage business case",
                    ("describe_studies(study=ess)", "submit_solve(confirm=true)", "get_study_result(study=ess)"),
                ),
                (
                    "hedge power procurement",
                    ("optimize_procurement",),
                ),
            ),
        ),
        Area(
            "physical_risk",
            "Physical climate risk",
            "A separate subsystem (own session id): seed a portfolio from the model, set perils/climate/horizon, run, "
            "read damage, transition and finance results.",
            ("physical_risk_seed", "physical_risk_run", "physical_risk_report"),
            "physical risk climate flood heat wave wildfire peril ngfs rcp ssp damage transition premium "
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
                (
                    "scan an area for candidate sites",
                    ("siting_scan", "siting_scan(confirm=true)", "siting_cluster_sites", "promote_siting_sites"),
                ),
            ),
        ),
        Area(
            "plugins",
            "Plugins and tab modules",
            "Backend plugins (analysis, contribute, transform, action hooks, uploaded data files) and third-party tab modules: "
            "list, install, run, remove.",
            ("list_plugins", "get_plugin", "run_plugin_analysis", "list_tab_modules"),
            "plugin tab module install uninstall upload analysis contribute transform action hook extension "
            "플러그인 모듈 설치 확장",
            (
                (
                    "run a plugin analysis on a run",
                    ("list_plugins", "get_plugin", "run_plugin_analysis"),
                ),
                (
                    "install a plugin and use it",
                    (
                        "install_plugin",
                        "install_plugin(confirm=true)",
                        "get_plugin",
                        "run_plugin_action(confirm=true)",
                    ),
                ),
                (
                    "install a third-party tab module",
                    (
                        "install_tab_module",
                        "install_tab_module(confirm=true)",
                        "set_tab_module_enabled",
                        "list_tab_modules",
                    ),
                ),
            ),
        ),
        Area(
            "session",
            "Session, journal, server",
            "Undo and journal of edits, revert, clear the session, the project's app settings (modules, run controls, "
            "plugin settings), server health and log, reload the schema, and tool_catalogue (this routing).",
            ("tool_catalogue", "get_journal", "undo_journal_entry", "get_server_info"),
            "undo journal revert history session clear server log health version catalogue routing settings app state "
            "enabled modules preferences currency solver threads 되돌리기 이력 세션 서버 상태 설정 모듈 켜기",
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
                    "read or change the app settings the project carries",
                    ("get_app_state", "set_app_state", "set_app_state(confirm=true)"),
                ),
                (
                    "is the server healthy and which build is it",
                    ("get_server_info", "get_server_log"),
                ),
            ),
        ),
    )
}

# Recipes quoted in the server instructions (area id, index into that area's recipes). Order = display order.
_INSTRUCTION_RECIPES: tuple[tuple[str, int], ...] = (
    ("data", 1),
    ("composites", 0),
    ("p2x", 0),
    ("fuel_costs", 0),
    ("build", 0),
    ("time_ops", 0),
    ("transforms", 0),
    ("run", 0),
    ("run", 2),
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
            ("Ragnarok tool areas (call tool_catalogue(area=<id>) for one area's tools and recipes). "
            "R = read-only, W+confirm = writes, preview first then confirm=true, W = writes without a confirm argument."),
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
    "\n\nStudies (adequacy, reserves, outage Monte Carlo, ELCC, LMP, merchant, PPA, ESS, company finance, stochastic ...) "
    "ride the same solve as options: describe_studies lists each option key and result key, get_study_result reads one "
    "study of a stored run. RFNBO and co-firing limits are run options too (describe_run_options).\n\n"
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
        (f"The server has {len(tools)} tools in {len(AREAS)} areas "
        "(mode: R read-only, W+confirm preview then confirm=true, W writes without confirm)."),
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
