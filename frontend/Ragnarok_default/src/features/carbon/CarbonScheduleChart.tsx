/**
 * Interactive carbon-price schedule editor — a hand-rolled SVG line chart
 * (no chart library, matching the rest of the app).
 *
 * Interactions:
 *   • drag a point vertically  → change its price (year is fixed per point)
 *   • click empty plot area     → add a point at that (year, price)
 *   • select a point            → inline year/price editor + delete
 *
 * Sizing: the chart's coordinate system is measured PIXELS (viewBox width =
 * the element's real width via ResizeObserver, height fixed), NOT a fixed
 * viewBox scaled to width — otherwise text and height blow up on a wide panel.
 * So it grows only wider; height and font sizes stay constant.
 *
 * Stability rules (a naive version "jumps everywhere"):
 *   • x-axis range rounded to 5-year bounds, driven only by committed years,
 *     so adding/editing a point inside the range never shifts the others.
 *   • Selection tracked by YEAR (unique), not array index, so a re-sort after
 *     an edit doesn't reselect the wrong point.
 *   • Year/price inputs commit on blur / Enter, never per keystroke.
 *   • The y-axis max is frozen during a drag, so dragging stays 1:1.
 */
import React, { useEffect, useMemo, useRef, useState } from 'react';
import type { CarbonPriceScheduleEntry } from 'lib/types';
import { CARBON_CHART_CONFIG } from 'lib/constants';

export interface CarbonChartOverlay {
  name: string;
  color: string;
  schedule: CarbonPriceScheduleEntry[];
}

interface Props {
  schedule: CarbonPriceScheduleEntry[];
  onChange: (next: CarbonPriceScheduleEntry[]) => void;
  currencySymbol: string;
  /** Scalar price (applies when the schedule is empty) — used to scale the y-axis. */
  scalarPrice: number;
  /** Read-only comparison curves drawn faintly behind the editable one. */
  overlays?: CarbonChartOverlay[];
  /** Compare view: hide the editable curve + disable editing so the saved
   *  (ticked) schedules read clearly without the in-progress curve on top. */
  compareMode?: boolean;
}

const H = 240; // fixed pixel height
const L = 52;
const R = 18;
const T = 16;
const B = 34;
const PLOT_H = H - T - B;
const PLOT_BOTTOM = T + PLOT_H;

const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));
const fmt = (n: number) => (Number.isInteger(n) ? String(n) : n.toFixed(1));

function niceCeil(value: number): number {
  if (value <= 0) return 10;
  const exp = Math.pow(10, Math.floor(Math.log10(value)));
  const f = value / exp;
  const nf = f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10;
  return nf * exp;
}

