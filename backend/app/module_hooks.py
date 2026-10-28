"""Module hook registry: how a backend module plugs into a run without the core knowing it.

The core ``run_pypsa`` is *build -> optimize -> store*. Anything PyPSA lacks (operating reserves, custom
constraints, market studies, adequacy Monte Carlo, ...) lives in a module package ``backend/app/<module>/``
that processes user data and hands it to PyPSA as a declared constraint or reads the solved network back as a
study. A module declares what it contributes by registering hooks from its ``hooks.py``; the core discovers
those files (:func:`load_modules`, a scan of ``backend/app`` subpackages that have a ``hooks`` submodule) and
never imports a module by name.

Hook kinds, in the order a run reaches them:

``submit``
    ``fn(data: dict) -> dict`` at submit time (``_resolve_payload_model``): may rewrite the run payload
    (scenario overrides, physical-risk uplift, session RFNBO settings) before it is frozen into the queue.
``guard``
    ``fn(ctx)`` before the network is built: refuse (HTTP 400) a combination the module cannot honour.
``build_step``
    ``fn(ctx)`` inside ``build_network`` after the sheets are loaded: a module's rewiring of the workbook
    (demand response). ``ctx.network`` is the network under construction.
``constraints``
    ``prepare(ctx) -> callable | None`` once per run, before the solve (resolve a plan, raise a 400); the
    returned ``extra_functionality(n, snapshots)`` contribution is composed into the one hook PyPSA calls.
``replace_solve``
    ``fn(ctx) -> dict | None`` after the build: return a finished result payload to take over the run
    (rule-based market simulation); ``None`` lets the solve proceed.
``post_solve``
    ``fn(ctx) -> dict`` straight after the solve, before the core reads the network (the stochastic
    collapse to a representative scenario). The returned keys join the payload.
``diagnose``
    ``fn(ctx) -> {"headline": str, "text": str} | None`` when a solve came back unusable (infeasible, or load
    unserved): explain WHY from the built network. The first hook that answers wins; the core words the error.
``study``
    ``fn(ctx) -> dict`` after the core has read the solved network: a study whose result keys join the
    payload. Every declared ``payload_keys`` entry is present in the payload (``None`` when the study did
    not run), so a client never sees a key appear and disappear.

Contract rules (kept here once; ``docs/module.md`` links to this file):

* Ordering comes from the declared ``order`` and the hook id (stable tiebreak), never import order.
* A second claim on the same (kind, hook id) or on the same payload key is a declare-time error.
* One module failing to import is reported in :func:`diagnostics` and skipped; the host runs with zero modules
  (a run then builds, solves and stores, with no constraints and no study payload).
* The hooks only see :class:`RunContext`; a module must not reach into the core's private helpers.
"""
from __future__ import annotations

import contextlib
import importlib
import importlib.util
import logging
import pkgutil
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

_log = logging.getLogger(__name__)

KINDS = ("submit", "guard", "build_step", "constraints", "replace_solve", "post_solve", "study", "diagnose")


class HookConflict(ValueError):
    """Two modules claimed the same hook id or the same payload key (a declare-time error)."""


@dataclass
class RunContext:
    """What a hook may read about the run. Fields fill in as the run progresses; a hook uses only the
    ones its phase guarantees (``guard``: options only; ``study``: everything)."""

    model: dict[str, list[dict[str, Any]]] | None = None
    scenario: dict[str, Any] = field(default_factory=dict)
    options: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    network: Any = None  # pypsa.Network (built, and solved from ``post_solve`` on)
    currency: str = "$"
    owner_column: str = "owner"
    emissions_factors: dict[str, float] = field(default_factory=dict)
    snapshot_count: int = 0
    snapshot_weight: float = 1.0
    solver_options: dict[str, Any] = field(default_factory=dict)
    oo: Any = None  # parsed optimise options
    io_api: str = "direct"
    pathway: Any = None
    rolling: Any = None
    stochastic: Any = None
    sampling: Any = None
    sclopf_enabled: bool = False
    pf_enabled: bool = False
    contingency_enabled: bool = False
    mga_enabled: bool = False
    # Per-run scratch space a module may use to hand data from its ``constraints`` hook to its ``study`` hook.
    state: dict[str, Any] = field(default_factory=dict)

    @property
    def incompatible_modes(self) -> list[str]:
        """Names of the core study/solve modes active in this run (for a module's exclusivity guard)."""
        names = {
            "rolling horizon": self.rolling is not None and bool(getattr(self.rolling, "enabled", False)),
            "stochastic": self.stochastic is not None and bool(getattr(self.stochastic, "enabled", False)),
            "security-constrained": self.sclopf_enabled,
            "sampled-block": self.sampling is not None and bool(getattr(self.sampling, "enabled", False)),
            "power-flow": self.pf_enabled,
            "contingency": self.contingency_enabled,
        }
        return [k for k, v in names.items() if v]


@dataclass(frozen=True)
class Hook:
    kind: str
    hook_id: str
    module: str
    order: int
    fn: Callable[..., Any]
    payload_keys: tuple[str, ...] = ()


_hooks: dict[str, dict[str, Hook]] = {k: {} for k in KINDS}
_claimed_keys: dict[str, str] = {}
_loaded = False
_diagnostics: list[dict[str, str]] = []


