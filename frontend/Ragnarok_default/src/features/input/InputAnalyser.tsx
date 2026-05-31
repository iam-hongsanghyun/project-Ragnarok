import React, { useEffect, useMemo, useState } from 'react';
import { GridRow } from 'lib/types';
import { stringValue } from 'lib/utils/helpers';
import { SearchableSelect } from '../../shared/components/SearchableSelect';

// ── Helpers ───────────────────────────────────────────────────────────────────

function numVal(v: unknown): number {
  if (typeof v === 'number') return v;
  const n = parseFloat(String(v ?? ''));
  return Number.isFinite(n) ? n : 0;
}

function isNumericCol(rows: GridRow[], col: string): boolean {
  const sample = rows.slice(0, 20).map((r) => r[col]);
  const numeric = sample.filter((v) => v !== null && v !== '' && Number.isFinite(Number(v)));
  return numeric.length > Math.max(sample.length * 0.5, 1);
}

function isStringCol(rows: GridRow[], col: string): boolean {
  return !isNumericCol(rows, col);
}

// Extract hour-of-day (0–23) from a label like "2020-01-01 04:00" or "04:00"
function extractHour(label: string): number | null {
  const m = label.match(/(\d{1,2}):(\d{2})/);
  if (m) return parseInt(m[1], 10);
  return null;
}

const PALETTE = [
  '#0f766e','#f97316','#16a34a','#dc2626','#7c3aed',
  '#0891b2','#d97706','#be185d','#065f46','#1e40af',
  '#84cc16','#ec4899','#6366f1','#14b8a6','#f59e0b',
];

// ── Shared SVG primitives ─────────────────────────────────────────────────────

function NoData({ msg = 'No data to display.' }: { msg?: string }) {
  return <p style={{ padding: '16px', fontSize: '0.82rem', color: 'var(--muted)', textAlign: 'center' }}>{msg}</p>;
}

// ── 1. Horizontal Bar (static, one value per row) ─────────────────────────────

