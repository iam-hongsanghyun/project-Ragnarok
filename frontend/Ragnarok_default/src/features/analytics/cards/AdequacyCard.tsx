/**
 * AdequacyCard (A1+A2) — reliability under renewable variability.
 *
 * Leads with the metrics regulators use — LOLE (h/yr) against the "1 day in 10
 * years" ≈ 2.4 h/yr yardstick, and EENS (MWh/yr) — then plots the available-
 * generation band (p10–p90 across the synthetic ensemble) against load, so the
 * hours where the band dips under demand (the loss-of-load risk) are visible.
 */
import React from 'react';
import { AdequacyResult } from 'lib/types';

interface Props {
  data: AdequacyResult;
}

const num0 = (v: number) => Math.round(v).toLocaleString();
const YARDSTICK = 2.4; // LOLE h/yr ≈ "1 day in 10 years"

export function AdequacyCard({ data }: Props) {
  const band = data.band;
  const meetsYardstick = data.lole <= YARDSTICK;

  const W = 520, H = 220, pad = { l: 52, r: 12, t: 12, b: 26 };
  const plotW = W - pad.l - pad.r, plotH = H - pad.t - pad.b;
  const n = band.length;
  const maxY = Math.max(data.peakLoadMW, ...band.map((b) => b.p90)) * 1.08 || 1;
  const sx = (i: number) => pad.l + (n > 1 ? (i / (n - 1)) : 0) * plotW;
  const sy = (v: number) => pad.t + plotH - (v / maxY) * plotH;

  // p10–p90 available band as a filled polygon, p50 and load as lines.
  const bandPath =
    band.map((b, i) => `${sx(i).toFixed(1)},${sy(b.p90).toFixed(1)}`).join(' ') + ' ' +
    band.slice().reverse().map((b, ri) => { const i = n - 1 - ri; return `${sx(i).toFixed(1)},${sy(b.p10).toFixed(1)}`; }).join(' ');
  const line = (key: 'p50' | 'load') => band.map((b, i) => `${sx(i).toFixed(1)},${sy(b[key]).toFixed(1)}`).join(' ');

  return (
    <div className="econ-card">
      <div className="econ-kpi-row">
        <div className="econ-kpi">
          <div className="econ-kpi-label">LOLE</div>
          <div className={`econ-kpi-value${meetsYardstick ? ' econ-recovered' : ' econ-negative'}`}>{data.lole.toFixed(1)} h/yr</div>
          <div className="econ-kpi-unit">{meetsYardstick ? 'within' : 'above'} the ≈{YARDSTICK} h/yr standard</div>
        </div>
        <div className="econ-kpi">
          <div className="econ-kpi-label">EENS</div>
          <div className="econ-kpi-value">{num0(data.eens)} MWh/yr</div>
          <div className="econ-kpi-unit">expected energy not served</div>
        </div>
        <div className="econ-kpi">
          <div className="econ-kpi-label">Capacity vs peak</div>
          <div className="econ-kpi-value">{num0(data.firmCapacityMW + data.renewableCapacityMW)} MW</div>
          <div className="econ-kpi-unit">{num0(data.firmCapacityMW)} firm + {num0(data.renewableCapacityMW)} renewable · peak {num0(data.peakLoadMW)}</div>
        </div>
        <div className="econ-kpi">
          <div className="econ-kpi-label">Ensemble</div>
          <div className="econ-kpi-value">{data.members}</div>
          <div className="econ-kpi-unit">members · ±{Math.round(data.variability * 100)}% variability</div>
        </div>
      </div>

      {n > 1 && (
        <div style={{ overflowX: 'auto' }}>
          <svg viewBox={`0 0 ${W} ${H}`} className="adequacy-chart" role="img" aria-label="Available generation band vs load">
            <line x1={pad.l} y1={pad.t} x2={pad.l} y2={pad.t + plotH} className="ab-axis" />
            <line x1={pad.l} y1={pad.t + plotH} x2={W - pad.r} y2={pad.t + plotH} className="ab-axis" />
            <text x={4} y={pad.t + 8} className="ab-label">MW</text>
            <polygon points={bandPath} className="adq-band" />
            <polyline points={line('p50')} className="adq-median" />
            <polyline points={line('load')} className="adq-load" />
          </svg>
          <p className="econ-footnote" style={{ marginTop: 2 }}>
            Shaded = available generation p10–p90 across the ensemble; green = median; red = load.
            Hours where the band dips below load are the loss-of-load risk.
          </p>
        </div>
      )}

      <p className="econ-footnote">
        {data.members} synthetic weather members (±{Math.round(data.variability * 100)}% variability,
        shape-preserving). LOLE weights the per-snapshot loss-of-load probability by hours and scales
        to a year; EENS is the expected unserved energy. Firm capacity is treated as always available.
      </p>
    </div>
  );
}
