"""PyPSA-native file formats and grid-model importers (P18, P41, P42, P43).

Everything here goes through PyPSA's own importers/exporters so a format change
in PyPSA never has to be re-implemented:

* Excel / CSV-folder import and export (``import_from_excel(engine="calamine")``,
  ``import_from_csv_folder``, ``export_to_excel``, ``export_to_csv_folder``).
* MATPOWER ``.m`` / ``.mat`` case files -> PYPOWER ``ppc`` dict ->
  ``import_from_pypower_ppc`` (a small parser; no extra dependency).
* pandapower nets via ``import_from_pandapower_net`` -- pandapower is an
  OPTIONAL dependency (installing it downgrades numpy/pandas in the PyPSA 1.4
  environment), so it is imported lazily and reported cleanly when absent.
* netCDF export options: ``compression``, ``float32``, ``export_standard_types``.
* ``Lines.apply_seasonal_rating`` as a workbook transform.
"""
from __future__ import annotations

import io
import re
import tempfile
import zipfile
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pypsa

from .serialize import network_to_model
from .snapshots import parse_snapshot_labels

# ── export options (P43) ─────────────────────────────────────────────────────


def netcdf_export_kwargs(options: dict[str, Any] | None) -> dict[str, Any]:
    """``export_to_netcdf`` keyword arguments from run/export ``options``.

    Option keys: ``exportStandardTypes`` (bool), ``netcdfFloat32`` (bool),
    ``netcdfCompression`` (``true`` -> zlib level 4 | int 1-9 -> that zlib level |
    dict -> passed to xarray as the per-variable encoding, e.g.
    ``{"zlib": true, "complevel": 5}``; false/absent -> none).
    """
    options = options or {}
    kwargs: dict[str, Any] = {}
    if options.get("exportStandardTypes"):
        kwargs["export_standard_types"] = True
    if options.get("netcdfFloat32"):
        kwargs["float32"] = True
    comp = options.get("netcdfCompression")
    if isinstance(comp, dict) and comp:
        kwargs["compression"] = dict(comp)
    elif isinstance(comp, bool) and comp:
        kwargs["compression"] = {"zlib": True, "complevel": 4}
    elif isinstance(comp, (int, float)) and not isinstance(comp, bool) and comp > 0:
        kwargs["compression"] = {"zlib": True, "complevel": int(min(max(comp, 1), 9))}
    return kwargs


