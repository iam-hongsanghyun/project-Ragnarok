"""Load scaling to match a target annual energy (TWh)."""
from __future__ import annotations

import pandas as pd
import pypsa


def scale_load(
    network: pypsa.Network,
    target_load_twh: float,
    base_year: int,
) -> None:
    r"""Scale load to a target annual energy, holding *additional* demand fixed.

    Demand that did not exist in the base year — "additional" load, identified by
    a ``build_year`` (on the load itself **or** on its bus) strictly **after**
    ``base_year`` — is kept exactly as imported.  Only the pre-existing
    ("distributable") load is scaled, and only by enough to make the
    **whole-system** annual energy equal ``target_load_twh``.  The additional
    demand therefore sits on top of the target and the legacy load fills the
    remainder:

    Algorithm:
        $$ E_{add} = \sum_{i \in \text{new}} \sum_t p^{set}_{i,t},\qquad
           E_{dist} = \sum_{i \notin \text{new}} \sum_t p^{set}_{i,t} $$
        $$ s = \frac{E_{target} - E_{add}}{E_{dist}},\qquad
           p^{set}_{i,t} \leftarrow s\, p^{set}_{i,t}\ \ (i \notin \text{new}) $$

        E_add  = Σ p_set over loads built after base_year        [MWh]
        E_dist = Σ p_set over the remaining (pre-existing) loads  [MWh]
        s      = (target_MWh − E_add) / E_dist         (dimensionless)
        distributable loads ×= s ;  additional loads unchanged

    When no load is "additional" (no ``build_year`` column, or none after
    ``base_year``) this reduces to ``E_add = 0`` and the plain uniform scale
    ``s = target / Σ p_set`` — identical to the previous behaviour.

    Args:
        network:         PyPSA Network to modify in place.
        target_load_twh: Target **whole-system** annual energy in TWh.  ``0`` (or
            empty in the dashboard) means "do not scale".
        base_year:       A load is "additional" iff its (or its bus's)
            ``build_year`` is strictly greater than this.

    Raises:
        ValueError: When the additional demand alone meets or exceeds the target
            — no non-negative scaling of the legacy load can then hit the target.
    """
    p_set = network.loads_t.p_set
    sum_mwh = float(p_set.sum().sum())
    original_twh = sum_mwh / 1e6

    if target_load_twh <= 0:
        print(
            f"  Load scaling: skipped (load cell empty or 0) — "
            f"using original profile ({original_twh:.1f} TWh)"
        )
        return

    # Identify additional (post-base-year) loads via build_year on the load or
    # its bus.  NaN/absent build_year → pre-existing (distributable).
    loads = network.loads
    is_additional = pd.Series(False, index=loads.index)
    if "build_year" in loads.columns:
        load_by = pd.to_numeric(loads["build_year"], errors="coerce")
        is_additional |= load_by > base_year
    if "build_year" in network.buses.columns and "bus" in loads.columns:
        bus_by = pd.to_numeric(network.buses["build_year"], errors="coerce")
        is_additional |= loads["bus"].map(bus_by) > base_year

    additional = [c for c in p_set.columns if c in is_additional.index and bool(is_additional[c])]
    distributable = [c for c in p_set.columns if c not in set(additional)]

    add_mwh = float(p_set[additional].sum().sum()) if additional else 0.0
    dist_mwh = float(p_set[distributable].sum().sum()) if distributable else 0.0
    target_mwh = target_load_twh * 1e6
    dist_target_mwh = target_mwh - add_mwh

    if dist_mwh <= 0:
        print(
            f"  Load scaling: no distributable (pre-{base_year}) load to scale — "
            f"leaving all {original_twh:.1f} TWh as-is"
        )
        return
    if dist_target_mwh <= 0:
        raise ValueError(
            f"Load scaling: additional demand ({add_mwh / 1e6:.1f} TWh, built after "
            f"{base_year}) already meets or exceeds the target ({target_load_twh:.1f} "
            f"TWh). Cannot hold it fixed and still reach the target by scaling the "
            f"legacy load — raise the target or reduce the new demand."
        )

    scale_factor = dist_target_mwh / dist_mwh
    scaled = p_set.copy()
    scaled[distributable] = scaled[distributable] * scale_factor
    network.loads_t.p_set = scaled

    if additional:
        print(
            f"  Load scaled: legacy ×{scale_factor:.4f} → {dist_target_mwh / 1e6:.1f} TWh, "
            f"+ {add_mwh / 1e6:.1f} TWh additional held fixed = {target_load_twh:.1f} TWh "
            f"(was {original_twh:.1f} TWh)"
        )
    else:
        print(
            f"  Load scaled by {scale_factor:.4f}  "
            f"({original_twh:.1f} TWh → {target_load_twh:.1f} TWh)"
        )
