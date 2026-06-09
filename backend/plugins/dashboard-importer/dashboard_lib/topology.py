"""Network topology transformations.

Public entry point :func:`apply_topology` dispatches on
``settings.grid_mode``:

================================  ==========================================
``grid_mode``                     Action
================================  ==========================================
``single``                        :func:`collapse_to_single_bus`
``line_to_link``                  :func:`line_to_link`
``merge_line_transformer``        :func:`merge_line_transformer`
``as-is`` (or anything else)      Imported topology kept unchanged.
================================  ==========================================

For energy-balance / dispatch studies (no power-flow analysis) the two new
modes replace the Kirchhoff Voltage Law constraints — whose tiny
susceptance coefficients (``b · z_base``, ~1e-3) cause HiGHS dual-simplex
blow-up on the meshed Korean grid — with a transport network of
bidirectional ``Link`` components.
"""
from __future__ import annotations

import pandas as pd
import pypsa

# Forward-only typing to avoid a cycle with :mod:`lib.settings`
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lib.settings import Settings


def collapse_to_single_bus(network: pypsa.Network, bus_name: str) -> None:
    """Collapse the network to a single bus, removing all lines and transformers.

    All generators and storage units are reassigned to *bus_name*.
    All loads are **aggregated** into a single ``load_total`` object:

    - Time-series ``p_set`` columns are summed into one column.
    - Static ``p_set`` scalars are summed into one scalar.

    Lines, transformers, and original buses are removed.

    Args:
        network: PyPSA Network to modify in place.
        bus_name: Name of the single aggregated bus (from dashboard ``Single_bus`` row).
    """
    LOAD_NAME = "load_total"

    # 1. Add the single aggregated bus
    network.add("Bus", bus_name, carrier="AC")

    # 2. Aggregate all loads into one ──────────────────────────────────────
    if not network.loads_t.p_set.empty:
        agg_p_set_t = network.loads_t.p_set.sum(axis=1)   # Series: snapshot → MW
    else:
        agg_p_set_t = None

    agg_p_set_scalar = (
        float(network.loads["p_set"].sum())
        if "p_set" in network.loads.columns
        else 0.0
    )

    network.remove("Load", network.loads.index)
    network.add(
        "Load",
        LOAD_NAME,
        bus=bus_name,
        carrier="load",
        p_set=agg_p_set_scalar if agg_p_set_t is None else 0.0,
    )

    if agg_p_set_t is not None:
        network.loads_t.p_set = pd.DataFrame(
            {LOAD_NAME: agg_p_set_t}, index=network.snapshots
        )

    # 3. Reassign generators and storage units
    network.generators["bus"] = bus_name
    if not network.storage_units.empty:
        network.storage_units["bus"] = bus_name

    # 4. Remove transmission
    if not network.lines.empty:
        network.remove("Line", network.lines.index)
    if not network.transformers.empty:
        network.remove("Transformer", network.transformers.index)

    # 5. Remove all original buses (now unreferenced)
    original = network.buses.index[network.buses.index != bus_name]
    if len(original):
        network.remove("Bus", original)

    total_mw = agg_p_set_scalar if agg_p_set_t is None else float(agg_p_set_t.mean())
    print(
        f"  Topology: single bus '{bus_name}'  "
        f"({len(network.generators)} generators, 1 load  "
        f"[avg {total_mw:.1f} MW])"
    )


def _validate_loss(link_loss: float) -> None:
    if not (0.0 <= link_loss < 1.0):
        raise ValueError(f"link_loss must be in [0, 1) — got {link_loss!r}")


def _add_bidirectional_link(
    network: pypsa.Network,
    bus0: str,
    bus1: str,
    p_nom: float,
) -> None:
    """Add one **lossless** bidirectional Link named ``link_<a>_<b>``.

    Links here represent simple transmission corridors between regions — they
    are transport elements, not generators, so they must conserve energy.

    A bidirectional Link (``p_min_pu = -1``) MUST be lossless
    (``efficiency = 1.0``).  PyPSA enforces ``p1 = -efficiency · p0``, so the
    net energy a Link injects into the grid is ``p0 · (efficiency - 1)``:

    * forward flow  (p0 > 0): ``p0·(η-1) < 0`` → consumes energy (a real loss)
    * reverse flow  (p0 < 0): ``p0·(η-1) > 0`` → **creates energy from nothing**

    With ``η < 1`` the cost-minimising solver drives reverse flows to
    manufacture free energy, so total generation falls below total load.  A
    lossless link gives ``p0 + p1 = 0`` in both directions — pure transport.
    """
    a, b = sorted((bus0, bus1))
    network.add(
        "Link",
        f"link_{a}_{b}",
        bus0=a,
        bus1=b,
        p_nom=p_nom,
        efficiency=1.0,   # lossless — see docstring; bidirectional + η<1 creates energy
        p_min_pu=-1.0,
    )


