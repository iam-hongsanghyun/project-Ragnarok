"""Server-side twins of results the web UI used to compute only in the browser (WA7).

Pure functions (no I/O) so the UI and MCP read the same numbers:

* :func:`derive_asset_details` — ``lib/results/assetDetails.ts`` (per-asset
  generator / bus / storage / store / branch / process / shunt detail series).
* :func:`compute_kpis`          — ``features/analytics/cards/KpiStripCard.tsx``.
* :func:`compare_companies`     — ``features/analytics/cards/CompanyComparisonCard.tsx``.
* :func:`installed_capacity`, :func:`split_capacity_summary`,
  :func:`run_comparison_entry`  — ``features/analytics/ComparisonPane.tsx`` /
  ``ComparisonMatrix.tsx`` (the data half; charts stay in the browser).

Deliberate differences from the TS: colours are presentation, so a ``color`` is
returned only where the model row carries an explicit hex colour (generators /
processes) and carrier-mix items omit it; display strings use ``en-US`` grouping.

Algorithm (KPI strip):
    $$\\text{LF} = \\frac{\\bar P}{P_{peak}},\\quad
      \\bar P = \\frac{\\sum_c E_c}{N\\,w},\\quad
      \\text{RES} = 100\\,\\frac{\\sum_{c\\in R} E_c}{\\sum_c E_c}$$
    ASCII: LF = avg_load / peak_load; avg_load = total_dispatch_MWh / (snapshots * weight_h);
    RES% = 100 * renewable_MWh / total_dispatch_MWh.
    E_c = dispatch of carrier c (MWh); N = snapshot count; w = snapshot weight (h).
"""

from __future__ import annotations

import math
import re
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Callable

Row = dict[str, Any]
Model = dict[str, list[Row]]
Series = dict[str, list[Row]]

_HEX = re.compile(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
_MIN_EFFICIENCY = 1e-6
_NON_RENEWABLE_ZERO_EF = {"nuclear"}


# ── scalar helpers (lib/utils/helpers.ts) ────────────────────────────────────


def number_value(value: Any) -> float:
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(value) else 0.0
    if isinstance(value, str):
        try:
            parsed = float(value)
        except ValueError:
            return 0.0
        return parsed if math.isfinite(parsed) else 0.0
    return 0.0


def string_value(value: Any) -> str:
    return "" if value is None else str(value)


def fmt(n: float, digits: int = 0) -> str:
    """``n.toLocaleString(undefined, {maximumFractionDigits: digits})`` (en-US)."""
    if not math.isfinite(n):
        return "NaN" if math.isnan(n) else ("∞" if n > 0 else "-∞")
    q = Decimal(1).scaleb(-digits)
    rounded = Decimal(repr(n)).quantize(q, rounding=ROUND_HALF_UP)
    text = f"{rounded:,f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


def _fixed(n: float, digits: int) -> str:
    """JS ``Number.prototype.toFixed``."""
    return str(Decimal(repr(n)).quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP))


def _explicit_color(value: Any) -> str | None:
    raw = string_value(value).strip()
    return raw if _HEX.match(raw) else None


def _index_by_name(rows: list[Row] | None) -> dict[str, Row]:
    out: dict[str, Row] = {}
    for row in rows or []:
        name = string_value(row.get("name"))
        if name:
            out[name] = row
    return out


# ── snapshot axis + input-profile lookup (assetDetails.ts) ───────────────────


def _iso_to_label(iso: str) -> str:
    t = iso.find("T")
    if t < 0 or len(iso) < t + 6:
        return iso
    return iso[t + 1 : t + 6]


def _pick_snapshot_rows(series: Series | None, preferred: list[str]) -> list[Row]:
    if not series:
        return []
    for key in preferred:
        rows = series.get(key)
        if rows:
            return rows
    for rows in series.values():
        if rows:
            return rows
    return []


def filter_series_by_period(series: Series, period: int | None) -> Series:
    """Keep only ``period`` rows (rows without a numeric period pass through)."""
    if period is None:
        return series
    out: Series = {}
    for sheet, rows in series.items():
        kept = []
        for row in rows or []:
            raw = row.get("period")
            if raw is None or raw == "" or number_value(raw) == period:
                kept.append(row)
        out[sheet] = kept
    return out


def snapshot_periods(series: Series | None, preferred: list[str]) -> list[int | None]:
    """Investment period of each snapshot row (None when absent / non-integer)."""
    out: list[int | None] = []
    for r in _pick_snapshot_rows(series, preferred):
        raw = r.get("period")
        if raw is None or raw == "":
            out.append(None)
            continue
        try:
            n = float(raw)
        except (TypeError, ValueError):
            out.append(None)
            continue
        out.append(int(n) if math.isfinite(n) and n.is_integer() else None)
    return out


def _series_value(rows: list[Row] | None, i: int, column: str) -> float:
    if not rows or i >= len(rows):
        return 0.0
    return number_value(rows[i].get(column))


def _static_or_input(static: dict[str, Any], sheet: str, name: str, attr: str, fallback: float) -> float:
    v = ((static.get(sheet) or {}).get(name) or {}).get(attr)
    if v is None or v == "":
        return fallback
    return number_value(v)


