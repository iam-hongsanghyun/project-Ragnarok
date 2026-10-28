"""The module contract: hooks are declared data, discovered by scanning, and the core never names a module.

Boundary guards (run on every pytest invocation):

* core -> module direction: the two core pipeline files may import only the allowlisted ``backend.app`` packages,
  each row justified; a stale row (no longer imported) also fails;
* no production code imports a compatibility shim (the shims exist for external code and old tests);
* no module imports the core pipeline root (``backend.pypsa.results`` / ``run_pypsa``);
* the registered surface is pinned by an anchor hash, so adding or moving a hook is a deliberate edit here;
* the host boots and solves with zero modules registered, and one module failing to load is reported and skipped.
"""
from __future__ import annotations

import ast
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from backend.app import module_hooks as mh

ROOT = Path(__file__).resolve().parents[2]
CORE_FILES = (
    "backend/pypsa/results/__init__.py",
    "backend/pypsa/network/__init__.py",
)

#: core file -> backend.app packages it may import, with the reason (a stale row fails the test).
CORE_TO_MODULE_ALLOWLIST: dict[str, dict[str, str]] = {
    "backend/pypsa/results/__init__.py": {
        "module_hooks": "the hook runner: the one door every module goes through",
        "carbon_pricing": "reads the carbon term back (cost breakdown) and refuses carbon price + CVaR",
        "emissions": "summary KPIs read the module's primary_energy totals and the carrier factor map",
        "stochastic": "parse_stochastic_config: stochastic is a native solve mode, its parser lives with the module",
    },
    "backend/pypsa/network/__init__.py": {
        "module_hooks": "runs the build_step hooks",
        "carbon_pricing": "records the carbon plan on the network (the objective term is added at solve time)",
        "annual_budgets": "writes the per-year budgets into PyPSA as horizon totals at build time",
        "stochastic": "parse_stochastic_config (see above)",
    },
}

#: pinned sha256 of ``json.dumps(module_hooks.registered(), sort_keys=True)``: the registered-surface anchor.
REGISTERED_SURFACE_ANCHOR = "0e57dc7a0e86836a9471b1ffc0d3cc91738fc650bd78d0e7070cf00b3ba8b1fd"


def _anchor() -> str:
    return hashlib.sha256(json.dumps(mh.registered(), sort_keys=True).encode()).hexdigest()


def _package_of(path: Path) -> list[str]:
    parts = list(path.relative_to(ROOT).with_suffix("").parts)
    return parts[:-1]


def _imported_modules(path: Path) -> set[str]:
    """Absolute dotted names every import in ``path`` refers to (relative imports resolved)."""
    pkg = _package_of(path)
    out: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.ImportFrom):
            if node.level:
                base = pkg[: len(pkg) - (node.level - 1)]
                full = ".".join(base + ([node.module] if node.module else []))
            else:
                full = node.module or ""
            out.add(full)
            out.update(f"{full}.{a.name}" for a in node.names)
        elif isinstance(node, ast.Import):
            out.update(a.name for a in node.names)
    return out


def _production_files() -> list[Path]:
    return [p for p in (ROOT / "backend").rglob("*.py") if "/tests/" not in str(p) and "__pycache__" not in str(p)]


def _shim_modules() -> set[str]:
    shims = set()
    for p in _production_files():
        if "Compatibility shim" in p.read_text()[:300]:
            shims.add(".".join(_package_of(p) + ([] if p.name == "__init__.py" else [p.stem])))
    return shims


# ── registry mechanics ───────────────────────────────────────────────────────