export function CarbonScheduleChart({ schedule, onChange, currencySymbol, scalarPrice, overlays, compareMode = false }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const svgRef = useRef<SVGSVGElement | null>(null);
  const dragMaxRef = useRef<number | null>(null);
  const [width, setWidth] = useState(760); // measured pixel width (1 viewBox unit = 1 px)
  const [dragYear, setDragYear] = useState<number | null>(null);
  const [selectedYear, setSelectedYear] = useState<number | null>(null);
  const [editYear, setEditYear] = useState('');
  const [editPrice, setEditPrice] = useState('');
  const [hover, setHover] = useState<{ name: string; year: number | null; price: number | null; vx: number; vy: number } | null>(null);

  // Track the real rendered width so the viewBox maps 1:1 to pixels.
  useEffect(() => {
    const el = containerRef.current;
    if (!el || typeof ResizeObserver === 'undefined') return undefined;
    const ro = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect.width;
      if (w && w > 0) setWidth(Math.max(320, Math.round(w)));
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const plotW = width - L - R;
  const points = useMemo(() => [...schedule].sort((a, b) => a.year - b.year), [schedule]);
  const emit = (next: CarbonPriceScheduleEntry[]) => onChange([...next].sort((a, b) => a.year - b.year));

  const { xMin, xMax, yMax } = useMemo(() => {
    const all = [...points, ...(overlays ?? []).flatMap((o) => o.schedule)];
    const years = all.map((p) => p.year);
    // Default window is the configured range (2020–2050); it only extends
    // (rounded to 5-year bounds) to fit points that fall outside it.
    let lo = CARBON_CHART_CONFIG.defaultStartYear;
    let hi = CARBON_CHART_CONFIG.defaultEndYear;
    if (years.length) {
      lo = Math.min(lo, Math.floor((Math.min(...years) - 2) / 5) * 5);
      hi = Math.max(hi, Math.ceil((Math.max(...years) + 2) / 5) * 5);
    }
    const rawMax = all.length ? Math.max(...all.map((p) => p.price)) : 0;
    return { xMin: lo, xMax: hi, yMax: niceCeil(Math.max(rawMax, scalarPrice, 10) * 1.2) };
  }, [points, overlays, scalarPrice]);

  const xOf = (year: number) => L + ((year - xMin) / (xMax - xMin)) * plotW;
  const yOf = (price: number) => T + (1 - price / yMax) * PLOT_H;
  const yearFromX = (px: number) => Math.round(xMin + ((px - L) / plotW) * (xMax - xMin));
  const priceFromY = (py: number) => clamp(yMax * (1 - (py - T) / PLOT_H), 0, yMax);

  const pointerVB = (e: React.PointerEvent | React.MouseEvent) => {
    const rect = svgRef.current!.getBoundingClientRect();
    return {
      x: ((e.clientX - rect.left) / rect.width) * width,
      y: ((e.clientY - rect.top) / rect.height) * H,
    };
  };

  const selected = selectedYear !== null ? points.find((p) => p.year === selectedYear) ?? null : null;

  useEffect(() => {
    const p = selectedYear !== null ? schedule.find((s) => s.year === selectedYear) : undefined;
    if (p) {
      setEditYear(String(p.year));
      setEditPrice(String(p.price));
    }
  }, [selectedYear, dragYear]); // eslint-disable-line react-hooks/exhaustive-deps

  const updateByYear = (oldYear: number, patch: Partial<CarbonPriceScheduleEntry>) =>
    emit(points.map((p) => (p.year === oldYear ? { ...p, ...patch } : p)));

  const startDrag = (e: React.PointerEvent, year: number) => {
    e.stopPropagation();
    (e.currentTarget as Element).setPointerCapture?.(e.pointerId);
    dragMaxRef.current = yMax;
    setDragYear(year);
    setSelectedYear(year);
  };
  const onPointerMove = (e: React.PointerEvent) => {
    if (dragYear === null) return;
    const max = dragMaxRef.current ?? yMax;
    const { y } = pointerVB(e);
    const price = clamp(Math.round(max * (1 - (y - T) / PLOT_H)), 0, max);
    updateByYear(dragYear, { price });
  };
  const endDrag = () => {
    dragMaxRef.current = null;
    setDragYear(null);
  };

  const addAt = (e: React.MouseEvent) => {
    const { x, y } = pointerVB(e);
    if (x < L || x > width - R || y < T || y > PLOT_BOTTOM) return;
    const year = clamp(yearFromX(x), xMin, xMax);
    if (points.some((p) => p.year === year)) return; // one point per year
    emit([...points, { year, price: Math.round(priceFromY(y)) }]);
    setSelectedYear(year);
  };

  const commitYear = () => {
    if (selectedYear === null) return;
    const n = parseInt(editYear, 10);
    if (!Number.isFinite(n) || points.some((p) => p.year === n && p.year !== selectedYear)) {
      setEditYear(String(selectedYear));
      return;
    }
    if (n !== selectedYear) {
      updateByYear(selectedYear, { year: n });
      setSelectedYear(n);
    }
  };
  const commitPrice = () => {
    if (selectedYear === null) return;
    const v = parseFloat(editPrice);
    const price = Number.isFinite(v) ? Math.max(0, v) : 0;
    updateByYear(selectedYear, { price });
    setEditPrice(String(price));
  };
  const removeSelected = () => {
    if (selectedYear === null) return;
    emit(points.filter((p) => p.year !== selectedYear));
    setSelectedYear(null);
  };

  const yTicks = [0, 0.25, 0.5, 0.75, 1].map((f) => f * yMax);
  const linePath = points.map((p, i) => `${i === 0 ? 'M' : 'L'}${xOf(p.year)} ${yOf(p.price)}`).join(' ');
  let lastLabelX = -Infinity;
  const showYearLabel = points.map((p) => {
    const x = xOf(p.year);
    if (x - lastLabelX >= 40) {
      lastLabelX = x;
      return true;
    }
    return false;
  });

  return (
    <div className="carbon-chart" ref={containerRef}>
      <svg
        ref={svgRef}
        viewBox={`0 0 ${width} ${H}`}
        style={{ width: '100%', height: H, display: 'block' }}
        className={`carbon-chart-svg${compareMode ? ' is-compare' : ''}`}
        onPointerMove={compareMode ? undefined : onPointerMove}
        onPointerUp={compareMode ? undefined : endDrag}
        onPointerLeave={compareMode ? undefined : endDrag}
      >
        {yTicks.map((v) => (
          <g key={`y${v}`}>
            <line x1={L} y1={yOf(v)} x2={width - R} y2={yOf(v)} className="carbon-chart-grid" />
            <text x={L - 8} y={yOf(v) + 3} textAnchor="end" className="carbon-chart-axis-label">{fmt(v)}</text>
          </g>
        ))}
        <line x1={L} y1={T} x2={L} y2={PLOT_BOTTOM} className="carbon-chart-axis" />
        <line x1={L} y1={PLOT_BOTTOM} x2={width - R} y2={PLOT_BOTTOM} className="carbon-chart-axis" />
        <rect x={L} y={T} width={plotW} height={PLOT_H} className="carbon-chart-surface" onClick={compareMode ? undefined : addAt} />
        {(overlays ?? []).map((o) => {
          const pts = [...o.schedule].sort((a, b) => a.year - b.year);
          if (pts.length === 0) return null;
          const d = pts.map((p, i) => `${i === 0 ? 'M' : 'L'}${xOf(p.year)} ${yOf(p.price)}`).join(' ');
          return (
            <g
              key={`ov-${o.name}`}
              className="carbon-chart-overlay"
              style={{ color: o.color }}
              onPointerMove={(e) => {
                const v = pointerVB(e);
                let near: CarbonPriceScheduleEntry | null = null;
                let bestDx = Infinity;
                for (const pt of pts) {
                  const dx = Math.abs(xOf(pt.year) - v.x);
                  if (dx < bestDx) { bestDx = dx; near = pt; }
                }
                setHover({ name: o.name, year: near?.year ?? null, price: near?.price ?? null, vx: v.x, vy: v.y });
              }}
              onPointerLeave={() => setHover((h) => (h && h.name === o.name ? null : h))}
            >
              {pts.length > 1 && <path d={d} className="carbon-chart-overlay-line" />}
              {pts.map((p) => (
                <circle key={`ov-${o.name}-${p.year}`} cx={xOf(p.year)} cy={yOf(p.price)} r={3} className="carbon-chart-overlay-dot" />
              ))}
            </g>
          );
        })}
        {points.length > 1 && <path d={linePath} className="carbon-chart-line" />}
        {points.map((p, i) => (
          <g key={`p${p.year}`}>
            {showYearLabel[i] && (
              <text x={xOf(p.year)} y={PLOT_BOTTOM + 16} textAnchor="middle" className="carbon-chart-axis-label">{p.year}</text>
            )}
            <text x={xOf(p.year)} y={yOf(p.price) - 10} textAnchor="middle" className="carbon-chart-value">
              {currencySymbol}{fmt(p.price)}
            </text>
            <circle
              cx={xOf(p.year)}
              cy={yOf(p.price)}
              r={selectedYear === p.year ? 6 : 4.5}
              className={`carbon-chart-point${selectedYear === p.year ? ' is-selected' : ''}`}
              onPointerDown={compareMode ? undefined : (e) => startDrag(e, p.year)}
            />
          </g>
        ))}
        {points.length === 0 && (
          <text x={width / 2} y={T + PLOT_H / 2} textAnchor="middle" className="carbon-chart-empty">
            Click anywhere to add the first point (the scalar price applies until you do).
          </text>
        )}
      </svg>

      {hover && (
        <div
          className="carbon-chart-tooltip"
          style={{ left: `${(hover.vx / width) * 100}%`, top: `${(hover.vy / H) * 100}%` }}
        >
          {hover.name}
          {hover.year !== null && hover.price !== null && (
            <span className="carbon-chart-tooltip-val"> · {hover.year}: {currencySymbol}{fmt(hover.price)}</span>
          )}
        </div>
      )}

      {selected && !compareMode && (
        <div
          className="carbon-chart-editor"
          style={{ left: `${(xOf(selected.year) / width) * 100}%`, top: `${(yOf(selected.price) / H) * 100}%` }}
          onKeyDown={(e) => { if (e.key === 'Escape') setSelectedYear(null); }}
        >
          <label>
            Year
            <input
              type="number"
              step={1}
              value={editYear}
              onChange={(e) => setEditYear(e.target.value)}
              onBlur={commitYear}
              onKeyDown={(e) => { if (e.key === 'Enter') commitYear(); }}
            />
          </label>
          <label>
            {currencySymbol}/tCO₂
            <input
              type="number"
              step={1}
              min={0}
              value={editPrice}
              onChange={(e) => setEditPrice(e.target.value)}
              onBlur={commitPrice}
              onKeyDown={(e) => { if (e.key === 'Enter') commitPrice(); }}
            />
          </label>
          <button type="button" className="carbon-chart-done" title="Done (close)" onClick={() => setSelectedYear(null)}>Done</button>
          <button type="button" className="carbon-chart-del" title="Delete this point" onClick={removeSelected}>Delete</button>
        </div>
      )}
    </div>
  );
}