_STAMP_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2})(?:T(\d{2}):(\d{2})(?::(\d{2}))?(?:\.\d+)?(?:Z|[+-]\d{2}(?::?\d{2})?)?)?$"
)


def normalize_stamp(raw: str) -> str:
    """Canonical ``YYYY-MM-DDTHH:MM:SS`` (space -> T, fraction/zone dropped)."""
    if len(raw) == 19 and raw[10] == "T":
        return raw
    m = _STAMP_RE.match(raw.strip().replace(" ", "T", 1))
    if not m:
        return raw
    if m.group(2) is None:
        return m.group(1)
    return f"{m.group(1)}T{m.group(2)}:{m.group(3)}:{m.group(4) or '00'}"


class InputIndex:
    """Timestamp -> row lookup for an input temporal sheet (``indexInputByTimestamp``)."""

    def __init__(self, rows: list[Row] | None, averaging: dict[str, Any] | None = None) -> None:
        self.by_stamp: dict[str, Row] = {}
        self.by_period_stamp: dict[tuple[float, str], Row] = {}
        self.columns: set[str] = set()
        self.has_period = False
        if not rows or "snapshot" not in rows[0]:
            return
        self.has_period = "period" in rows[0]
        self.columns = {k for k in rows[0] if k not in ("snapshot", "period")}
        for row in rows:
            raw = string_value(row.get("snapshot"))
            if not raw:
                continue
            stamp = normalize_stamp(raw)
            self.by_stamp[stamp] = row
            if self.has_period and row.get("period") not in (None, ""):
                try:
                    p = float(row["period"])
                except (TypeError, ValueError):
                    continue
                if math.isfinite(p):
                    self.by_period_stamp[(p, stamp)] = row
        if averaging and not self.has_period:
            target = normalize_stamp(averaging["startStamp"])
            start = next(
                (i for i, r in enumerate(rows) if normalize_stamp(string_value(r.get("snapshot"))) == target), -1
            )
            if start >= 0:
                end = min(start + int(averaging["windowRows"]), len(rows))
                block = min(int(averaging["blockSize"]), end - start)
                for j in range(block):
                    avg = dict(rows[start + j])
                    for col in self.columns:
                        total, count = 0.0, 0
                        for k in range(start + j, end, block):
                            cell = rows[k].get(col)
                            if cell is None or cell == "":
                                continue
                            n = number_value(cell)
                            if math.isfinite(n):
                                total += n
                                count += 1
                        if count > 0:
                            avg[col] = total / count
                    self.by_stamp[normalize_stamp(string_value(rows[start + j].get("snapshot")))] = avg

    def value_at(self, stamp: str, col: str, fallback: float, period: float | None = None) -> float:
        """``inputSeriesValueAtStamp``: the temporal column wins over the static scalar."""
        if col not in self.columns:
            return fallback
        key = normalize_stamp(stamp)
        if self.has_period and period is not None:
            row = self.by_period_stamp.get((float(period), key))
        else:
            row = self.by_stamp.get(key)
        cell = row.get(col) if row else None
        if cell is None or cell == "":
            return 0.0
        return number_value(cell)


def input_averaging_from_sampling(sampling: dict[str, Any] | None, start_stamp: str | None) -> dict[str, Any] | None:
    if not sampling or not sampling.get("enabled") or sampling.get("mode") != "average" or not start_stamp:
        return None
    window_rows = number_value(sampling.get("representedSnapshots"))
    block = number_value(sampling.get("blockSize"))
    if not (window_rows > 0 and block > 0):
        return None
    return {"startStamp": start_stamp, "windowRows": window_rows, "blockSize": min(block, window_rows)}


def generator_efficiency(row: Row) -> float:
    eta = number_value(row.get("efficiency"))
    return eta if eta > _MIN_EFFICIENCY else 1.0


def generator_emission_factor(row: Row, carrier_static: dict[str, Row]) -> float:
    """Thermal-basis factor, tCO2 per MWh electrical: carrier co2_emissions / efficiency."""
    carrier = string_value(row.get("carrier")) or "Other"
    return number_value((carrier_static.get(carrier) or {}).get("co2_emissions")) / generator_efficiency(row)


# ── per-asset builders ───────────────────────────────────────────────────────


class _Ctx:
    def __init__(self, model: Model, outputs: dict[str, Any], currency: str, weight: float,
                 snapshots: list[str], periods: list[int | None], averaging: dict[str, Any] | None) -> None:
        self.model = model
        self.series: Series = outputs.get("series") or {}
        self.static: dict[str, Any] = outputs.get("static") or {}
        self.currency = currency
        self.weight = weight
        self.snapshots = snapshots
        self.labels = [_iso_to_label(s) for s in snapshots]
        self.periods = periods
        self.averaging = averaging

    def period(self, i: int) -> int | None:
        return self.periods[i] if i < len(self.periods) else None


def _wants(names: set[str] | None, name: str) -> bool:
    return names is None or name in names