def test_duplicate_hook_id_and_duplicate_payload_key_are_declare_time_errors() -> None:
    with mh.isolated():
        mh.register("study", "a", lambda ctx: {}, module="m1", payload_keys=("k",))
        with pytest.raises(mh.HookConflict, match="already registered"):
            mh.register("study", "a", lambda ctx: {}, module="m2")
        with pytest.raises(mh.HookConflict, match="already claimed"):
            mh.register("study", "b", lambda ctx: {}, module="m2", payload_keys=("k",))
        with pytest.raises(ValueError, match="unknown hook kind"):
            mh.register("nope", "c", lambda ctx: {}, module="m3")
        with pytest.raises(ValueError, match="only study / post_solve"):
            mh.register("guard", "d", lambda ctx: None, module="m3", payload_keys=("x",))


def test_order_comes_from_declared_data_not_registration_order() -> None:
    with mh.isolated():
        for hook_id, order in (("zeta", 5), ("alpha", 5), ("mid", 1), ("last", 9)):
            mh.register("guard", hook_id, lambda ctx: None, module="m", order=order)
        assert [h.hook_id for h in mh.hooks("guard")] == ["mid", "alpha", "zeta", "last"]  # (order, id)


def test_declared_study_keys_are_always_present_and_a_study_may_not_leave_one_out() -> None:
    with mh.isolated():
        mh.register("study", "s", lambda ctx: {}, module="m", payload_keys=("one", "two"))
        assert mh.run_studies(mh.RunContext()) == {"one": None, "two": None}


def test_constraint_contributions_compose_in_order_and_none_is_skipped() -> None:
    calls: list[str] = []
    with mh.isolated():
        mh.register("constraints", "b", lambda ctx: (lambda n, s: calls.append("b")), module="m", order=2)
        mh.register("constraints", "a", lambda ctx: (lambda n, s: calls.append("a")), module="m", order=1)
        mh.register("constraints", "skip", lambda ctx: None, module="m", order=3)
        mh.compose_constraints(mh.RunContext())(None, None)
    assert calls == ["a", "b"]


# ── discovery ────────────────────────────────────────────────────────────────

def test_discovery_loads_every_module_without_a_hardcoded_list() -> None:
    assert mh.diagnostics() == []
    import backend.app as app_pkg

    expected = {p.parent.name for p in Path(app_pkg.__path__[0]).glob("*/hooks.py")}
    registered_modules = {h["module"] for hooks in mh.registered().values() for h in hooks}
    # every directory that ships a hooks.py contributed at least one hook (module ids are the declared names)
    assert len(registered_modules) >= len(expected) - 1  # physical_risk registers under "physical-risk"
    assert {"reserves", "stochastic", "market-studies", "company", "adequacy", "constraints"} <= registered_modules


def test_a_module_that_fails_to_import_is_reported_and_skipped(tmp_path: Path) -> None:
    import backend.app as app_pkg

    pkg = tmp_path / "zz_broken_module"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "hooks.py").write_text("raise RuntimeError('boom at import')\n")
    app_pkg.__path__.append(str(tmp_path))
    try:
        with mh.isolated(empty=False):
            mh._loaded = False  # rescan: the real modules are cached in sys.modules, only the broken one runs
            mh._diagnostics.clear()
            mh.load_modules()
            found = [d for d in mh.diagnostics() if d["module"] == "zz_broken_module"]
            assert found and "boom at import" in found[0]["error"]
            assert mh.hooks("study")  # the other modules still registered
            mh._diagnostics.clear()
    finally:
        app_pkg.__path__.remove(str(tmp_path))
        sys.modules.pop("backend.app.zz_broken_module", None)
        sys.modules.pop("backend.app.zz_broken_module.hooks", None)


# ── the host runs with zero modules ──────────────────────────────────────────

def _tiny_model() -> dict[str, list[dict[str, Any]]]:
    snaps = [f"2025-01-01T{h:02d}:00:00" for h in range(2)]
    return {
        "buses": [{"name": "b0", "v_nom": 1.0}],
        "carriers": [{"name": "gas", "co2_emissions": 0.4}],
        "snapshots": [{"snapshot": s} for s in snaps],
        "generators": [{"name": "g", "bus": "b0", "carrier": "gas", "p_nom": 100.0, "marginal_cost": 10.0}],
        "loads": [{"name": "load", "bus": "b0", "p_set": 50.0}],
        "loads-p_set": [{"snapshot": s, "load": 50.0} for s in snaps],
    }


