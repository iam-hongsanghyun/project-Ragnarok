/**
 * TransitionRiskCard (R2) — how a rising carbon price erodes each company.
 *
 * Live over the per-company P&L statement: set a forward carbon-price
 * trajectory (base price, escalation, horizon) and a stranding threshold, and
 * the card recomputes each company's net-margin path, the first year it turns
 * stranded, and the cumulative margin-at-risk. Dispatch and revenue are held at
 * the solved outcome — this isolates the carbon-cost burden.
 */
import React from 'react';
import { CompanyStatementResult } from 'lib/types';
import {
  CompanyRisk,
  DEFAULT_TRANSITION_PARAMS,
  TransitionParams,
  computeTransitionRisk,
} from 'lib/results/transitionRisk';

interface Props {
  data: CompanyStatementResult;
}

const PALETTE = ['#4e79a7', '#e15759', '#59a14f', '#edc948', '#b07aa1', '#f28e2b', '#76b7b2', '#ff9da7'];
const money = (v: number, cur: string) => `${v < 0 ? '−' : ''}${cur}${Math.abs(Math.round(v)).toLocaleString()}`;

export function TransitionRiskCard({ data }: Props) {
  const cur = data.currency || '';
  const [params, setParams] = React.useState<TransitionParams>({
    ...DEFAULT_TRANSITION_PARAMS,
    basePrice: Math.max(DEFAULT_TRANSITION_PARAMS.basePrice, Math.round(data.carbonPrice) || DEFAULT_TRANSITION_PARAMS.basePrice),
  });
  const set = (patch: Partial<TransitionParams>) => setParams((p) => ({ ...p, ...patch }));

  const result = React.useMemo(() => computeTransitionRisk(data, params), [data, params]);
  const strandedCount = result.companies.filter((c) => c.strandedYear !== null).length;
  const earliest = result.companies.reduce<number | null>((min, c) =>
    c.strandedYear !== null && (min === null || c.strandedYear < min) ? c.strandedYear : min, null);
  const totalAtRisk = result.companies.reduce((s, c) => s + c.marginErosion, 0);

  const shown = result.companies.slice(0, PALETTE.length);

  return (
    <div className="econ-card">
      {/* Trajectory controls */}
      <div className="tr-controls">
        <label>Base price {cur}
          <input type="number" min={0} step={5} value={params.basePrice}
            onChange={(e) => set({ basePrice: Math.max(0, Number(e.target.value) || 0) })} />
        </label>
        <label>Escalation %/yr
          <input type="number" min={0} step={1} value={params.escalationPct}
            onChange={(e) => set({ escalationPct: Math.max(0, Number(e.target.value) || 0) })} />
        </label>
        <label>Horizon (yr)
          <input type="number" min={1} max={50} step={1} value={params.years}
            onChange={(e) => set({ years: Math.max(1, Math.min(50, Math.round(Number(e.target.value) || 1))) })} />
        </label>
        <label>Base year
          <input type="number" min={2000} max={2100} step={1} value={params.baseYear}
            onChange={(e) => set({ baseYear: Math.round(Number(e.target.value) || 2030) })} />
        </label>
        <label>Stranded ≤ {cur}
          <input type="number" step={1000} value={params.strandedThreshold}
            onChange={(e) => set({ strandedThreshold: Number(e.target.value) || 0 })} />
        </label>
      </div>

      <div className="econ-kpi-row">
        <div className="econ-kpi">
          <div className="econ-kpi-label">Companies at risk</div>
          <div className={`econ-kpi-value${strandedCount > 0 ? ' econ-negative' : ''}`}>{strandedCount} / {result.companies.length}</div>
          <div className="econ-kpi-unit">net margin ≤ {money(params.strandedThreshold, cur)} within horizon</div>
        </div>
        <div className="econ-kpi">
          <div className="econ-kpi-label">Earliest stranding</div>
          <div className="econ-kpi-value">{earliest ?? '—'}</div>
          <div className="econ-kpi-unit">first year any owner turns loss-making</div>
        </div>
        <div className="econ-kpi">
          <div className="econ-kpi-label">Total margin at risk</div>
          <div className="econ-kpi-value econ-negative">{money(totalAtRisk, cur)}</div>
          <div className="econ-kpi-unit">cumulative erosion vs {result.baseYear} over {params.years} yr</div>
        </div>
        <div className="econ-kpi">
          <div className="econ-kpi-label">Carbon price {result.baseYear}→{result.baseYear + params.years}</div>
          <div className="econ-kpi-value">{cur}{Math.round(result.trajectory[0].price)}→{Math.round(result.trajectory[result.trajectory.length - 1].price)}</div>
          <div className="econ-kpi-unit">/tCO₂ at {params.escalationPct}%/yr</div>
        </div>
      </div>

      <MarginChart companies={shown} baseline={params.strandedThreshold} currency={cur} />

      <div className="econ-table-wrap">
        <table className="econ-table">
          <thead>
            <tr>
              <th>Company</th>
              <th className="num">Emissions (t)</th>
              <th className="num">Net margin {result.baseYear}</th>
              <th className="num">Stranded year</th>
              <th className="num">Margin at risk</th>
            </tr>
          </thead>
          <tbody>
            {result.companies.map((c, i) => (
              <tr key={c.company}>
                <td>
                  <span className="tr-swatch" style={{ background: i < PALETTE.length ? PALETTE[i] : 'var(--muted)' }} />
                  {c.company}
                </td>
                <td className="num">{Math.round(c.emissionsTonnes).toLocaleString()}</td>
                <td className={`num${c.baseNetMargin >= 0 ? '' : ' econ-negative'}`}>{money(c.baseNetMargin, cur)}</td>
                <td className={`num${c.strandedYear !== null ? ' econ-negative' : ''}`}>{c.strandedYear ?? 'never'}</td>
                <td className="num econ-negative">{c.marginErosion > 0 ? money(c.marginErosion, cur) : '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="econ-footnote">
        Dispatch and revenue held at the solved outcome; only the carbon price rises. Net margin =
        (revenue − fuel/VOM − capex − interest) − emissions × carbon price. A company is stranded
        the first year its net margin falls to/below the threshold.
      </p>
    </div>
  );
}

function MarginChart({ companies, baseline, currency }: { companies: CompanyRisk[]; baseline: number; currency: string }) {
  const W = 480, H = 220, pad = { l: 56, r: 12, t: 12, b: 26 };
  const plotW = W - pad.l - pad.r, plotH = H - pad.t - pad.b;
  if (companies.length === 0 || companies[0].byYear.length === 0) return null;

  const years = companies[0].byYear.map((p) => p.year);
  const xMin = years[0], xMax = years[years.length - 1];
  const allMargins = companies.flatMap((c) => c.byYear.map((p) => p.netMargin)).concat([baseline, 0]);
  const yMin = Math.min(...allMargins), yMax = Math.max(...allMargins);
  const sx = (yr: number) => pad.l + ((yr - xMin) / (xMax - xMin || 1)) * plotW;
  const sy = (v: number) => pad.t + plotH - ((v - yMin) / (yMax - yMin || 1)) * plotH;

  return (
    <div style={{ overflowX: 'auto' }}>
      <svg viewBox={`0 0 ${W} ${H}`} className="tr-chart" role="img" aria-label="Net margin trajectory by company">
        {/* baseline (stranding threshold) */}
        <line x1={pad.l} y1={sy(baseline)} x2={W - pad.r} y2={sy(baseline)} className="tr-threshold" />
        <text x={pad.l} y={sy(baseline) - 3} className="tr-axis-label">stranded ≤ {currency}{Math.round(baseline)}</text>
        {/* axes */}
        <line x1={pad.l} y1={pad.t} x2={pad.l} y2={pad.t + plotH} className="tr-axis" />
        <line x1={pad.l} y1={pad.t + plotH} x2={W - pad.r} y2={pad.t + plotH} className="tr-axis" />
        <text x={pad.l} y={pad.t + plotH + 18} className="tr-axis-label" textAnchor="middle">{xMin}</text>
        <text x={W - pad.r} y={pad.t + plotH + 18} className="tr-axis-label" textAnchor="end">{xMax}</text>
        <text x={4} y={pad.t + 8} className="tr-axis-label">{currency}/yr net</text>
        {/* one line per company */}
        {companies.map((c, i) => (
          <g key={c.company}>
            <polyline
              className="tr-line"
              stroke={PALETTE[i % PALETTE.length]}
              points={c.byYear.map((p) => `${sx(p.year).toFixed(1)},${sy(p.netMargin).toFixed(1)}`).join(' ')}
            />
            {c.strandedYear !== null && (
              <circle cx={sx(c.strandedYear)} cy={sy(baseline)} r={3.5} fill={PALETTE[i % PALETTE.length]} />
            )}
          </g>
        ))}
      </svg>
    </div>
  );
}
