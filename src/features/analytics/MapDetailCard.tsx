import React from 'react';
import { AnalyticsFocus, RunResults } from '../../shared/types';
import { carrierColor } from '../../shared/utils/helpers';

// ── Sparkline ─────────────────────────────────────────────────────────────────

/** Downsample to at most maxPts evenly spaced values */
function downsample(values: number[], maxPts = 260): number[] {
  if (values.length <= maxPts) return values;
  const step = (values.length - 1) / (maxPts - 1);
  return Array.from({ length: maxPts }, (_, i) => values[Math.round(i * step)]);
}

function MiniSparkline({ values, color = '#2563eb' }: { values: number[]; color?: string }) {
  const pts = downsample(values);
  if (pts.length < 2) return null;

  const W = 228, H = 52;
  const min = Math.min(...pts);
  const max = Math.max(...pts);
  const range = max - min || 1;

  const px = (i: number) => (i / (pts.length - 1)) * W;
  const py = (v: number) => H - 4 - ((v - min) / range) * (H - 8);

  const linePts = pts.map((v, i) => `${px(i)},${py(v)}`).join(' ');
  const areaPath =
    `M${px(0)},${H} ` +
    pts.map((v, i) => `L${px(i)},${py(v)}`).join(' ') +
    ` L${px(pts.length - 1)},${H} Z`;

  return (
    <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} style={{ display: 'block' }}>
      <path d={areaPath} fill={color} fillOpacity={0.1} />
      <polyline
        points={linePts}
        fill="none"
        stroke={color}
        strokeWidth="1.5"
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  );
}

// ── KPI row ───────────────────────────────────────────────────────────────────

function KpiRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="mdc-kpi-row">
      <span className="mdc-kpi-label">{label}</span>
      <span className="mdc-kpi-value">{value}</span>
    </div>
  );
}

// ── Main card ─────────────────────────────────────────────────────────────────

interface Props {
  focus: AnalyticsFocus;
  results: RunResults;
  onClose: () => void;
  currencySymbol?: string;
}

export function MapDetailCard({ focus, results, onClose, currencySymbol = '$' }: Props) {
  if (focus.type === 'system') return null;

  const key = focus.key;
  let subtitle = '';
  let dotColor: string | null = null;
  let sparkValues: number[] = [];
  let sparkColor = '#2563eb';
  let sparkLabel = '';
  let kpis: Array<{ label: string; value: string }> = [];

  if (focus.type === 'generator') {
    const detail = results.assetDetails.generators[key];
    if (!detail) return null;
    subtitle = detail.carrier;
    dotColor = detail.color || carrierColor(detail.carrier);
    kpis = detail.summary.slice(0, 4).map((s) => ({ label: s.label, value: s.value }));
    sparkValues = detail.outputSeries.map((p) => p.output);
    sparkColor = dotColor;
    sparkLabel = 'Output (MW)';
  } else if (focus.type === 'bus') {
    const detail = results.assetDetails.buses[key];
    if (!detail) return null;
    subtitle = 'Bus';
    kpis = detail.summary.slice(0, 4).map((s) => ({ label: s.label, value: s.value }));
    sparkValues = detail.netSeries.map((p) => p.smp);
    sparkColor = '#7c3aed';
    sparkLabel = `Nodal SMP (${currencySymbol}/MWh)`;
  } else if (focus.type === 'storageUnit') {
    const detail = results.assetDetails.storageUnits[key];
    if (!detail) return null;
    subtitle = 'Storage Unit';
    kpis = detail.summary.slice(0, 4).map((s) => ({ label: s.label, value: s.value }));
    sparkValues = detail.stateSeries.map((p) => p.state);
    sparkColor = '#14b8a6';
    sparkLabel = 'State of charge (MWh)';
  } else if (focus.type === 'store') {
    const detail = results.assetDetails.stores[key];
    if (!detail) return null;
    subtitle = 'Store';
    kpis = detail.summary.slice(0, 4).map((s) => ({ label: s.label, value: s.value }));
    sparkValues = detail.energySeries.map((p) => p.energy);
    sparkColor = '#7c3aed';
    sparkLabel = 'Energy (MWh)';
  } else if (focus.type === 'branch') {
    const detail = results.assetDetails.branches[key];
    if (!detail) return null;
    subtitle = detail.component;
    kpis = detail.summary.slice(0, 4).map((s) => ({ label: s.label, value: s.value }));
    sparkValues = detail.flowSeries.map((p) => p.p0);
    sparkColor = '#f97316';
    sparkLabel = 'Flow p0 (MW)';
  } else if (focus.type === 'process') {
    const detail = results.assetDetails.processes[key];
    if (!detail) return null;
    subtitle = detail.carrier ? `Process · ${detail.carrier}` : 'Process';
    dotColor = detail.color || carrierColor(detail.carrier);
    kpis = detail.summary.slice(0, 4).map((s) => ({ label: s.label, value: s.value }));
    sparkValues = detail.throughputSeries.map((p) => p.throughput);
    sparkColor = dotColor;
    sparkLabel = 'Throughput |p0| (MW)';
  }

  const hasSparkline = sparkValues.length >= 2 && sparkValues.some((v) => Math.abs(v) > 0.001);
  const hasData = kpis.length > 0 || hasSparkline;

  return (
    <div className="map-detail-card">
      {/* Header */}
      <div className="mdc-header">
        <div className="mdc-title-row">
          {dotColor && <span className="mdc-dot" style={{ background: dotColor }} />}
          <span className="mdc-title" title={key}>{key}</span>
          {subtitle && <span className="mdc-badge">{subtitle}</span>}
        </div>
        <button className="mdc-close" onClick={onClose} title="Close (reset focus)">Close</button>
      </div>

      {/* KPIs */}
      {kpis.length > 0 && (
        <div className="mdc-kpis">
          {kpis.map((k) => <KpiRow key={k.label} label={k.label} value={k.value} />)}
        </div>
      )}

      {/* Sparkline */}
      {hasSparkline && (
        <div className="mdc-sparkline-wrap">
          <div className="mdc-sparkline-label">{sparkLabel}</div>
          <MiniSparkline values={sparkValues} color={sparkColor} />
        </div>
      )}

      {!hasData && (
        <p className="mdc-empty">Run the model to see asset details.</p>
      )}
    </div>
  );
}