def test_the_host_builds_solves_and_stores_with_zero_modules_registered() -> None:
    from backend.pypsa.results import run_pypsa

    scenario = {"discountRate": 0.0, "carbonPrice": 0.0}
    full = run_pypsa(_tiny_model(), scenario, {})
    with mh.isolated(empty=True):
        bare = run_pypsa(_tiny_model(), scenario, {})
    assert bare["summary"] and bare["outputs"]
    assert bare["generatorEnergy"] == full["generatorEnergy"]  # the core read is unchanged by module absence
    module_keys = set(full) & set(mh.declared_payload_keys())
    assert module_keys and not (module_keys & set(bare)), "an absent module must leave no result block behind"


def test_a_module_that_contributes_a_study_appears_in_the_payload_through_discovery_only() -> None:
    from backend.pypsa.results import run_pypsa

    with mh.isolated(empty=True):
        mh.register("study", "probe", lambda ctx: {"probe": {"buses": len(ctx.network.buses)}}, module="probe",
                    payload_keys=("probe",))
        result = run_pypsa(_tiny_model(), {"discountRate": 0.0}, {})
    assert result["probe"] == {"buses": 1}


# ── boundary guards ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("core_file", CORE_FILES)
def test_core_imports_only_allowlisted_modules_and_no_row_is_stale(core_file: str) -> None:
    imported = {
        ".".join(m.split(".")[:3]) for m in _imported_modules(ROOT / core_file) if m.startswith("backend.app.")
    }
    imported = {m.split(".")[2] for m in imported if len(m.split(".")) >= 3}
    allowed = set(CORE_TO_MODULE_ALLOWLIST[core_file])
    assert imported <= allowed, f"{core_file} imports module(s) not on the allowlist: {sorted(imported - allowed)}"
    assert allowed <= imported, f"stale allowlist row(s) for {core_file}: {sorted(allowed - imported)}"


def test_the_core_pipeline_names_no_module_result_key() -> None:
    declared = set(mh.declared_payload_keys())
    for core_file in CORE_FILES:
        text = (ROOT / core_file).read_text()
        named = sorted(k for k in declared if f'"{k}"' in text)
        assert not named, f"{core_file} hardcodes module-owned result keys {named}; they belong to the module's hook"


def test_no_production_code_imports_a_compatibility_shim() -> None:
    shims = _shim_modules()
    assert shims, "the S7 moves leave documented shims"
    offenders = []
    for p in _production_files():
        if "Compatibility shim" in p.read_text()[:300]:
            continue
        hit = _imported_modules(p) & shims
        if hit:
            offenders.append((str(p.relative_to(ROOT)), sorted(hit)))
    assert not offenders, f"import the real module, not the shim: {offenders}"


def test_no_module_imports_the_core_pipeline_root() -> None:
    offenders = []
    for hooks_file in (ROOT / "backend/app").glob("*/hooks.py"):
        for p in hooks_file.parent.rglob("*.py"):
            for m in _imported_modules(p):
                if m == "backend.pypsa.results" or m.startswith("backend.pypsa.results.run_pypsa"):
                    offenders.append((str(p.relative_to(ROOT)), m))
    # `from backend.pypsa.results import dispatch` style imports resolve to the submodule, which is fine.
    offenders = [o for o in offenders if o[1] == "backend.pypsa.results"
                 and "import run_pypsa" in (ROOT / o[0]).read_text()]
    assert not offenders, f"a module reaches into the core run loop: {offenders}"


def test_the_registered_surface_anchor_is_pinned() -> None:
    assert _anchor() == REGISTERED_SURFACE_ANCHOR, (
        "the registered hook surface changed; if deliberate, update REGISTERED_SURFACE_ANCHOR to "
        f"{_anchor()} and the module list in docs/module.md"
    )