def register(
    kind: str,
    hook_id: str,
    fn: Callable[..., Any],
    *,
    module: str,
    order: int = 100,
    payload_keys: tuple[str, ...] = (),
) -> Hook:
    """Declare a hook. Raises :class:`HookConflict` on a duplicate (kind, id) or payload key."""
    if kind not in _hooks:
        raise ValueError(f"unknown hook kind {kind!r}; expected one of {KINDS}")
    if payload_keys and kind not in ("study", "post_solve"):
        raise ValueError("only study / post_solve hooks declare payload_keys")
    if hook_id in _hooks[kind]:
        raise HookConflict(f"{kind} hook {hook_id!r} is already registered by module {_hooks[kind][hook_id].module!r}")
    for key in payload_keys:
        if key in _claimed_keys:
            raise HookConflict(f"payload key {key!r} is already claimed by hook {_claimed_keys[key]!r}")
    hook = Hook(kind, hook_id, module, order, fn, tuple(payload_keys))
    _hooks[kind][hook_id] = hook
    for key in payload_keys:
        _claimed_keys[key] = hook_id
    return hook


def hooks(kind: str) -> list[Hook]:
    """Registered hooks of a kind, ordered by (order, hook id)."""
    load_modules()
    return sorted(_hooks[kind].values(), key=lambda h: (h.order, h.hook_id))


def registered() -> dict[str, list[dict[str, Any]]]:
    """Declared hooks as data (for docs and the contract test): kind -> [{id, module, order, payloadKeys}]."""
    return {
        kind: [
            {"id": h.hook_id, "module": h.module, "order": h.order, "payloadKeys": list(h.payload_keys)}
            for h in hooks(kind)
        ]
        for kind in KINDS
    }


def declared_payload_keys() -> tuple[str, ...]:
    """Every payload key a post_solve / study hook declares."""
    load_modules()
    return tuple(sorted(_claimed_keys))


# ── discovery ────────────────────────────────────────────────────────────────

def load_modules() -> None:
    """Import ``backend.app.<pkg>.hooks`` for every subpackage that has one (once, in name order).

    A module whose ``hooks`` fails to import is recorded in :func:`diagnostics` and skipped, so one bad
    module never takes the host down. The scan is by directory content, not a hardcoded list.
    """
    global _loaded
    if _loaded:
        return
    _loaded = True
    import backend.app as app_pkg

    for info in sorted(pkgutil.iter_modules(app_pkg.__path__), key=lambda i: i.name):
        if not info.ispkg:
            continue
        name = f"{app_pkg.__name__}.{info.name}.hooks"
        try:
            if importlib.util.find_spec(name) is None:
                continue
            importlib.import_module(name)
        except Exception as exc:  # noqa: BLE001 - a broken module is reported and skipped
            _log.exception("module %s failed to load its hooks", info.name)
            _diagnostics.append({"module": info.name, "error": f"{type(exc).__name__}: {exc}"})


def diagnostics() -> list[dict[str, str]]:
    """Modules that failed to load their hooks (empty when every module loaded)."""
    load_modules()
    return list(_diagnostics)


@contextlib.contextmanager
def isolated(empty: bool = True) -> Iterator[None]:
    """Temporarily swap the registry (tests: an empty host, or a throwaway module)."""
    global _loaded
    load_modules()
    saved = ({k: dict(v) for k, v in _hooks.items()}, dict(_claimed_keys), _loaded)
    if empty:
        for k in _hooks:
            _hooks[k] = {}
        _claimed_keys.clear()
    try:
        yield
    finally:
        _hooks.clear()
        _hooks.update(saved[0])
        _claimed_keys.clear()
        _claimed_keys.update(saved[1])
        _loaded = saved[2]


# ── runners (what the core calls) ────────────────────────────────────────────

def run_submit(data: dict[str, Any]) -> dict[str, Any]:
    """Pass the run payload dict through every ``submit`` hook, in order."""
    for h in hooks("submit"):
        data = h.fn(data)
    return data


def run_guards(ctx: RunContext) -> None:
    """Run every ``guard`` hook (before the build); a refusal raises ``HTTPException`` from the hook."""
    for h in hooks("guard"):
        h.fn(ctx)


def run_build_steps(ctx: RunContext) -> None:
    """Run every ``build_step`` hook against ``ctx.network``."""
    for h in hooks("build_step"):
        h.fn(ctx)


def compose_constraints(ctx: RunContext) -> Callable[[Any, Any], None]:
    """Prepare every ``constraints`` hook, and return the one ``extra_functionality(n, snapshots)``.

    A module's ``prepare(ctx)`` runs now (so a bad plan is a 400 before the solve) and returns its
    contribution, or ``None`` when it has nothing to add for this run.
    """
    parts = [fn for fn in (h.fn(ctx) for h in hooks("constraints")) if fn is not None]

    def extra_functionality(n: Any, snapshots: Any) -> None:
        for part in parts:
            part(n, snapshots)

    return extra_functionality


def run_replace_solve(ctx: RunContext) -> dict[str, Any] | None:
    """First ``replace_solve`` hook that returns a payload wins; ``None`` when none takes over."""
    for h in hooks("replace_solve"):
        result = h.fn(ctx)
        if result is not None:
            return result
    return None


def _run_payload_hooks(kind: str, ctx: RunContext) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for h in hooks(kind):
        produced = h.fn(ctx) or {}
        for key in h.payload_keys:
            out.setdefault(key, None)
        out.update(produced)
    return out


def run_post_solve(ctx: RunContext) -> dict[str, Any]:
    """Run the ``post_solve`` hooks; returns their payload keys."""
    return _run_payload_hooks("post_solve", ctx)


def run_studies(ctx: RunContext) -> dict[str, Any]:
    """Run the ``study`` hooks; returns their payload keys (declared keys default to ``None``)."""
    return _run_payload_hooks("study", ctx)


def run_diagnose(ctx: RunContext) -> dict[str, str] | None:
    """Explanation of a failed solve from the first ``diagnose`` hook that has one (``headline`` and ``text``)."""
    for h in hooks("diagnose"):
        diag = h.fn(ctx)
        if diag:
            return diag
    return None