def export_network_bytes(
    network: pypsa.Network, fmt: str, options: dict[str, Any] | None = None
) -> tuple[bytes, str, str]:
    """Serialise ``network`` -> ``(bytes, media_type, filename)``.

    ``fmt`` is ``netcdf`` | ``hdf5`` | ``excel`` | ``csv`` (zip of a CSV folder).
    """
    options = options or {}
    std = bool(options.get("exportStandardTypes"))
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        if fmt == "netcdf":
            path = base / "network.nc"
            network.export_to_netcdf(str(path), **netcdf_export_kwargs(options))
            return path.read_bytes(), "application/x-netcdf", "ragnarok_network.nc"
        if fmt == "hdf5":
            path = base / "network.h5"
            network.export_to_hdf5(str(path), export_standard_types=std)
            return path.read_bytes(), "application/x-hdf5", "ragnarok_network.h5"
        if fmt == "excel":
            path = base / "network.xlsx"
            network.export_to_excel(str(path), export_standard_types=std)
            return (
                path.read_bytes(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "ragnarok_pypsa_network.xlsx",
            )
        if fmt == "csv":
            folder = base / "csv"
            folder.mkdir()
            network.export_to_csv_folder(str(folder), export_standard_types=std)
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                for f in sorted(folder.rglob("*")):
                    if f.is_file():
                        zf.write(f, f.relative_to(folder).as_posix())
            return buf.getvalue(), "application/zip", "ragnarok_pypsa_csv.zip"
    raise ValueError(f"unknown export format {fmt!r}; expected netcdf | hdf5 | excel | csv")


# ── PyPSA-native imports (P41) ────────────────────────────────────────────────


def network_from_excel(data: bytes, *, skip_time: bool = False, engine: str = "calamine") -> pypsa.Network:
    """``Network.import_from_excel`` on an uploaded ``.xlsx`` (calamine reader)."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "network.xlsx"
        path.write_bytes(data)
        n = pypsa.Network()
        n.import_from_excel(str(path), skip_time=skip_time, engine=engine)
    return n


def network_from_csv_zip(data: bytes, *, skip_time: bool = False) -> pypsa.Network:
    """``Network.import_from_csv_folder`` on a zip of a PyPSA CSV folder.

    The CSVs may sit at the zip root or inside one top-level folder.
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            for member in zf.namelist():
                target = (root / member).resolve()
                if root.resolve() not in target.parents and target != root.resolve():
                    raise ValueError(f"unsafe path in zip: {member}")
            zf.extractall(root)
        folder = root
        if not (folder / "buses.csv").exists() and not (folder / "network.csv").exists():
            subs = [p for p in root.iterdir() if p.is_dir() and not p.name.startswith("__")]
            for sub in subs:
                if (sub / "buses.csv").exists() or (sub / "network.csv").exists():
                    folder = sub
                    break
        n = pypsa.Network()
        n.import_from_csv_folder(str(folder), skip_time=skip_time)
    return n


# ── MATPOWER / PYPOWER (P42) ──────────────────────────────────────────────────

_MPC_FIELDS = ("baseMVA", "bus", "gen", "branch", "gencost")


def _parse_matrix(body: str) -> np.ndarray:
    rows: list[list[float]] = []
    for raw in body.replace("\r", "").split("\n"):
        line = raw.split("%", 1)[0].strip()
        for chunk in line.split(";"):
            chunk = chunk.strip()
            if not chunk:
                continue
            vals = [float(tok) for tok in re.split(r"[\s,]+", chunk) if tok]
            if vals:
                rows.append(vals)
    if not rows:
        return np.zeros((0, 0))
    width = max(len(r) for r in rows)
    out = np.full((len(rows), width), np.nan)
    for i, r in enumerate(rows):
        out[i, : len(r)] = r
    return out


def parse_matpower_m(text: str) -> dict[str, Any]:
    """Parse a MATPOWER ``.m`` case (``mpc.baseMVA`` / ``bus`` / ``gen`` / ``branch`` / ``gencost``)."""
    ppc: dict[str, Any] = {}
    m = re.search(r"mpc\.baseMVA\s*=\s*([-+0-9.eE]+)\s*;", text)
    if not m:
        raise ValueError("not a MATPOWER case: mpc.baseMVA not found")
    ppc["baseMVA"] = float(m.group(1))
    v = re.search(r"mpc\.version\s*=\s*['\"]?(\w+)['\"]?\s*;", text)
    ppc["version"] = v.group(1) if v else "2"
    for field in ("bus", "gen", "branch", "gencost"):
        mm = re.search(rf"mpc\.{field}\s*=\s*\[(.*?)\]\s*;", text, flags=re.S)
        if mm:
            ppc[field] = _parse_matrix(mm.group(1))
    missing = [f for f in ("bus", "gen", "branch") if f not in ppc]
    if missing:
        raise ValueError(f"MATPOWER case is missing mpc.{', mpc.'.join(missing)}")
    return ppc


def load_matpower_mat(data: bytes) -> dict[str, Any]:
    """Read a MATPOWER ``.mat`` file (struct ``mpc`` or top-level matrices)."""
    from scipy.io import loadmat

    mat = loadmat(io.BytesIO(data), squeeze_me=True, struct_as_record=False)
    src: Any = mat.get("mpc")
    ppc: dict[str, Any] = {}
    for field in _MPC_FIELDS:
        val = getattr(src, field, None) if src is not None else mat.get(field)
        if val is not None:
            ppc[field] = float(val) if field == "baseMVA" else np.atleast_2d(np.asarray(val, dtype=float))
    if "baseMVA" not in ppc or any(f not in ppc for f in ("bus", "gen", "branch")):
        raise ValueError("MAT file has no MATPOWER case (need mpc.baseMVA, bus, gen, branch)")
    ver = getattr(src, "version", None) if src is not None else mat.get("version")
    ppc["version"] = str(ver) if ver is not None else "2"
    return ppc


def network_from_ppc(ppc: dict[str, Any], overwrite_zero_s_nom: float | None = None) -> pypsa.Network:
    """``Network.import_from_pypower_ppc`` -- PyPSA does the MATPOWER/PYPOWER mapping."""
    n = pypsa.Network()
    n.import_from_pypower_ppc(ppc, overwrite_zero_s_nom=overwrite_zero_s_nom)
    return n


def network_from_matpower(
    data: bytes, filename: str = "case.m", overwrite_zero_s_nom: float | None = None
) -> pypsa.Network:
    """MATPOWER ``.m`` or ``.mat`` bytes -> ``pypsa.Network`` via ``import_from_pypower_ppc``."""
    if filename.lower().endswith(".mat"):
        ppc = load_matpower_mat(data)
    else:
        ppc = parse_matpower_m(data.decode("utf-8", errors="replace"))
    return network_from_ppc(ppc, overwrite_zero_s_nom=overwrite_zero_s_nom)


class PandapowerUnavailable(RuntimeError):
    """pandapower is not installed (optional dependency)."""


def network_from_pandapower_json(
    text: str, *, extra_line_data: bool = False, use_pandapower_index: bool = False
) -> pypsa.Network:
    """pandapower net (``pandapower.to_json`` text) -> ``import_from_pandapower_net``.

    Raises :class:`PandapowerUnavailable` when pandapower is not installed.
    """
    try:
        import pandapower as pp  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - exercised only without the lib
        raise PandapowerUnavailable(
            "pandapower is not installed in this environment (it pins older numpy/pandas than "
            "PyPSA 1.4). Convert the net to MATPOWER with pandapower.converter.to_ppc / "
            "pp.converter.to_mpc and import that instead, or `pip install pandapower` in an "
            "environment that allows it."
        ) from exc
    net = pp.from_json_string(text)
    n = pypsa.Network()
    n.import_from_pandapower_net(
        net, extra_line_data=extra_line_data, use_pandapower_index=use_pandapower_index
    )
    return n


def pandapower_available() -> bool:
    try:
        import pandapower  # noqa: F401  # type: ignore[import-not-found]
    except ImportError:
        return False
    return True


# ── Lines.apply_seasonal_rating as a workbook transform (P18) ─────────────────


def seasonal_rating_transform(
    model: dict[str, list[dict[str, Any]]],
    ratings: dict[str, dict[str, float]],
    summer_months: list[int] | None = None,
    compose: bool = True,
) -> dict[str, Any]:
    """Write ``lines-s_max_pu`` from per-line summer/winter MVA ratings.

    Delegates to PyPSA's ``Lines.apply_seasonal_rating`` on a scratch network that
    carries the model's snapshots, lines (``s_nom``, static ``s_max_pu``) and any
    existing ``lines-s_max_pu`` series, so month handling, ``compose`` and the
    validation (positive ratings and ``s_nom``, known lines) are PyPSA's own.

    Args:
        model: workbook model (needs ``snapshots`` with datetime labels and ``lines``).
        ratings: ``{line: {"summer": MVA, "winter": MVA}}``.
        summer_months: months treated as summer (default PyPSA NH ``4..9``).
        compose: multiply into any existing ``s_max_pu`` (True) or overwrite.

    Returns:
        ``{"model", "lines", "summerMonths", "compose", "snapshots"}`` -- the model with an
        updated ``lines-s_max_pu`` sheet; ``s_nom`` is unchanged.
    """
    snap_rows = model.get("snapshots") or []
    labels = [
        str(r.get("snapshot") or r.get("name") or r.get("datetime") or r.get("timestep") or "").strip()
        for r in snap_rows
    ]
    labels = [x for x in labels if x]
    if not labels:
        raise ValueError("The model has no snapshots; seasonal ratings need datetime snapshots.")
    try:
        index = parse_snapshot_labels(labels)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"Snapshot labels are not datetimes: {exc}") from exc
    line_rows = [r for r in (model.get("lines") or []) if str(r.get("name") or "").strip()]
    if not line_rows:
        raise ValueError("The model has no lines.")
    if not ratings:
        raise ValueError("ratings is empty; pass {line: {summer, winter}}.")
    for ln, rt in ratings.items():
        if not isinstance(rt, dict) or "summer" not in rt or "winter" not in rt:
            raise ValueError(f"ratings[{ln!r}] must have 'summer' and 'winter' MVA values.")

    n = pypsa.Network()
    n.set_snapshots(index)
    buses = sorted({str(r.get(c)) for r in line_rows for c in ("bus0", "bus1") if r.get(c)})
    if buses:
        n.add("Bus", buses)
    for r in line_rows:
        kw: dict[str, Any] = {"bus0": str(r.get("bus0") or buses[0]), "bus1": str(r.get("bus1") or buses[-1])}
        for key in ("s_nom", "s_max_pu"):
            v = r.get(key)
            if v not in (None, ""):
                kw[key] = float(v)
        n.add("Line", str(r["name"]), x=0.1, **kw)
    existing = model.get("lines-s_max_pu") or []
    if existing:
        frame = pd.DataFrame(existing)
        key_col = "snapshot" if "snapshot" in frame.columns else frame.columns[0]
        frame.index = parse_snapshot_labels(frame.pop(key_col).astype(str))
        frame = frame.apply(pd.to_numeric, errors="coerce")
        cols = [c for c in frame.columns if c in n.lines.index]
        if cols:
            n.lines_t.s_max_pu = frame[cols].reindex(index)

    table = pd.DataFrame(
        {"summer": {k: float(v["summer"]) for k, v in ratings.items()},
         "winter": {k: float(v["winter"]) for k, v in ratings.items()}}
    )
    months = tuple(int(m) for m in summer_months) if summer_months else (4, 5, 6, 7, 8, 9)
    n.c.lines.apply_seasonal_rating(table, summer_months=months, compose=compose)

    series = n.lines_t.s_max_pu
    rated_cols = [c for c in series.columns]
    out_rows: list[dict[str, Any]] = []
    for label, (_, vals) in zip(labels, series[rated_cols].iterrows()):
        row: dict[str, Any] = {"snapshot": label}
        row.update({str(c): float(v) for c, v in vals.items() if pd.notna(v)})
        out_rows.append(row)
    new_model = dict(model)
    new_model["lines-s_max_pu"] = out_rows
    return {
        "model": new_model,
        "lines": sorted(str(k) for k in ratings),
        "summerMonths": list(months),
        "compose": compose,
        "snapshots": len(labels),
    }


def model_from_network(network: pypsa.Network) -> dict[str, list[dict[str, Any]]]:
    """Workbook-model JSON of an imported network (shared by all import endpoints)."""
    return network_to_model(network)