def _build_generators(c: _Ctx, names: set[str] | None) -> dict[str, Any]:
    gen_static = _index_by_name(c.model.get("generators"))
    carrier_static = _index_by_name(c.model.get("carriers"))
    p_series = c.series.get("generators-p")
    p_max_pu_idx = InputIndex(c.model.get("generators-p_max_pu"), c.averaging)
    out: dict[str, Any] = {}
    for name, row in gen_static.items():
        if not _wants(names, name):
            continue
        carrier = string_value(row.get("carrier")) or "Other"
        p_nom_input = number_value(row.get("p_nom"))
        p_nom = _static_or_input(c.static, "generators", name, "p_nom_opt", p_nom_input)
        mc = number_value(row.get("marginal_cost"))
        raw_pmax = row.get("p_max_pu")
        p_max_pu_static = 1.0 if raw_pmax is None or raw_pmax == "" else number_value(raw_pmax)
        efficiency = generator_efficiency(row)
        ef = generator_emission_factor(row, carrier_static)
        time_varying = name in p_max_pu_idx.columns
        output_s, emis_s, avail_s, curt_s = [], [], [], []
        energy = total_em = 0.0
        for i, stamp in enumerate(c.snapshots):
            o = _series_value(p_series, i, name)
            pos = max(o, 0.0)
            ratio = p_max_pu_idx.value_at(stamp, name, p_max_pu_static, c.period(i))
            avail = max(ratio * p_nom, pos)
            em = pos * ef
            energy += pos * c.weight
            total_em += em * c.weight
            label = c.labels[i]
            output_s.append({"label": label, "timestamp": stamp, "output": o})
            emis_s.append({"label": label, "timestamp": stamp, "emissions": em})
            avail_s.append({"label": label, "timestamp": stamp, "available": avail})
            if time_varying:
                curt_s.append({"label": label, "timestamp": stamp, "curtailment": max(avail - pos, 0.0)})
        detail: dict[str, Any] = {
            "name": name, "carrier": carrier, "bus": string_value(row.get("bus")),
            "summary": [
                {"label": "Energy", "value": f"{fmt(energy)} MWh", "detail": f"{fmt(c.weight, 3)} h weighting applied"},
                {"label": "Operating cost", "value": f"{fmt(energy * mc)} {c.currency}",
                 "detail": f"{_fixed(mc, 1)} {c.currency}/MWh marginal cost"},
                {"label": "Emissions", "value": f"{fmt(total_em)} tCO2e",
                 "detail": f"{_fixed(ef, 2)} t/MWh thermal-basis factor (eta {_fixed(efficiency, 2)})"},
            ],
            "outputSeries": output_s, "emissionsSeries": emis_s,
            "availableSeries": avail_s, "curtailmentSeries": curt_s,
        }
        color = _explicit_color(row.get("color"))
        if color:
            detail["color"] = color
        out[name] = detail
    return out


def _build_buses(c: _Ctx, names: set[str] | None) -> dict[str, Any]:
    bus_static = _index_by_name(c.model.get("buses"))
    gen_static = _index_by_name(c.model.get("generators"))
    load_static = _index_by_name(c.model.get("loads"))
    carrier_static = _index_by_name(c.model.get("carriers"))
    p_series = c.series.get("generators-p")
    price_series = c.series.get("buses-marginal_price")
    vmag_series = c.series.get("buses-v_mag_pu")
    vang_series = c.series.get("buses-v_ang")
    load_idx = InputIndex(c.model.get("loads-p_set"), c.averaging)
    gen_by_bus: dict[str, list[str]] = {}
    load_by_bus: dict[str, list[str]] = {}
    for row in gen_static.values():
        b = string_value(row.get("bus"))
        if b:
            gen_by_bus.setdefault(b, []).append(string_value(row.get("name")))
    for row in load_static.values():
        b = string_value(row.get("bus"))
        if b:
            load_by_bus.setdefault(b, []).append(string_value(row.get("name")))
    out: dict[str, Any] = {}
    for name in bus_static:
        if not _wants(names, name):
            continue
        gens, loads = gen_by_bus.get(name, []), load_by_bus.get(name, [])
        net: list[dict[str, Any]] = []
        carrier_mix: dict[str, float] = {}
        load_avg = gen_avg = price_avg = 0.0
        price_count = 0
        has_v = has_a = False
        for i, stamp in enumerate(c.snapshots):
            load_t = sum(
                load_idx.value_at(stamp, ln, number_value((load_static.get(ln) or {}).get("p_set")), c.period(i))
                for ln in loads
            )
            gen_t = em_t = 0.0
            for gn in gens:
                pos = max(_series_value(p_series, i, gn), 0.0)
                gen_t += pos
                g = gen_static.get(gn)
                carrier = string_value((g or {}).get("carrier")) or "Other"
                em_t += pos * (generator_emission_factor(g, carrier_static) if g else 0.0)
                carrier_mix[carrier] = carrier_mix.get(carrier, 0.0) + pos * c.weight
            smp = _series_value(price_series, i, name) if price_series else 0.0
            if price_series:
                price_count += 1
            vmag = _series_value(vmag_series, i, name) if vmag_series else 0.0
            vang = _series_value(vang_series, i, name) if vang_series else 0.0
            if vmag_series and vmag != 0:
                has_v = True
            if vang_series and vang != 0:
                has_a = True
            load_avg += load_t
            gen_avg += gen_t
            price_avg += smp
            net.append({
                "label": c.labels[i], "timestamp": stamp, "load": load_t, "generation": gen_t,
                "smp": smp, "emissions": em_t, "v_mag_pu": vmag, "v_ang": vang,
            })
        n = len(c.snapshots) or 1
        load_avg /= n
        gen_avg /= n
        price_avg = price_avg / price_count if price_count else 0.0
        out[name] = {
            "name": name,
            "summary": [
                {"label": "Average load", "value": f"{fmt(load_avg)} MW", "detail": f"{len(loads)} load(s) attached"},
                {"label": "Average generation", "value": f"{fmt(gen_avg)} MW", "detail": f"{len(gens)} generator(s) attached"},
                {"label": "Average SMP", "value": f"{fmt(price_avg)} {c.currency}/MWh", "detail": "Bus marginal price"},
            ],
            "netSeries": net,
            "hasVoltageMagnitude": bool(vmag_series) and has_v,
            "hasVoltageAngle": bool(vang_series) and has_a,
            "carrierMix": [
                {"label": k, "value": v}
                for k, v in sorted(((k, v) for k, v in carrier_mix.items() if v > 0), key=lambda kv: -kv[1])
            ],
        }
    return out


