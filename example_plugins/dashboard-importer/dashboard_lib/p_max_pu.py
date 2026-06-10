"""Apply province- and carrier-aware per-unit capacity-factor profiles to generators."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pypsa


def apply_standard_p_max_pu(network: pypsa.Network, excel_path: str) -> None:
    """Populate ``generators_t.p_max_pu`` from a ``standard_p_max_pu`` sheet.

    The sheet uses a **two-row header**:

    - **Row 1 (province):** blank for generic/fallback columns, Korean province
      name for province-specific columns.
    - **Row 2 (carrier):** ``solar``, ``wind``, ``hydro``, etc.
    - **Column 1:** snapshot timestamps (used as the index).

    Matching priority for each generator:

    1. ``(generator.province, generator.carrier)`` — province-specific profile.
    2. ``(generic_sentinel, generator.carrier)`` — fallback for provinces not
       in the sheet, or for generators with no province value.

    The generic sentinel is detected automatically: any level-0 column value
    that does **not** appear as a province in ``network.generators["province"]``
    is treated as the generic sentinel (typically the forward-filled index-column
    label, e.g. ``"Province"``).

    Only activates when both conditions hold:

    1. ``generators_t.p_max_pu`` is currently empty.
    2. The Excel file contains a sheet named ``standard_p_max_pu``.

    Args:
        network: PyPSA Network to modify in place.
        excel_path: Path to the Excel workbook containing the
            ``standard_p_max_pu`` sheet.
    """
    if not network.generators_t.p_max_pu.empty:
        return

    last_error: Exception | None = None
    for engine in ("calamine", "openpyxl"):
        try:
            xl = pd.ExcelFile(excel_path, engine=engine)
            break
        except Exception as exc:
            last_error = exc
    else:
        raise ImportError(
            "Unable to read standard_p_max_pu sheet. "
            "Install `python-calamine` or `openpyxl`."
        ) from last_error

    if "standard_p_max_pu" not in xl.sheet_names:
        return

    # Read two-row header; first column becomes the snapshot index
    standard = xl.parse("standard_p_max_pu", header=[0, 1], index_col=0)

    # Normalise the MultiIndex: strip whitespace from both levels
    standard.columns = pd.MultiIndex.from_tuples(
        [(str(p).strip(), str(c).strip()) for p, c in standard.columns],
        names=["province", "carrier"],
    )

    # Identify generic-sentinel label(s):
    # any level-0 value that is NOT a known generator province is the sentinel.
    gen_provinces: set[str] = (
        set(network.generators["province"].dropna().astype(str).str.strip())
        if "province" in network.generators.columns
        else set()
    )
    sheet_level0: set[str] = set(standard.columns.get_level_values("province"))
    generic_labels: set[str] = sheet_level0 - gen_provinces  # e.g. {"Province"}

    available_carriers: set[str] = set(standard.columns.get_level_values("carrier"))
    matched = network.generators[network.generators["carrier"].isin(available_carriers)]
    if matched.empty:
        return

    result: dict[str, np.ndarray] = {}
    province_hits = 0
    generic_hits = 0

    for gen_name, gen in matched.iterrows():
        carrier = str(gen["carrier"]).strip()
        province = (
            str(gen["province"]).strip()
            if "province" in gen.index and pd.notna(gen["province"])
            else ""
        )

        # 1. Province-specific match
        province_key = (province, carrier)
        if province and province_key in standard.columns:
            result[gen_name] = standard[province_key].values
            province_hits += 1
            continue

        # 2. Generic fallback
        for glabel in generic_labels:
            generic_key = (glabel, carrier)
            if generic_key in standard.columns:
                result[gen_name] = standard[generic_key].values
                generic_hits += 1
                break

    if result:
        network.generators_t.p_max_pu = pd.DataFrame(result, index=network.snapshots)
        print(
            f"  p_max_pu applied to {len(result)} generators "
            f"({province_hits} province-matched, {generic_hits} generic fallback)"
        )