def line_to_link(network: pypsa.Network, link_loss: float) -> None:
    """Replace every line and transformer with a bidirectional ``Link``.

    Links here are simple transmission representatives between buses/regions:
    transport elements, not generators.  This function builds them as
    **lossless bidirectional** links (``η = 1``, ``p_min_pu = -1``) as a
    structural intermediate.  The configured ``link_loss`` is applied later by
    :func:`apply_link_losses`, which splits each bidirectional link into two
    one-directional lossy links (``η = 1 − link_loss`` each way).

    The two-step design exists because a *single* bidirectional link with
    ``η < 1`` is not energy-consistent — on reverse flow PyPSA's
    ``p1 = -η·p0`` makes the link inject energy (see
    :func:`_add_bidirectional_link`).  Keeping the structural step lossless
    also lets parallel-link deduplication and region aggregation operate on a
    single link per corridor; the loss is applied once, last.

    All buses are kept.  Parallel lines + transformers between the same
    unordered ``{bus0, bus1}`` pair are **deduplicated** — capacities summed.

    Algorithm:
        $$p^{\\mathrm{nom}}_{\\{a,b\\}} = \\sum_{\\ell \\,:\\, \\{a,b\\}}
          s^{\\mathrm{nom}}_\\ell$$

        ASCII:
          p_nom_{a,b} = sum_{ℓ in lines+trafos with {bus0,bus1}={a,b}} s_nom_ℓ

    Args:
        network:   PyPSA Network to modify in place.
        link_loss: Validated here; the actual loss is applied downstream by
                   :func:`apply_link_losses`. Must satisfy ``0 ≤ link_loss < 1``.

    Raises:
        ValueError: If ``link_loss`` is outside ``[0, 1)``.
    """
    _validate_loss(link_loss)

    edges: dict[frozenset[str], float] = {}  # pair → summed p_nom

    def _accumulate(df: pd.DataFrame) -> int:
        if df.empty:
            return 0
        n = 0
        for _, row in df.iterrows():
            a, b = str(row["bus0"]), str(row["bus1"])
            if a == b:
                continue
            pair = frozenset((a, b))
            cap = float(row.get("s_nom", 0.0) or 0.0)
            edges[pair] = edges.get(pair, 0.0) + cap
            n += 1
        return n

    n_lines = _accumulate(network.lines)
    n_trafos = _accumulate(network.transformers)

    if not network.lines.empty:
        network.remove("Line", network.lines.index)
    if not network.transformers.empty:
        network.remove("Transformer", network.transformers.index)

    for pair, p_nom in edges.items():
        a, b = sorted(pair)
        _add_bidirectional_link(network, a, b, p_nom)

    if link_loss > 0:
        print(
            f"  Topology: line_to_link  (link_loss={link_loss:.3f} will be applied "
            f"later by splitting each link into two one-directional lossy links)"
        )
    print(
        f"  Topology: line_to_link  "
        f"({n_lines} lines + {n_trafos} transformers → "
        f"{len(edges)} unique bidirectional links)"
    )