def _build_storage_units(c: _Ctx, names: set[str] | None) -> dict[str, Any]:
    static_in = _index_by_name(c.model.get("storage_units"))
    p_series = c.series.get("storage_units-p")
    soc_series = c.series.get("storage_units-state_of_charge")
    out: dict[str, Any] = {}
    for name, row in static_in.items():
        if not _wants(names, name):
            continue
        p_nom_input = number_value(row.get("p_nom"))
        p_nom = _static_or_input(c.static, "storage_units", name, "p_nom_opt", p_nom_input)
        max_hours = number_value(row.get("max_hours"))
        dispatch, charge, discharge, state = [], [], [], []
        peak_state = 0.0
        for i, stamp in enumerate(c.snapshots):
            p = _series_value(p_series, i, name)
            soc = _series_value(soc_series, i, name)
            peak_state = max(peak_state, soc)
            label = c.labels[i]
            dispatch.append({"label": label, "timestamp": stamp, "dispatch": p})
            charge.append({"label": label, "timestamp": stamp, "charge": abs(min(p, 0.0))})
            discharge.append({"label": label, "timestamp": stamp, "discharge": max(p, 0.0)})
            state.append({"label": label, "timestamp": stamp, "state": soc})
        out[name] = {
            "name": name, "bus": string_value(row.get("bus")),
            "summary": [
                {"label": "Power rating", "value": f"{fmt(p_nom)} MW",
                 "detail": "Solved p_nom_opt" if p_nom != p_nom_input else "Storage unit dispatch limit"},
                {"label": "Energy capacity", "value": f"{fmt(p_nom * max_hours)} MWh",
                 "detail": f"{_fixed(max_hours, 1)} h max_hours"},
                {"label": "Peak state", "value": f"{fmt(peak_state)} MWh", "detail": "Maximum state of charge"},
            ],
            "dispatchSeries": dispatch, "chargeSeries": charge,
            "dischargeSeries": discharge, "stateSeries": state,
        }
    return out


def _build_stores(c: _Ctx, names: set[str] | None) -> dict[str, Any]:
    static_in = _index_by_name(c.model.get("stores"))
    e_series = c.series.get("stores-e")
    p_series = c.series.get("stores-p")
    out: dict[str, Any] = {}
    for name, row in static_in.items():
        if not _wants(names, name):
            continue
        e_nom_input = number_value(row.get("e_nom"))
        e_nom = _static_or_input(c.static, "stores", name, "e_nom_opt", e_nom_input)
        energy_s, power_s = [], []
        peak_e = peak_p = 0.0
        for i, stamp in enumerate(c.snapshots):
            e = _series_value(e_series, i, name)
            p = _series_value(p_series, i, name)
            peak_e = max(peak_e, e)
            peak_p = max(peak_p, abs(p))
            energy_s.append({"label": c.labels[i], "timestamp": stamp, "energy": e})
            power_s.append({"label": c.labels[i], "timestamp": stamp, "power": p})
        out[name] = {
            "name": name, "bus": string_value(row.get("bus")),
            "summary": [
                {"label": "Energy rating", "value": f"{fmt(e_nom)} MWh",
                 "detail": "Solved e_nom_opt" if e_nom != e_nom_input else "Store nominal energy"},
                {"label": "Peak energy", "value": f"{fmt(peak_e)} MWh", "detail": "Maximum stored energy"},
                {"label": "Peak power", "value": f"{fmt(peak_p)} MW", "detail": "Maximum absolute store power"},
            ],
            "energySeries": energy_s, "powerSeries": power_s,
        }
    return out


