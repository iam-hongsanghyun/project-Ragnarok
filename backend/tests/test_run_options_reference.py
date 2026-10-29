"""The run-options reference (WA5) against what the frontend actually sends.

The reference is the single place an MCP client learns every run key, so it must not
lag the browser. These tests parse the TypeScript *textually* (no node needed) and
fail when the frontend sends a key, or a config interface carries a field, that
``backend/app/run_options_reference.py`` does not document, or when a documented
default drifts from the frontend's ``default*Config()`` functions.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from backend.app import run_options_reference as ref
from backend.app import main as _app  # noqa: F401 - importing the app imports every router, which registers its options
from backend.app import scenario_presets as sp

SRC = Path(__file__).resolve().parents[2] / "frontend" / "Ragnarok_default" / "src"

pytestmark = pytest.mark.skipif(not SRC.is_dir(), reason="frontend sources not in this checkout")


def _read(rel: str) -> str:
    return (SRC / rel).read_text(encoding="utf-8")


def _interface_fields(source: str, name: str) -> list[str]:
    match = re.search(rf"export interface {name}\b[^{{]*\{{(.*?)\n\}}", source, re.DOTALL)
    assert match, f"interface {name} not found in lib/types"
    return re.findall(r"^  (\w+)\??:", match.group(1), re.MULTILINE)


# ── the frontend's top-level keys ────────────────────────────────────────────


def _object_keys(source: str, opener: str) -> list[str]:
    """Top-level (4-space indented) keys of the object literal that starts at ``opener``."""
    start = source.index(opener) + len(opener)
    end = source.index("\n  };", start)
    return re.findall(r"^    (\w+)\s*[:,]", source[start:end], re.MULTILINE)


def test_every_key_build_run_payload_sends_is_documented() -> None:
    source = _read("features/scenario/buildRunPayload.ts")
    scenario_keys = _object_keys(source, "const scenario = {")
    option_keys = _object_keys(source, "const options: Record<string, unknown> = {")
    option_keys += re.findall(r"^\s+options\.(\w+) = ", source, re.MULTILINE)
    assert len(option_keys) > 40 and "carbonPrice" in scenario_keys  # the parse found the objects
    keys = ref.top_level_keys()
    missing_scenario = sorted(set(scenario_keys) - set(keys["scenario"]))
    missing_options = sorted(set(option_keys) - set(keys["options"]))
    assert not missing_scenario, f"scenario keys sent by the UI but not in the reference: {missing_scenario}"
    assert not missing_options, f"options keys sent by the UI but not in the reference: {missing_options}"


def test_batch_run_label_the_app_adds_is_documented() -> None:
    app = _read("App.tsx")
    sent = set(re.findall(r"\boptions\.(\w+) = ", app))
    assert "runLabel" in sent
    assert not (sent - set(ref.top_level_keys()["options"]))


# config interface -> where its fields live in the reference
_BLOCKS = {
    "PathwayConfig": "options.pathwayConfig",
    "RollingHorizonConfig": "options.rollingConfig",
    "SamplingConfig": "options.samplingConfig",
    "StochasticConfig": "options.stochasticConfig",
    "SecurityConstrainedConfig": "options.securityConstrainedConfig",
    "ReserveConfig": "options.reserveConfig",
    "OutageMcConfig": "options.outageMcConfig",
    "CorrelatedSamplingConfig": "options.correlatedSamplingConfig",
    "RampConfig": "options.rampConfig",
    "ElccConfig": "options.elccConfig",
    "ConvergenceConfig": "options.convergenceConfig",
    "LmpDecompositionConfig": "options.lmpDecompositionConfig",
    "PowerFlowConfig": "options.powerFlowConfig",
    "MarketSimConfig": "options.marketSimConfig",
    "ContingencyConfig": "options.contingencyConfig",
    "MgaConfig": "options.mgaConfig",
    "MerchantConfig": "options.merchantConfig",
    "BidStrategyConfig": "options.bidStrategyConfig",
    "AssetSwapConfig": "options.assetSwapConfig",
    "EssConfig": "options.essConfig",
    "PpaConfig": "options.ppaConfig",
    "DemandResponseConfig": "options.demandResponseConfig",
    "FinanceConfig": "options.financeConfig",
    # nested interfaces
    "PathwayPeriodConfig": "options.pathwayConfig.periods[]",
    "StochasticScenarioConfig": "options.stochasticConfig.scenarios[]",
    "StochasticScenarioOverride": "options.stochasticConfig.scenarios[].overrides[]",
    "StrategicBiddingConfig": "options.marketSimConfig.strategic",
    "AssetSwapFilter": "options.assetSwapConfig.removeFilters[]",
    "CarbonPriceScheduleEntry": "options.carbonPriceSchedule[]",
    "ModelOverride": "options.modelOverrides[]",
    "CustomConstraint": "scenario.constraints[]",
}
# Result-only fields that ride on a config interface (PathwayPeriodConfig echoes period results).
_RESULT_ONLY = {("PathwayPeriodConfig", f) for f in ("installedCapacityMw", "storageCapacityMw", "capexAnnual")}


@pytest.mark.parametrize("interface", sorted(_BLOCKS))
def test_every_config_interface_field_is_documented(interface: str) -> None:
    types = _read("lib/types/index.ts")
    documented = ref.documented_paths()
    prefix = _BLOCKS[interface]
    for field in _interface_fields(types, interface):
        if (interface, field) in _RESULT_ONLY:
            continue
        candidates = {f"{prefix}.{field}", f"{prefix}.{field}[]"}
        assert candidates & documented, f"{interface}.{field} is sent by the UI but {prefix}.{field} is not in the reference"


def test_inline_demand_bid_fields_and_constraint_terms_are_documented() -> None:
    types = _read("lib/types/index.ts")
    documented = ref.documented_paths()
    assert {"options.marketSimConfig.demandBids[].fraction", "options.marketSimConfig.demandBids[].wtp"} <= documented
    assert re.search(r"demandBids\?: \{ fraction: number; wtp: number \}\[\]", types)
    # ConstraintSpec terms are documented on the lhs[] entry's meaning text.
    lhs = next(e for e in ref.all_entries() if e.path == "scenario.constraintSpecs[].lhs[]")
    for field in _interface_fields(types, "ConstraintTerm"):
        assert field in lhs.meaning, f"ConstraintTerm.{field} missing from the lhs[] description"
    for field in _interface_fields(types, "ConstraintSpec"):
        assert any(e.path.startswith(f"scenario.constraintSpecs[].{field}") for e in ref.all_entries())


def test_every_unread_or_removed_field_is_not_listed_as_sent() -> None:
    """A field the UI no longer sends must not linger in the reference (D1 clean-up)."""
    types = _read("lib/types/index.ts")
    for interface, gone in (("PathwayConfig", "overridePolicy"), ("RollingHorizonConfig", "stepPolicy")):
        if gone not in _interface_fields(types, interface):
            assert not any(p.endswith(f".{gone}") for p in ref.documented_paths())


# ── defaults ─────────────────────────────────────────────────────────────────

_TS_DEFAULTS = {
    "pathwayConfig": ("lib/results/pathway.ts", "defaultPathwayConfig"),
    "rollingConfig": ("lib/results/rolling.ts", "defaultRollingConfig"),
    "samplingConfig": ("lib/results/sampling.ts", "defaultSamplingConfig"),
    "stochasticConfig": ("lib/results/scenarios.ts", "defaultStochasticConfig"),
    "securityConstrainedConfig": ("lib/results/scenarios.ts", "defaultSclopfConfig"),
    "reserveConfig": ("lib/results/scenarios.ts", "defaultReserveConfig"),
    "outageMcConfig": ("lib/results/scenarios.ts", "defaultOutageMcConfig"),
    "correlatedSamplingConfig": ("lib/results/scenarios.ts", "defaultCorrelatedSamplingConfig"),
    "rampConfig": ("lib/results/scenarios.ts", "defaultRampConfig"),
    "elccConfig": ("lib/results/scenarios.ts", "defaultElccConfig"),
    "convergenceConfig": ("lib/results/scenarios.ts", "defaultConvergenceConfig"),
    "lmpDecompositionConfig": ("lib/results/scenarios.ts", "defaultLmpDecompositionConfig"),
    "powerFlowConfig": ("lib/results/scenarios.ts", "defaultPowerFlowConfig"),
    "marketSimConfig": ("lib/results/scenarios.ts", "defaultMarketSimConfig"),
    "contingencyConfig": ("lib/results/scenarios.ts", "defaultContingencyConfig"),
    "mgaConfig": ("lib/results/scenarios.ts", "defaultMgaConfig"),
    "merchantConfig": ("lib/results/scenarios.ts", "defaultMerchantConfig"),
    "bidStrategyConfig": ("lib/results/scenarios.ts", "defaultBidStrategyConfig"),
    "assetSwapConfig": ("lib/results/scenarios.ts", "defaultAssetSwapConfig"),
    "essConfig": ("lib/results/scenarios.ts", "defaultEssConfig"),
    "ppaConfig": ("lib/results/scenarios.ts", "defaultPpaConfig"),
    "demandResponseConfig": ("lib/results/scenarios.ts", "defaultDemandResponseConfig"),
    "financeConfig": ("lib/results/scenarios.ts", "defaultFinanceConfig"),
}


def _ts_literal(text: str):
    """A TypeScript object/array literal of plain values -> Python (via JSON)."""
    text = re.sub(r"'([^']*)'", r'"\1"', text)
    text = re.sub(r"([{,]\s*)([A-Za-z_]\w*)\s*:", r'\1"\2":', text)
    text = re.sub(r",(\s*[}\]])", r"\1", text)
    return json.loads(text)


def _ts_default(rel: str, fn: str):
    source = _read(rel)
    match = re.search(rf"export function {fn}\(\)[^{{]*\{{\s*return (\{{.*?\}});\s*\}}", source, re.DOTALL)
    assert match, f"{fn} not found in {rel}"
    return _ts_literal(match.group(1))


@pytest.mark.parametrize("block", sorted(_TS_DEFAULTS))
def test_block_defaults_equal_the_frontend_defaults(block: str) -> None:
    rel, fn = _TS_DEFAULTS[block]
    assert sp.CONFIG_BLOCKS[block][0]() == _ts_default(rel, fn)


def test_every_default_key_has_a_reference_entry_and_vice_versa() -> None:
    documented = ref.documented_paths()
    for block, (default_fn, _clone) in sp.CONFIG_BLOCKS.items():
        for key in default_fn():
            assert f"options.{block}.{key}" in documented or f"options.{block}.{key}[]" in documented, (block, key)


def test_reference_default_matches_the_preset_default() -> None:
    by_path = {e.path: e for e in ref.all_entries()}
    assert by_path["options.essConfig.maxHours"].default == 4
    assert by_path["options.marketSimConfig.voll"].default == 3000
    assert by_path["options.essConfig"].default == sp.default_ess_config()


def test_ui_run_defaults_equal_app_config_json() -> None:
    config = json.loads(_read("config/app_config.json"))["settings"]["defaults"]
    for key in ("dateFormat", "solverThreads", "solverType", "objectiveAutoScale", "currencySymbol", "solveAcceptance"):
        assert sp.UI_RUN_DEFAULTS[key] == config[key], key


def test_enums_equal_the_frontend_unions() -> None:
    settings = _read("lib/settings/types.ts")
    by_path = {e.path: e for e in ref.all_entries()}
    for ts_type, path in (("DateFormat", "options.dateFormat"), ("SolverType", "options.solverType"), ("SolveAcceptance", "options.solveAcceptance")):
        union = re.search(rf"export type {ts_type} = ([^;]+);", settings).group(1)
        assert re.findall(r"'([^']+)'", union) == by_path[path].allowed, ts_type


def test_metric_table_equals_metric_defs() -> None:
    text = _read("lib/constants/index.ts")
    defs = dict(re.findall(r"^  (\w+):\s*\{[^\n]*needsCarrier: (true|false)", text, re.MULTILINE))
    assert len(defs) == 12
    metrics = ref.build_reference()["metrics"]
    assert {m: v["needsCarrier"] for m, v in metrics.items()} == {m: d == "true" for m, d in defs.items()}
    assert sp.CARRIER_METRICS == {m for m, d in defs.items() if d == "true"}
    by_path = {e.path: e for e in ref.all_entries()}
    assert by_path["scenario.constraints[].metric"].allowed == sorted(defs)


# ── behaviour ────────────────────────────────────────────────────────────────


def test_every_entry_has_the_fields_an_agent_needs() -> None:
    for entry in ref.all_entries():
        assert entry.path.startswith(("scenario.", "options.")), entry.path
        assert entry.type and entry.meaning, entry.path
        assert entry.reader, f"{entry.path} names no backend reader"
        if entry.path.count(".") == 2 and entry.type == "number" and entry.source == "ui" and "options." in entry.path:
            assert entry.unit is not None, f"{entry.path} is a number with no unit"


def test_the_new_ess_cost_keys_are_documented() -> None:
    fields = {f["path"]: f for f in ref.build_reference("options.essConfig")["fields"]}
    for key in ("capitalCostPerMWh", "fixedOmPerMWYear", "variableCostPerMWh", "lifetimeYears", "standingLoss"):
        assert f"options.essConfig.{key}" in fields
    assert "15" in fields["options.essConfig.lifetimeYears"]["meaning"]


def test_index_is_bounded_and_describes_precedence() -> None:
    doc = ref.build_reference()
    assert len(json.dumps(doc)) < 30_000
    assert any("constraintSpecs" in n and "RAGNAROK_CustomDSL" in n for n in doc["notes"])
    assert {row["key"] for row in doc["index"]} >= {"options.pathwayConfig", "options.essConfig", "scenario.customDsl"}


def test_unknown_key_error_lists_valid_keys() -> None:
    with pytest.raises(KeyError) as exc:
        ref.build_reference("options.nope")
    assert "unknown run-option key" in str(exc.value) and "essConfig" in str(exc.value)


def test_options_patch_validation_names_the_valid_keys() -> None:
    assert ref.validate_options_patch({"forceLp": True}) == []
    problems = ref.validate_options_patch({"forceLP": True})
    assert problems and "forceLP" in problems[0] and "forceLp" in problems[0]


def test_register_options_is_the_extension_point() -> None:
    entry = ref.RunOption("options.zzTestOption", "boolean", "test", False, reader="tests")
    try:
        ref.register_options([entry])
        ref.register_options([entry])  # idempotent
        assert "zzTestOption" in ref.top_level_keys()["options"]
        assert sum(1 for e in ref.all_entries() if e.path == "options.zzTestOption") == 1
    finally:
        ref.EXTRA_OPTIONS[:] = [e for e in ref.EXTRA_OPTIONS if e.path != "options.zzTestOption"]