def merge_line_transformer(network: pypsa.Network, link_loss: float) -> None:
    """Merge transformer-connected buses into substations, then turn lines into Links.

    Transformer endpoints are treated as the **same physical location**
    (different voltage levels of one substation).  Buses linked through any
    chain of transformers are unioned into a substation group; one canonical
    bus per group survives, the rest are dropped.  All component bus
    references (generators, loads, storage units, stores, lines, links) are
    rewritten to the canonical bus.

    Lines that become self-loops after the merge are discarded; lines that
    end up parallel are summed.  The remaining unique pairs become **lossless
    bidirectional** ``Link`` components as a structural intermediate; the
    configured ``link_loss`` is applied later by :func:`apply_link_losses`
    (which splits each into two one-directional lossy links).

    Canonical-bus selection: the bus with the **highest** ``v_nom`` in the
    group; ties broken lexicographically by name.

    Algorithm:
        groups       = connected_components(G_trafo)        # union-find
        canonical(g) = argmax_{b ∈ g}( v_nom(b), -name(b) )
        for component c:  c.bus_ref ← canonical(group(c.bus_ref))
        drop self-loop lines
        merge parallel lines: p_nom_{a,b} = Σ s_nom_ℓ

    Args:
        network:   PyPSA Network to modify in place.
        link_loss: Validated here; the actual loss is applied downstream by
                   :func:`apply_link_losses`. Must satisfy ``0 ≤ link_loss < 1``.

    Raises:
        ValueError: If ``link_loss`` is outside ``[0, 1)``.
    """
    _validate_loss(link_loss)

    n_buses_before = len(network.buses)
    n_lines_before = len(network.lines)
    n_trafos_before = len(network.transformers)

    # 1. Union-find: group every bus joined through any chain of transformers
    parent: dict[str, str] = {b: b for b in network.buses.index}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for _, row in network.transformers.iterrows():
        union(str(row["bus0"]), str(row["bus1"]))

    # 2. Canonical bus per group: max v_nom, then lex(name)
    v_nom = (
        network.buses["v_nom"]
        if "v_nom" in network.buses.columns
        else pd.Series(0.0, index=network.buses.index)
    )
    groups: dict[str, list[str]] = {}
    for b in network.buses.index:
        groups.setdefault(find(b), []).append(b)

    canonical: dict[str, str] = {}
    for members in groups.values():
        max_v = max(float(v_nom.get(m, 0.0)) for m in members)
        ties = [m for m in members if float(v_nom.get(m, 0.0)) == max_v]
        best = sorted(ties)[0]
        for m in members:
            canonical[m] = best

    # 3. Remap every component's bus references
    def _remap(df: pd.DataFrame, cols: list[str]) -> None:
        if df.empty:
            return
        for c in cols:
            if c in df.columns:
                df[c] = df[c].map(lambda x: canonical.get(str(x), str(x)))

    _remap(network.generators,    ["bus"])
    _remap(network.loads,         ["bus"])
    _remap(network.storage_units, ["bus"])
    _remap(network.stores,        ["bus"])
    _remap(network.lines,         ["bus0", "bus1"])
    _remap(network.links,         ["bus0", "bus1"])

    # 4. Drop transformers (now intra-substation)
    if not network.transformers.empty:
        network.remove("Transformer", network.transformers.index)

    # 5. Aggregate remaining lines into deduplicated unordered pairs
    edges: dict[frozenset[str], float] = {}
    for _, row in network.lines.iterrows():
        a, b = str(row["bus0"]), str(row["bus1"])
        if a == b:
            continue                       # self-loop after merge
        pair = frozenset((a, b))
        cap = float(row.get("s_nom", 0.0) or 0.0)
        edges[pair] = edges.get(pair, 0.0) + cap

    if not network.lines.empty:
        network.remove("Line", network.lines.index)

    # 6. Drop now-unused (non-canonical) buses
    keep = set(canonical.values())
    drop = [b for b in network.buses.index if b not in keep]
    if drop:
        network.remove("Bus", drop)

    # 7. Add the deduplicated, lossless bidirectional Links
    for pair, p_nom in edges.items():
        a, b = sorted(pair)
        _add_bidirectional_link(network, a, b, p_nom)

    print(
        f"  Topology: merge_line_transformer  "
        f"({n_buses_before} buses → {len(network.buses)} substations, "
        f"{n_lines_before} lines + {n_trafos_before} transformers → "
        f"{len(edges)} unique lossless links)"
    )