def _build_branch_group(
    c: _Ctx, names: set[str] | None, component: str, capacity_attr: str, unit: str, sheet: str,
) -> dict[str, Any]:
    p0_series = c.series.get(f"{sheet}-p0")
    p1_series = c.series.get(f"{sheet}-p1")
    out: dict[str, Any] = {}
    if not p0_series and not p1_series:
        return out
    for row in c.model.get(sheet) or []:
        name = string_value(row.get("name"))
        if not name or not _wants(names, name):
            continue
        input_cap = number_value(row.get(capacity_attr))
        capacity = max(_static_or_input(c.static, sheet, name, f"{capacity_attr}_opt", input_cap), 1.0)
        flow_s, loading_s, losses_s = [], [], []
        peak_flow = peak_loading = 0.0
        for i, stamp in enumerate(c.snapshots):
            p0 = _series_value(p0_series, i, name)
            p1 = _series_value(p1_series, i, name)
            flow = max(abs(p0), abs(p1))
            loading = flow / capacity * 100
            peak_flow = max(peak_flow, flow)
            peak_loading = max(peak_loading, loading)
            flow_s.append({"label": c.labels[i], "timestamp": stamp, "p0": p0, "p1": p1})
            loading_s.append({"label": c.labels[i], "timestamp": stamp, "loading": loading})
            losses_s.append({"label": c.labels[i], "timestamp": stamp, "losses": abs(p0 + p1)})
        out[name] = {
            "name": name, "component": component,
            "bus0": string_value(row.get("bus0")), "bus1": string_value(row.get("bus1")),
            "summary": [
                {"label": "Thermal rating" if component in ("line", "transformer") else "Transfer rating",
                 "value": f"{fmt(capacity)} {unit}", "detail": f"Static {component} rating"},
                {"label": "Peak flow", "value": f"{fmt(peak_flow)} MW", "detail": "Maximum terminal flow"},
                {"label": "Peak loading", "value": f"{fmt(peak_loading)}%", "detail": "Maximum utilization"},
            ],
            "flowSeries": flow_s, "loadingSeries": loading_s, "lossesSeries": losses_s,
        }
    return out


def _build_branches(c: _Ctx, names: set[str] | None) -> dict[str, Any]:
    return {
        **_build_branch_group(c, names, "line", "s_nom", "MVA", "lines"),
        **_build_branch_group(c, names, "link", "p_nom", "MW", "links"),
        **_build_branch_group(c, names, "transformer", "s_nom", "MVA", "transformers"),
    }


def _build_processes(c: _Ctx, names: set[str] | None) -> dict[str, Any]:
    static_in = _index_by_name(c.model.get("processes"))
    p0_series = c.series.get("processes-p0")
    p1_series = c.series.get("processes-p1")
    out: dict[str, Any] = {}
    for name, row in static_in.items():
        if not _wants(names, name):
            continue
        p_nom_input = number_value(row.get("p_nom"))
        p_nom = _static_or_input(c.static, "processes", name, "p_nom_opt", p_nom_input)
        mc = number_value(row.get("marginal_cost"))
        p0_o, p1_o, thr_o = [], [], []
        throughput_energy = ratio_num = ratio_den = 0.0
        for i, stamp in enumerate(c.snapshots):
            p0 = _series_value(p0_series, i, name)
            p1 = _series_value(p1_series, i, name)
            throughput = abs(p0)
            throughput_energy += throughput * c.weight
            if abs(p0) > 1e-9:
                ratio_num += abs(p1) / abs(p0) * throughput
                ratio_den += throughput
            p0_o.append({"label": c.labels[i], "timestamp": stamp, "p0": p0})
            p1_o.append({"label": c.labels[i], "timestamp": stamp, "p1": p1})
            thr_o.append({"label": c.labels[i], "timestamp": stamp, "throughput": throughput})
        eff = ratio_num / ratio_den if ratio_den > 0 else 0.0
        detail: dict[str, Any] = {
            "name": name, "carrier": string_value(row.get("carrier")) or "Other",
            "bus0": string_value(row.get("bus0")), "bus1": string_value(row.get("bus1")),
            "summary": [
                {"label": "Power rating", "value": f"{fmt(p_nom)} MW",
                 "detail": "Solved p_nom_opt" if p_nom != p_nom_input else "Input p_nom"},
                {"label": "Throughput", "value": f"{fmt(throughput_energy)} MWh",
                 "detail": f"{fmt(c.weight, 3)} h weighting applied"},
                {"label": "Realised efficiency", "value": _fixed(eff, 3) if eff > 0 else "—",
                 "detail": "Throughput-weighted |p1|/|p0|"},
                {"label": "Operating cost", "value": f"{fmt(throughput_energy * mc)} {c.currency}",
                 "detail": f"{_fixed(mc, 1)} {c.currency}/MWh marginal cost"},
            ],
            "p0Series": p0_o, "p1Series": p1_o, "throughputSeries": thr_o,
        }
        color = _explicit_color(row.get("color"))
        if color:
            detail["color"] = color
        out[name] = detail
    return out