function HBar({ labels, values, colors, unit }: {
  labels: string[]; values: number[]; colors?: string[]; unit: string;
}) {
  if (!labels.length) return <NoData />;
  const max = Math.max(...values, 0);
  const barH = 22; const labelW = 130; const barW = 340; const valW = 72;
  const padX = 8; const padY = 6;
  const W = labelW + barW + valW + padX * 2;
  const H = padY * 2 + labels.length * (barH + 4);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', maxWidth: W, display: 'block' }}>
      {labels.map((label, i) => {
        const y = padY + i * (barH + 4);
        const fill = colors?.[i] ?? '#0f766e';
        const w = max > 0 ? (values[i] / max) * barW : 0;
        const fmt = values[i] === 0 ? '—' : values[i] < 1 ? values[i].toFixed(3) : values[i].toLocaleString(undefined, { maximumFractionDigits: 1 });
        return (
          <g key={i}>
            <text x={padX + labelW - 4} y={y + barH / 2 + 4} textAnchor="end" fontSize={11} fill="var(--muted)">
              {label.length > 18 ? label.slice(0, 17) + '…' : label}
            </text>
            <rect x={padX + labelW} y={y} width={barW} height={barH} rx={0} fill="var(--bg-hover)" />
            {w > 0 && <rect x={padX + labelW} y={y} width={w} height={barH} rx={0} fill={fill} opacity={0.85} />}
            <text x={padX + labelW + barW + 5} y={y + barH / 2 + 4} fontSize={11} fill="var(--text)">
              {fmt}{unit ? ` ${unit}` : ''}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

// ── 2. Donut (grouped by a string col) ───────────────────────────────────────

function Donut({ data }: { data: { label: string; value: number; color: string }[] }) {
  const [tip, setTip] = useState<{ label: string; value: number } | null>(null);
  if (!data.length) return <NoData />;
  const cx = 110; const cy = 110; const outerR = 90; const innerR = 52;
  const total = data.reduce((s, d) => s + d.value, 0) || 1;
  let angle = -Math.PI / 2;
  const arcs = data.map((d) => {
    const span = (d.value / total) * Math.PI * 2;
    const start = angle;
    angle += span;
    return { ...d, start, end: angle, span };
  });
  const arc = (s: number, e: number) => {
    const gap = 0.01;
    const a = s + gap; const b = e - gap;
    const lx1 = cx + outerR * Math.cos(a); const ly1 = cy + outerR * Math.sin(a);
    const lx2 = cx + outerR * Math.cos(b); const ly2 = cy + outerR * Math.sin(b);
    const sx1 = cx + innerR * Math.cos(b); const sy1 = cy + innerR * Math.sin(b);
    const sx2 = cx + innerR * Math.cos(a); const sy2 = cy + innerR * Math.sin(a);
    const lg = b - a > Math.PI ? 1 : 0;
    return `M${lx1} ${ly1} A${outerR} ${outerR} 0 ${lg} 1 ${lx2} ${ly2} L${sx1} ${sy1} A${innerR} ${innerR} 0 ${lg} 0 ${sx2} ${sy2} Z`;
  };
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 24, flexWrap: 'wrap' }}>
      <svg viewBox="0 0 220 220" style={{ width: 180, flexShrink: 0 }}>
        {arcs.map((a) => (
          <path key={a.label} d={arc(a.start, a.end)} fill={a.color}
            opacity={tip && tip.label !== a.label ? 0.45 : 1}
            onMouseEnter={() => setTip({ label: a.label, value: a.value })}
            onMouseLeave={() => setTip(null)}
            style={{ cursor: 'pointer', transition: 'opacity 0.15s' }}
          />
        ))}
        {tip && (
          <>
            <text x={cx} y={cy - 6} textAnchor="middle" fontSize={11} fill="var(--muted)">{tip.label}</text>
            <text x={cx} y={cy + 12} textAnchor="middle" fontSize={13} fontWeight="700" fill="var(--text)">
              {((tip.value / total) * 100).toFixed(1)}%
            </text>
          </>
        )}
      </svg>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {arcs.map((a) => (
          <div key={a.label} style={{ display: 'flex', alignItems: 'center', gap: 7, fontSize: 12 }}>
            <span style={{ width: 10, height: 10, borderRadius: '50%', background: a.color, flexShrink: 0 }} />
            <span style={{ color: 'var(--muted)' }}>{a.label}</span>
            <span style={{ fontWeight: 600, color: 'var(--text)', marginLeft: 4 }}>
              {a.value.toLocaleString(undefined, { maximumFractionDigits: 1 })}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── 3. Scatter ────────────────────────────────────────────────────────────────

function Scatter({ xVals, yVals, labels, xCol, yCol }: {
  xVals: number[]; yVals: number[]; labels: string[]; xCol: string; yCol: string;
}) {
  const [hov, setHov] = useState<number | null>(null);
  if (!xVals.length) return <NoData />;
  const W = 440; const H = 260; const pL = 48; const pR = 16; const pT = 12; const pB = 36;
  const cW = W - pL - pR; const cH = H - pT - pB;
  const xMin = Math.min(...xVals); const xMax = Math.max(...xVals) || 1;
  const yMin = Math.min(...yVals); const yMax = Math.max(...yVals) || 1;
  const xPos = (v: number) => pL + ((v - xMin) / (xMax - xMin || 1)) * cW;
  const yPos = (v: number) => pT + cH - ((v - yMin) / (yMax - yMin || 1)) * cH;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', maxWidth: W, display: 'block' }}>
      {[0, 0.5, 1].map((t) => {
        const v = yMin + t * (yMax - yMin);
        const y = yPos(v);
        return (
          <g key={t}>
            <line x1={pL} x2={W - pR} y1={y} y2={y} stroke="#e2e8f0" strokeWidth={1} />
            <text x={pL - 4} y={y + 4} textAnchor="end" fontSize={9} fill="#94a3b8">
              {v < 1 ? v.toFixed(1) : Math.round(v).toLocaleString()}
            </text>
          </g>
        );
      })}
      {[0, 0.5, 1].map((t) => {
        const v = xMin + t * (xMax - xMin);
        const x = xPos(v);
        return (
          <text key={t} x={x} y={H - pB + 14} textAnchor="middle" fontSize={9} fill="#94a3b8">
            {v < 1 ? v.toFixed(1) : Math.round(v).toLocaleString()}
          </text>
        );
      })}
      <text x={pL + cW / 2} y={H - 2} textAnchor="middle" fontSize={10} fill="var(--muted)">{xCol}</text>
      <text x={10} y={pT + cH / 2} textAnchor="middle" fontSize={10} fill="var(--muted)"
        transform={`rotate(-90, 10, ${pT + cH / 2})`}>{yCol}</text>
      {xVals.map((x, i) => (
        <g key={i} onMouseEnter={() => setHov(i)} onMouseLeave={() => setHov(null)}>
          <circle cx={xPos(x)} cy={yPos(yVals[i])} r={hov === i ? 7 : 5}
            fill="#0f766e" opacity={hov !== null && hov !== i ? 0.3 : 0.8}
            style={{ cursor: 'pointer', transition: 'r 0.1s, opacity 0.1s' }} />
          {hov === i && (
            <text x={xPos(x) + 8} y={yPos(yVals[i]) - 6} fontSize={10} fill="var(--text)">
              {labels[i]}
            </text>
          )}
        </g>
      ))}
    </svg>
  );
}

// ── 4. Multi-line / Stacked-area ──────────────────────────────────────────────

function LineArea({ xLabels, series, stacked }: {
  xLabels: string[];
  series: { key: string; values: number[]; color: string }[];
  stacked: boolean;
}) {
  if (!xLabels.length || !series.length) return <NoData />;
  const W = 560; const H = 220; const pL = 50; const pR = 12; const pT = 12; const pB = 32;
  const cW = W - pL - pR; const cH = H - pT - pB;
  const n = xLabels.length;
  const tickStep = Math.max(1, Math.ceil(n / 8));

  // For stacked, compute cumulative baseline
  const computeY = (seriesIdx: number, rowIdx: number): number => {
    if (!stacked) return series[seriesIdx].values[rowIdx];
    return series.slice(0, seriesIdx + 1).reduce((s, sr) => s + sr.values[rowIdx], 0);
  };
  const baseY = (seriesIdx: number, rowIdx: number): number => {
    if (!stacked) return 0;
    return series.slice(0, seriesIdx).reduce((s, sr) => s + sr.values[rowIdx], 0);
  };

  const allTopVals = series.flatMap((_, si) => xLabels.map((__, ri) => computeY(si, ri)));
  const maxV = Math.max(...allTopVals, 0);
  const minV = stacked ? 0 : Math.min(...series.flatMap((s) => s.values), 0);
  const range = maxV - minV || 1;

  const xPos = (i: number) => pL + (i / Math.max(n - 1, 1)) * cW;
  const yPos = (v: number) => pT + cH - ((v - minV) / range) * cH;

  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', maxWidth: W, display: 'block' }}>
      {[0, 0.25, 0.5, 0.75, 1].map((t) => {
        const v = minV + t * range;
        const y = yPos(v);
        return (
          <g key={t}>
            <line x1={pL} x2={W - pR} y1={y} y2={y} stroke="#e2e8f0" strokeWidth={1} />
            <text x={pL - 4} y={y + 4} textAnchor="end" fontSize={9} fill="#94a3b8">
              {Math.abs(v) < 1 ? v.toFixed(2) : Math.round(v).toLocaleString()}
            </text>
          </g>
        );
      })}
      {xLabels.map((label, i) => {
        if (i % tickStep !== 0 && i !== n - 1) return null;
        return (
          <text key={i} x={xPos(i)} y={H - pB + 14} textAnchor="middle" fontSize={9} fill="#94a3b8">
            {label.length > 10 ? label.slice(0, 9) + '…' : label}
          </text>
        );
      })}
      {/* Render stacked areas bottom-to-top, then lines on top */}
      {stacked && [...series].reverse().map((s, ri) => {
        const si = series.length - 1 - ri;
        const topPts = xLabels.map((_, i) => `${xPos(i)},${yPos(computeY(si, i))}`).join(' ');
        const basePts = [...xLabels].reverse().map((_, revi) => {
          const i = n - 1 - revi;
          return `${xPos(i)},${yPos(baseY(si, i))}`;
        }).join(' ');
        return (
          <polygon key={s.key} points={`${topPts} ${basePts}`}
            fill={s.color} opacity={0.45} />
        );
      })}
      {series.map((s, si) => {
        const pts = xLabels.map((_, i) => `${xPos(i)},${yPos(computeY(si, i))}`).join(' ');
        return (
          <polyline key={s.key} points={pts} fill="none"
            stroke={s.color} strokeWidth={stacked ? 1 : 1.8}
            strokeLinejoin="round" strokeLinecap="round" />
        );
      })}
    </svg>
  );
}

// ── 5. Duration curve ─────────────────────────────────────────────────────────

function DurationCurve({ values, label, color }: { values: number[]; label: string; color: string }) {
  const sorted = [...values].sort((a, b) => b - a);
  if (!sorted.length) return <NoData />;
  const W = 480; const H = 200; const pL = 50; const pR = 12; const pT = 12; const pB = 32;
  const cW = W - pL - pR; const cH = H - pT - pB;
  const n = sorted.length;
  const maxV = sorted[0]; const minV = Math.min(...sorted, 0);
  const range = maxV - minV || 1;
  const xPos = (i: number) => pL + (i / (n - 1)) * cW;
  const yPos = (v: number) => pT + cH - ((v - minV) / range) * cH;
  const pts = sorted.map((v, i) => `${xPos(i)},${yPos(v)}`).join(' ');
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', maxWidth: W, display: 'block' }}>
      {[0, 0.25, 0.5, 0.75, 1].map((t) => {
        const v = minV + t * range;
        const y = yPos(v);
        return (
          <g key={t}>
            <line x1={pL} x2={W - pR} y1={y} y2={y} stroke="#e2e8f0" strokeWidth={1} />
            <text x={pL - 4} y={y + 4} textAnchor="end" fontSize={9} fill="#94a3b8">
              {Math.round(v).toLocaleString()}
            </text>
          </g>
        );
      })}
      <text x={pL + cW / 2} y={H - 2} textAnchor="middle" fontSize={10} fill="var(--muted)">Rank (sorted descending)</text>
      <polygon points={`${xPos(0)},${yPos(minV)} ${pts} ${xPos(n-1)},${yPos(minV)}`}
        fill={color} opacity={0.18} />
      <polyline points={pts} fill="none" stroke={color} strokeWidth={2} strokeLinejoin="round" />
      <text x={pL + 4} y={pT + 14} fontSize={10} fill="var(--muted)">{label}</text>
    </svg>
  );
}

// ── 6. Daily profile (average by hour-of-day) ─────────────────────────────────

function DailyProfile({ xLabels, series }: {
  xLabels: string[];
  series: { key: string; values: number[]; color: string }[];
}) {
  // Group by extracted hour-of-day, take mean
  const hourlyMeans: Record<string, number[]> = {};
  for (let h = 0; h < 24; h++) hourlyMeans[String(h)] = [];
  xLabels.forEach((label, i) => {
    const h = extractHour(label);
    if (h !== null) {
      series.forEach((s) => {
        if (!hourlyMeans[String(h)]) hourlyMeans[String(h)] = [];
        hourlyMeans[String(h)].push(s.values[i]);
      });
    }
  });
  const hours = Array.from({ length: 24 }, (_, h) => h);
  const means = hours.map((h) => {
    const vals = hourlyMeans[String(h)] ?? [];
    return vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : 0;
  });
  const maxV = Math.max(...means, 0);
  const W = 480; const H = 180; const pL = 46; const pR = 8; const pT = 10; const pB = 28;
  const cW = W - pL - pR; const cH = H - pT - pB;
  const barW = (cW / 24) - 2;
  const yPos = (v: number) => pT + cH - (v / (maxV || 1)) * cH;
  const color = series[0]?.color ?? '#0f766e';
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', maxWidth: W, display: 'block' }}>
      {[0, 0.5, 1].map((t) => {
        const v = t * maxV;
        const y = yPos(v);
        return (
          <g key={t}>
            <line x1={pL} x2={W - pR} y1={y} y2={y} stroke="#e2e8f0" strokeWidth={1} />
            <text x={pL - 4} y={y + 4} textAnchor="end" fontSize={9} fill="#94a3b8">
              {Math.round(v).toLocaleString()}
            </text>
          </g>
        );
      })}
      {hours.map((h) => {
        const x = pL + (h / 24) * cW;
        const y = yPos(means[h]);
        return (
          <g key={h}>
            <rect x={x + 1} y={y} width={barW} height={pT + cH - y} rx={0} fill={color} opacity={0.75} />
            {h % 6 === 0 && (
              <text x={x + barW / 2} y={H - pB + 14} textAnchor="middle" fontSize={9} fill="#94a3b8">{h}:00</text>
            )}
          </g>
        );
      })}
      <text x={pL + cW / 2} y={H - 2} textAnchor="middle" fontSize={10} fill="var(--muted)">Hour of day (average)</text>
    </svg>
  );
}

// ── Legend ────────────────────────────────────────────────────────────────────

function Legend({ items }: { items: { key: string; color: string }[] }) {
  if (items.length <= 1) return null;
  return (
    <div className="ia-legend">
      {items.map(({ key, color }) => (
        <span key={key} className="ia-legend-item">
          <span className="ia-legend-dot" style={{ background: color }} />
          {key}
        </span>
      ))}
    </div>
  );
}

// ── Control row ───────────────────────────────────────────────────────────────

function Ctl({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="ia-control">
      <span className="ia-control-label">{label}</span>
      {children}
    </label>
  );
}

// ── Main component ─────────────────────────────────────────────────────────────

interface InputAnalyserProps {
  rows: GridRow[];
  cols: string[];
  isTs: boolean;
  frozenCol: string | null;
  currencySymbol?: string;
  /** When the analyser is opened via "Analyse column", preselect this column as
   *  the value (static) / series (temporal). `null` analyses the whole table. */
  focusCol?: string | null;
}

type StaticChart = 'bar' | 'grouped-bar' | 'donut' | 'scatter';
type TsChart     = 'line' | 'stacked-area' | 'duration' | 'daily-profile';
type AggMethod   = 'sum' | 'mean' | 'max' | 'min' | 'count';

export function InputAnalyser({ rows, cols, isTs, frozenCol, currencySymbol = '$', focusCol = null }: InputAnalyserProps) {
  const numericCols = useMemo(
    () => cols.filter((c) => c !== frozenCol && isNumericCol(rows, c)),
    [rows, cols, frozenCol],
  );
  const stringCols = useMemo(
    () => cols.filter((c) => c !== frozenCol && isStringCol(rows, c)),
    [rows, cols, frozenCol],
  );
  const tsCols = useMemo(
    () => cols.filter((c) => c !== frozenCol),
    [cols, frozenCol],
  );

  // ── Static controls ────────────────────────────────────────────────────────
  const [valueCol,  setValueCol]  = useState('');
  const [groupCol,  setGroupCol]  = useState('none');
  const [scatterY,  setScatterY]  = useState('');
  const [agg,       setAgg]       = useState<AggMethod>('sum');
  const [staticChart, setStaticChart] = useState<StaticChart>('bar');

  // ── TS controls ────────────────────────────────────────────────────────────
  const [tsSeries,  setTsSeries]  = useState('__all__');
  const [tsChart,   setTsChart]   = useState<TsChart>('line');

  // "Analyse column" preselects the right control for the requested column.
  useEffect(() => {
    if (!focusCol) return;
    if (isTs) {
      if (tsCols.includes(focusCol)) setTsSeries(focusCol);
    } else if (numericCols.includes(focusCol)) {
      setValueCol(focusCol);
    }
  }, [focusCol, isTs, tsCols, numericCols]);

  // ── Static derived values (hooks must be unconditional) ───────────────────
  const nameCol     = frozenCol ?? cols[0] ?? '';
  const activeValue = numericCols.includes(valueCol) ? valueCol : (numericCols[0] ?? '');
  const activeScatY = numericCols.includes(scatterY) ? scatterY : (numericCols[1] ?? numericCols[0] ?? '');
  const activeGroup = stringCols.includes(groupCol) ? groupCol : 'none';

  const aggregate = (vals: number[], method: AggMethod): number => {
    if (!vals.length) return 0;
    if (method === 'sum')   return vals.reduce((a, b) => a + b, 0);
    if (method === 'mean')  return vals.reduce((a, b) => a + b, 0) / vals.length;
    if (method === 'max')   return Math.max(...vals);
    if (method === 'min')   return Math.min(...vals);
    if (method === 'count') return vals.length;
    return 0;
  };

  const groupedData = useMemo(() => {
    if (!activeValue) return [];
    if (activeGroup === 'none') {
      return rows.map((r, i) => ({
        label: nameCol ? stringValue(r[nameCol]) || `Row ${i + 1}` : `Row ${i + 1}`,
        value: numVal(r[activeValue]),
        group: '',
      }));
    }
    const map = new Map<string, number[]>();
    rows.forEach((r) => {
      const g = stringValue(r[activeGroup]) || '(blank)';
      if (!map.has(g)) map.set(g, []);
      map.get(g)!.push(numVal(r[activeValue]));
    });
    return Array.from(map.entries())
      .map(([label, vals]) => ({ label, value: aggregate(vals, agg), group: label }))
      .sort((a, b) => b.value - a.value);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rows, activeValue, activeGroup, agg, nameCol]);

  const colorByGroup = useMemo(() => {
    const groups = Array.from(new Set(groupedData.map((d) => d.group)));
    return Object.fromEntries(groups.map((g, i) => [g, PALETTE[i % PALETTE.length]]));
  }, [groupedData]);

  if (!rows.length) return <div className="ia-empty">No data — add rows to see charts.</div>;

  // ──────────────────────────────────────────────────────────────────────────
  // TEMPORAL rendering
  // ──────────────────────────────────────────────────────────────────────────

  if (isTs) {
    const xLabels = rows.map((r) => frozenCol ? stringValue(r[frozenCol]) : String(Object.values(r)[0] ?? ''));
    const displayCols = (tsSeries === '__all__' ? tsCols : [tsSeries]).slice(0, 15);
    const series = displayCols.map((col, i) => ({
      key: col,
      values: rows.map((r) => numVal(r[col])),
      color: PALETTE[i % PALETTE.length],
    }));

    return (
      <div className="ia-panel">
        <div className="ia-controls">
          <Ctl label="Series">
            <SearchableSelect
              className="ia-select"
              value={tsSeries}
              options={[{ value: '__all__', label: 'All' }, ...tsCols]}
              onChange={(v) => setTsSeries(v)}
            />
          </Ctl>
          <Ctl label="Chart">
            <SearchableSelect
              className="ia-select"
              value={tsChart}
              options={[
                { value: 'line', label: 'Line' },
                { value: 'stacked-area', label: 'Stacked area' },
                { value: 'duration', label: 'Duration curve' },
                { value: 'daily-profile', label: 'Daily profile' },
              ]}
              onChange={(v) => setTsChart(v as TsChart)}
            />
          </Ctl>
          <span className="ia-meta">{rows.length} snapshots · {tsCols.length} series</span>
        </div>

        <div className="ia-chart-wrap">
          {tsChart === 'line' && <LineArea xLabels={xLabels} series={series} stacked={false} />}
          {tsChart === 'stacked-area' && <LineArea xLabels={xLabels} series={series} stacked />}
          {tsChart === 'duration' && (
            series.length === 1
              ? <DurationCurve values={series[0].values} label={series[0].key} color={series[0].color} />
              : <div className="ia-tip">Select a single series for the duration curve.</div>
          )}
          {tsChart === 'daily-profile' && <DailyProfile xLabels={xLabels} series={series} />}
        </div>
        <Legend items={series} />
      </div>
    );
  }

  // ──────────────────────────────────────────────────────────────────────────
  // STATIC rendering
  // ──────────────────────────────────────────────────────────────────────────

  if (!numericCols.length) return <div className="ia-empty">No numeric columns to analyse.</div>;

  const labels = groupedData.map((d) => d.label);
  const values = groupedData.map((d) => d.value);
  const colors = groupedData.map((d) => colorByGroup[d.group] ?? PALETTE[0]);

  // Detect unit from column name
  const unit =
    activeValue.includes('cost') ? `${currencySymbol}/MWh`
    : activeValue === 'p_nom' || activeValue.includes('_mw') ? 'MW'
    : activeValue.includes('efficiency') || activeValue.includes('_pu') ? ''
    : '';

  const donutData = groupedData.map((d, i) => ({
    label: d.label, value: d.value, color: PALETTE[i % PALETTE.length],
  }));

  const scatterXVals = rows.map((r) => numVal(r[activeValue]));
  const scatterYVals = rows.map((r) => numVal(r[activeScatY]));
  const scatterLabels = rows.map((r, i) => nameCol ? stringValue(r[nameCol]) || `Row ${i+1}` : `Row ${i+1}`);

  const showGroupCtl = staticChart !== 'scatter';
  const showAggCtl   = showGroupCtl && activeGroup !== 'none';
  const showScatterY = staticChart === 'scatter';

  return (
    <div className="ia-panel">
      <div className="ia-controls">
        <Ctl label="Value">
          <SearchableSelect className="ia-select" value={activeValue} options={numericCols} onChange={(v) => setValueCol(v)} />
        </Ctl>
        {showScatterY && (
          <Ctl label="Y axis">
            <SearchableSelect className="ia-select" value={activeScatY} options={numericCols} onChange={(v) => setScatterY(v)} />
          </Ctl>
        )}
        {showGroupCtl && (
          <Ctl label="Group by">
            <SearchableSelect
              className="ia-select"
              value={activeGroup}
              options={[{ value: 'none', label: 'None (per row)' }, ...stringCols]}
              onChange={(v) => setGroupCol(v)}
            />
          </Ctl>
        )}
        {showAggCtl && (
          <Ctl label="Aggregate">
            <SearchableSelect
              className="ia-select"
              value={agg}
              options={[
                { value: 'sum', label: 'Sum' },
                { value: 'mean', label: 'Mean' },
                { value: 'max', label: 'Max' },
                { value: 'min', label: 'Min' },
                { value: 'count', label: 'Count' },
              ]}
              onChange={(v) => setAgg(v as AggMethod)}
            />
          </Ctl>
        )}
        <Ctl label="Chart">
          <SearchableSelect
            className="ia-select"
            value={staticChart}
            options={[
              { value: 'bar', label: 'Bar' },
              { value: 'grouped-bar', label: 'Grouped bar' },
              { value: 'donut', label: 'Donut' },
              { value: 'scatter', label: 'Scatter' },
            ]}
            onChange={(v) => setStaticChart(v as StaticChart)}
          />
        </Ctl>
        <span className="ia-meta">{rows.length} rows</span>
      </div>

      <div className="ia-chart-wrap">
        {staticChart === 'bar' && (
          <HBar labels={labels} values={values} colors={colors} unit={unit} />
        )}
        {staticChart === 'grouped-bar' && (
          <HBar labels={labels} values={values} colors={colors} unit={unit} />
        )}
        {staticChart === 'donut' && (
          <Donut data={donutData} />
        )}
        {staticChart === 'scatter' && (
          <Scatter xVals={scatterXVals} yVals={scatterYVals} labels={scatterLabels} xCol={activeValue} yCol={activeScatY} />
        )}
      </div>
    </div>
  );
}