def apply_link_losses(network: pypsa.Network, link_loss: float) -> None:
    """Split every bidirectional Link into a forward + reverse lossy pair.

    Transmission corridors are built upstream as **lossless bidirectional**
    Links (``p_min_pu = -1``, ``efficiency = 1``) so that the structural steps
    (line→link conversion, region aggregation, parallel-link deduplication)
    stay simple and energy-consistent.  This final step applies the physical
    line loss the right way: a corridor that can flow either way over time but
    only one way per snapshot is modelled as **two one-directional links**:

        link_<a>_<b>      a → b   p_min_pu = 0   η = 1 − link_loss
        link_<b>_<a>      b → a   p_min_pu = 0   η = 1 − link_loss

    Because each link is forward-only (``p_min_pu = 0`` ⇒ ``p0 ≥ 0``), its net
    grid injection ``p0·(η−1) ≤ 0`` is always a loss — never the phantom-energy
    *gain* a single bidirectional link with ``η < 1`` produces on reverse flow.
    The solver picks whichever direction it needs each hour; it never drives
    both at once because simultaneous counter-flow only wastes energy (and so
    raises generation cost), so a no-op when ``link_loss == 0``.

    Args:
        network:   PyPSA Network to modify in place.
        link_loss: Fractional per-corridor loss (e.g. ``0.03`` → 3 %).
                   When ``0`` the lossless bidirectional links are left as-is.

    Raises:
        ValueError: If ``link_loss`` is outside ``[0, 1)``.
    """
    _validate_loss(link_loss)
    if link_loss == 0.0 or network.links.empty:
        return

    eta = 1.0 - link_loss
    links = network.links.copy()

    def _p_min(name: str) -> float:
        try:
            return float(links.at[name, "p_min_pu"])
        except (KeyError, TypeError, ValueError):
            return 0.0

    bidirectional = [n for n in links.index if _p_min(n) < 0]
    if not bidirectional:
        return

    new: list[tuple[str, str, str, float, object]] = []  # name, bus0, bus1, p_nom, carrier
    for name in bidirectional:
        row = links.loc[name]
        bus0, bus1 = str(row["bus0"]), str(row["bus1"])
        try:
            p_nom = float(row.get("p_nom", 0.0) or 0.0)
        except (TypeError, ValueError):
            p_nom = 0.0
        carrier = row.get("carrier") if "carrier" in links.columns else None
        new.append((f"link_{bus0}_{bus1}", bus0, bus1, p_nom, carrier))   # forward
        new.append((f"link_{bus1}_{bus0}", bus1, bus0, p_nom, carrier))   # reverse

    network.remove("Link", bidirectional)
    for nm, b0, b1, p_nom, carrier in new:
        attrs = dict(bus0=b0, bus1=b1, p_nom=p_nom, efficiency=eta, p_min_pu=0.0)
        if carrier is not None and pd.notna(carrier):
            attrs["carrier"] = str(carrier)
        network.add("Link", nm, **attrs)

    print(
        f"  Topology: link losses applied — split {len(bidirectional)} "
        f"bidirectional links into {len(new)} one-directional links "
        f"(η = 1 − {link_loss:.3f} = {eta:.3f} each way)"
    )


def apply_topology(network: pypsa.Network, settings: "Settings") -> None:
    """Dispatch on ``settings.grid_mode`` and apply the matching transform.

    Recognised values:

    * ``single``                  → :func:`collapse_to_single_bus`
    * ``line_to_link``            → :func:`line_to_link`
    * ``merge_line_transformer``  → :func:`merge_line_transformer`
    * any other value (incl. ``as-is``) → no-op, prints the chosen mode.

    Args:
        network:  PyPSA Network to modify in place.
        settings: Parsed dashboard :class:`~lib.settings.Settings`.  This
            function reads ``grid_mode``, ``single_bus``, and ``link_loss``.
    """
    mode = settings.grid_mode
    if mode == "single":
        collapse_to_single_bus(network, settings.single_bus)
    elif mode == "line_to_link":
        line_to_link(network, settings.link_loss)
    elif mode == "merge_line_transformer":
        merge_line_transformer(network, settings.link_loss)
    else:
        print(f"  Topology: as-is  ({len(network.buses)} buses, "
              f"{len(network.lines)} lines, {len(network.transformers)} transformers)")


def drop_components_with_missing_buses(network: pypsa.Network) -> None:
    """Remove components that reference buses absent from the network.

    Checks generators, loads, storage units, lines, transformers, and links.
    Safe to call after any topology reduction (e.g. after
    :func:`collapse_to_single_bus`).

    Args:
        network: PyPSA Network to modify in place.
    """
    valid_buses = set(network.buses.index)
    removed_count = 0

    single_bus_components = [
        ("Generator", network.generators),
        ("Load", network.loads),
        ("StorageUnit", network.storage_units),
    ]

    for component_type, df in single_bus_components:
        if not df.empty and "bus" in df.columns:
            invalid = df.index[~df["bus"].isin(valid_buses)]
            if len(invalid):
                network.remove(component_type, invalid)
                removed_count += len(invalid)
                print(f"    Removed {len(invalid)} {component_type.lower()}(s) with missing buses")

    dual_bus_components = [
        ("Line", network.lines),
        ("Transformer", network.transformers),
        ("Link", network.links),
    ]

    for component_type, df in dual_bus_components:
        if not df.empty:
            invalid = df.index[
                ~df["bus0"].isin(valid_buses) | ~df["bus1"].isin(valid_buses)
            ]
            if len(invalid):
                network.remove(component_type, invalid)
                removed_count += len(invalid)
                print(f"    Removed {len(invalid)} {component_type.lower()}(s) with missing buses")

    if removed_count == 0:
        print("  No components with missing buses found")