def _build_shunts(c: _Ctx, names: set[str] | None) -> dict[str, Any]:
    static_in = _index_by_name(c.model.get("shunt_impedances"))
    p_series = c.series.get("shunt_impedances-p")
    q_series = c.series.get("shunt_impedances-q")
    out: dict[str, Any] = {}
    for name, row in static_in.items():
        if not _wants(names, name):
            continue
        g, b = number_value(row.get("g")), number_value(row.get("b"))
        p_o, q_o = [], []
        peak_p = peak_q = 0.0
        for i, stamp in enumerate(c.snapshots):
            p = _series_value(p_series, i, name)
            q = _series_value(q_series, i, name)
            peak_p = max(peak_p, abs(p))
            peak_q = max(peak_q, abs(q))
            p_o.append({"label": c.labels[i], "timestamp": stamp, "p": p})
            q_o.append({"label": c.labels[i], "timestamp": stamp, "q": q})
        out[name] = {
            "name": name, "bus": string_value(row.get("bus")),
            "summary": [
                {"label": "Conductance (g)", "value": f"{_fixed(g, 3)} S",
                 "detail": "No real-power coupling" if g == 0 else "Real shunt admittance"},
                {"label": "Susceptance (b)", "value": f"{_fixed(b, 3)} S",
                 "detail": "Capacitive (voltage support)" if b > 0 else "Inductive" if b < 0 else "No reactive coupling"},
                {"label": "Peak |P|", "value": f"{fmt(peak_p)} MW", "detail": "Maximum active power absorbed"},
                {"label": "Peak |Q|", "value": f"{fmt(peak_q)} MVar", "detail": "Maximum reactive power exchanged"},
            ],
            "pSeries": p_o, "qSeries": q_o,
        }
    return out


ASSET_KINDS: dict[str, Callable[[_Ctx, set[str] | None], dict[str, Any]]] = {
    "generators": _build_generators,
    "buses": _build_buses,
    "storageUnits": _build_storage_units,
    "stores": _build_stores,
    "branches": _build_branches,
    "processes": _build_processes,
    "shuntImpedances": _build_shunts,
}

_PREFERRED = ["generators-p", "buses-marginal_price", "storage_units-p", "stores-p", "processes-p0", "shunt_impedances-p"]


def derive_asset_details(
    model: Model,
    outputs: dict[str, Any] | None,
    currency: str = "$",
    snapshot_weight: float = 1.0,
    sampling: dict[str, Any] | None = None,
    *,
    kinds: list[str] | None = None,
    names: set[str] | None = None,
    period: int | None = None,
) -> dict[str, dict[str, Any]]:
    """Per-asset detail records, keyed ``kind -> name -> detail`` (as ``RunResults.assetDetails``).

    ``kinds`` / ``names`` narrow the work to what the caller needs; ``period``
    keeps one investment period of a pathway run.
    """
    empty: dict[str, dict[str, Any]] = {k: {} for k in ASSET_KINDS}
    if not outputs or not outputs.get("series"):
        return empty
    if period is not None:
        outputs = {**outputs, "series": filter_series_by_period(outputs["series"], period)}
    snapshots = [string_value(r.get("snapshot")) for r in _pick_snapshot_rows(outputs["series"], _PREFERRED)]
    ctx = _Ctx(
        model, outputs, currency, snapshot_weight, snapshots,
        snapshot_periods(outputs["series"], _PREFERRED),
        input_averaging_from_sampling(sampling, snapshots[0] if snapshots else None),
    )
    wanted = kinds if kinds else list(ASSET_KINDS)
    return {k: (ASSET_KINDS[k](ctx, names) if k in wanted else {}) for k in ASSET_KINDS}


# ── KPI strip ────────────────────────────────────────────────────────────────


def _storage_carriers(model: Model) -> set[str]:
    out: set[str] = set()
    for sheet in ("storage_units", "stores"):
        for row in model.get(sheet) or []:
            c = string_value(row.get("carrier"))
            if c:
                out.add(c)
    return out


def is_renewable_carrier(carrier: str, co2_emissions: float, storage_carriers: set[str]) -> bool:
    if co2_emissions > 0:
        return False
    if carrier in storage_carriers:
        return False
    return carrier.strip().lower() not in _NON_RENEWABLE_ZERO_EF


def _summary_value(result: dict[str, Any], *labels: str) -> str | None:
    for label in labels:
        for item in result.get("summary") or []:
            if item.get("label") == label:
                return string_value(item.get("value"))
    return None


def compute_kpis(
    result: dict[str, Any],
    carriers: list[Row],
    storage_carriers: set[str] | None = None,
    currency_symbol: str = "$",
    system_load_per_snapshot: Callable[[], list[float]] | None = None,
) -> dict[str, Any]:
    """The nine headline metrics of the KPI strip for one run.

    ``carriers`` are the model's ``carriers`` rows (for ``co2_emissions``);
    ``system_load_per_snapshot`` is a lazy fallback used only when the summary
    has no ``Peak demand`` (or ``snapshotCount * snapshotWeight`` is 0).
    Numeric fields are ``None`` where the TS shows an em dash.
    """
    carrier_mix = result.get("carrierMix") or []
    run_meta = result.get("runMeta") or {}
    total_dispatch = sum(number_value(m.get("value")) for m in carrier_mix)

    prices = [
        float(p["value"]) for p in result.get("systemPriceSeries") or []
        if isinstance(p.get("value"), (int, float)) and math.isfinite(p["value"])
    ]
    avg_price = sum(prices) / len(prices) if prices else 0.0
    min_price = min(prices) if prices else None
    max_price = max(prices) if prices else None

    emissions = _summary_value(result, "System emissions")

    total_cost = _summary_value(result, "Total cost", "System cost")
    cost_parts = [
        float(c["value"]) for c in result.get("costBreakdown") or []
        if isinstance(c.get("value"), (int, float)) and math.isfinite(c["value"])
    ]
    cost_total_value = sum(cost_parts) if cost_parts else None
    if total_cost is None and cost_total_value is not None:
        total_cost = f"{currency_symbol}{fmt(cost_total_value)}"

    peak_text = _summary_value(result, "Peak demand")
    peak_from_summary = math.nan
    if peak_text is not None:
        cleaned = re.sub(r"[^\d.\-]", "", peak_text)
        try:
            peak_from_summary = float(cleaned)
        except ValueError:
            peak_from_summary = math.nan

    system_load: list[float] | None = None

    def load() -> list[float]:
        nonlocal system_load
        if system_load is None:
            system_load = system_load_per_snapshot() if system_load_per_snapshot else []
        return system_load

    peak_load: float | None
    if math.isfinite(peak_from_summary):
        peak_load = peak_from_summary
    else:
        peak_load = max(load()) if load() else None

    weight = number_value(run_meta.get("snapshotWeight"))
    count = number_value(run_meta.get("snapshotCount"))
    modeled_hours = count * weight
    if modeled_hours > 0:
        avg_load: float | None = total_dispatch / modeled_hours
    elif load():
        avg_load = sum(load()) / len(load())
    else:
        avg_load = None
    load_factor = avg_load / peak_load if peak_load and avg_load else None

    by_name = {string_value(c.get("name")): c for c in carriers}
    storage = storage_carriers or set()
    renewable_mwh = sum(
        number_value(m.get("value")) for m in carrier_mix
        if is_renewable_carrier(
            string_value(m.get("label")),
            number_value((by_name.get(string_value(m.get("label"))) or {}).get("co2_emissions")),
            storage,
        )
    )
    renewable_share = renewable_mwh / total_dispatch * 100 if total_dispatch > 0 else 0.0

    return {
        "totalCost": total_cost,
        "dispatchMwh": total_dispatch,
        "avgPrice": avg_price,
        "minPrice": min_price,
        "maxPrice": max_price,
        "peakLoadMw": peak_load,
        "loadFactor": load_factor,
        "renewableSharePct": renewable_share,
        "emissions": emissions,
        "snapshotCount": run_meta.get("snapshotCount"),
        "snapshotWeightHours": run_meta.get("snapshotWeight"),
        "currencySymbol": currency_symbol,
    }


def system_load_series(asset_buses: dict[str, Any]) -> list[float]:
    """Positive system load per snapshot, summed over the buses' ``netSeries``."""
    details = list(asset_buses.values())
    n = len(details[0]["netSeries"]) if details else 0
    out = []
    for i in range(n):
        s = sum((d["netSeries"][i]["load"] if i < len(d["netSeries"]) else 0.0) for d in details)
        if s > 0:
            out.append(s)
    return out


# ── company comparison ───────────────────────────────────────────────────────

_COMPANY_METRICS = [
    ("npv", "NPV", True, "finance"), ("netMargin", "Net margin/yr", True, "statement"),
    ("irr", "IRR", True, "finance"), ("revenue", "Revenue/yr", True, None),
    ("capacityMW", "Capacity", True, None), ("emissionsTonnes", "Emissions", False, None),
]


def compare_companies(result: dict[str, Any], sort_by: str | None = None) -> dict[str, Any]:
    """Join the per-company breakdown (F1), finance (F2) and statement blocks by name."""
    breakdown = result.get("companies") or None
    finance = result.get("companyFinance") or None
    statement = result.get("companyStatement") or None
    rows: dict[str, dict[str, Any]] = {}

    def get(name: str) -> dict[str, Any]:
        return rows.setdefault(name, {"company": name})

    for c in (breakdown or {}).get("companies") or []:
        r = get(c["company"])
        r.update(capacityMW=c.get("capacityMW"), energyMWh=c.get("energyMWh"),
                 revenue=c.get("revenue"), emissionsTonnes=c.get("emissionsTonnes"))
    for c in (finance or {}).get("companies") or []:
        r = get(c["company"])
        r.update(npv=c.get("npv"), irr=c.get("irr"), paybackYears=c.get("paybackYears"))
    for c in (statement or {}).get("companies") or []:
        get(c["company"])["netMargin"] = c.get("netMargin")

    metrics = [
        {"key": k, "label": lbl, "higherBetter": hb}
        for k, lbl, hb, needs in _COMPANY_METRICS
        if needs is None or (needs == "finance" and finance) or (needs == "statement" and statement)
    ]
    key = sort_by if any(m["key"] == sort_by for m in metrics) else (metrics[0]["key"] if metrics else "revenue")
    higher = next((m["higherBetter"] for m in metrics if m["key"] == key), True)
    data = list(rows.values())
    have = sorted((r for r in data if r.get(key) is not None), key=lambda r: r[key], reverse=higher)
    missing = [r for r in data if r.get(key) is None]
    currency = (
        (breakdown or {}).get("currency") or (finance or {}).get("currency") or (statement or {}).get("currency") or ""
    )
    return {"currency": currency, "sortedBy": key, "metrics": metrics, "companies": have + missing}


# ── cross-run comparison ─────────────────────────────────────────────────────


def _installed_mw(solved: dict[str, Any] | None, input_row: Row) -> tuple[float, bool]:
    opt = (solved or {}).get("p_nom_opt")
    if opt is not None and opt != "":
        try:
            if math.isfinite(float(opt)):
                return number_value(opt), True
        except (TypeError, ValueError):
            pass
    return number_value(input_row.get("p_nom")), False


def installed_capacity(model_static: dict[str, Any] | None, outputs_static: dict[str, Any] | None) -> dict[str, Any]:
    """Installed capacity by carrier from the run's input topology + solved ``p_nom_opt``."""
    root = model_static or {}
    solved = (outputs_static or {})
    solved_gen = solved.get("generators") or {}
    solved_stor = solved.get("storage_units") or {}
    by_carrier: dict[str, float] = {}
    gen_cap = 0.0
    gen_solved = True
    for r in root.get("generators") or []:
        name = string_value(r.get("name"))
        if not name or name.startswith("load_shedding_"):
            continue
        mw, ok = _installed_mw(solved_gen.get(name), r)
        gen_solved = gen_solved and ok
        gen_cap += mw
        carrier = string_value(r.get("carrier")) or "Other"
        by_carrier[carrier] = by_carrier.get(carrier, 0.0) + mw
    stor_cap = 0.0
    stor_solved = True
    for r in root.get("storage_units") or []:
        name = string_value(r.get("name"))
        if not name:
            continue
        mw, ok = _installed_mw(solved_stor.get(name), r)
        stor_solved = stor_solved and ok
        stor_cap += mw
    mix = [
        {"label": k, "value": v}
        for k, v in sorted(((k, v) for k, v in by_carrier.items() if v > 0), key=lambda kv: -kv[1])
    ]
    return {"mix": mix, "genCapMw": gen_cap, "storCapMw": stor_cap, "genSolved": gen_solved, "storSolved": stor_solved}


def split_capacity_summary(base: list[dict[str, Any]], info: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Replace the single Installed capacity / Reserve position KPIs by the generator + storage split."""
    if not info:
        return base

    def mw(n: float) -> str:
        return f"{fmt(n)} MW"

    peak = 0.0
    for s in base:
        if re.fullmatch(r"peak demand", string_value(s.get("label")).strip(), re.I):
            peak = number_value(re.sub(r"[^\d.\-]", "", string_value(s.get("value")))) or 0.0
            break
    out: list[dict[str, Any]] = []
    for item in base:
        label = string_value(item.get("label")).strip()
        if re.fullmatch(r"installed capacity", label, re.I):
            out.append({"label": "Generator capacity", "value": mw(info["genCapMw"]),
                        "detail": "installed (solved p_nom_opt)" if info["genSolved"]
                        else "installed (input p_nom — solved capacity unavailable)"})
            out.append({"label": "Storage capacity", "value": mw(info["storCapMw"]),
                        "detail": "installed (solved p_nom_opt)" if info["storSolved"]
                        else "installed (input p_nom — solved capacity unavailable)"})
        elif re.fullmatch(r"reserve position", label, re.I):
            out.append({"label": "Generator reserve", "value": mw(info["genCapMw"] - peak),
                        "detail": "generator capacity vs peak demand"})
            out.append({"label": "Storage reserve", "value": mw(info["storCapMw"] - peak),
                        "detail": "storage capacity vs peak demand"})
        else:
            out.append(item)
    return out


COMPARISON_TOPICS = ("kpi", "generation-mix", "installed-capacity", "cost", "emissions", "capacity", "generation-time")
_MAX_TS_POINTS = 600


def run_comparison_entry(name: str, analytics: dict[str, Any], topics: list[str]) -> dict[str, Any]:
    """One scenario column of the comparison matrix, from a run's analytics bundle."""
    result = analytics.get("result") or {}
    info = installed_capacity(analytics.get("modelStatic"), (result.get("outputs") or {}).get("static"))
    entry: dict[str, Any] = {"name": name, "label": analytics.get("label") or name}
    if "kpi" in topics:
        entry["summary"] = split_capacity_summary(result.get("summary") or [], info)
    if "generation-mix" in topics:
        entry["carrierMix"] = [{"label": m.get("label"), "value": m.get("value")} for m in result.get("carrierMix") or []]
    if "installed-capacity" in topics:
        entry["capacityMix"] = info["mix"]
        entry["generatorCapacityMw"] = info["genCapMw"]
        entry["storageCapacityMw"] = info["storCapMw"]
    if "cost" in topics:
        entry["costBreakdown"] = [{"label": c.get("label"), "value": c.get("value")} for c in result.get("costBreakdown") or []]
    if "emissions" in topics:
        entry["emissionsByCarrier"] = [
            {"label": c.get("carrier"), "value": c.get("emissions_tco2")}
            for c in (result.get("emissionsBreakdown") or {}).get("byCarrier") or []
        ]
    if "capacity" in topics:
        entry["expansion"] = [
            {"name": a.get("name"), "carrier": a.get("carrier"), "installedMw": a.get("p_nom_mw"),
             "optimisedMw": a.get("p_nom_opt_mw")}
            for a in result.get("expansionResults") or []
        ]
    if "generation-time" in topics:
        series = result.get("dispatchSeries") or []
        stride = max(1, math.ceil(len(series) / _MAX_TS_POINTS))
        entry["dispatchSeries"] = series[::stride]
        entry["dispatchStride"] = stride
    return entry
