/**
 * TransitionRiskCard (R2) - how a rising carbon price erodes each company.
 *
 * Set a forward carbon-price trajectory (base price, escalation, horizon, demand and fuel
 * growth) and a stranding threshold; the server (`GET /api/runs/{name}/analysis/transition-risk`)
 * reprices each company's P&L statement year by year and returns the net-margin path, the first
 * stranded year and the cumulative margin-at-risk. Dispatch and revenue are held at the solved
 * outcome - this isolates the carbon-cost burden. The card holds the inputs and plots the answer.
 */
import React from 'react';
import { CompanyStatementResult } from 'lib/types';
import { CompanyRisk, fetchRunAnalysis, TransitionRiskQuery } from 'lib/api/resultsDerived';
import { useAsync } from '../../../shared/hooks/useAsync';

interface Props {
  /** The P&L statement: currency and the run's own carbon price (default for the base price). */
  data: CompanyStatementResult;
  runName?: string | null;
  /** Pathway investment period; null = the whole horizon. */
  period?: number | null;
}

const DEFAULT_PARAMS: TransitionRiskQuery = {
  baseYear: 2030,
  years: 20,
  basePrice: 50,
  escalationPct: 5,
  strandedThreshold: 0,
  demandGrowthPct: 0,
  fuelGrowthPct: 0,
};

/** Wait this long after the last edit before asking the server (inputs fire per keystroke). */
const EDIT_DEBOUNCE_MS = 300;

const PALETTE = ['#4e79a7', '#e15759', '#59a14f', '#edc948', '#b07aa1', '#f28e2b', '#76b7b2', '#ff9da7'];
const money = (v: number, cur: string) => `${v < 0 ? '−' : ''}${cur}${Math.abs(Math.round(v)).toLocaleString()}`;

export function TransitionRiskCard({ data, runName, period = null }: Props) {
  const cur = data.currency || '';
  const [params, setParams] = React.useState<TransitionRiskQuery>({
    ...DEFAULT_PARAMS,
    basePrice: Math.max(DEFAULT_PARAMS.basePrice, Math.round(data.carbonPrice) || DEFAULT_PARAMS.basePrice),
  });
  const set = (patch: Partial<TransitionRiskQuery>) => setParams((p) => ({ ...p, ...patch }));

  const [asked, setAsked] = React.useState(params);
  React.useEffect(() => {
    const t = window.setTimeout(() => setAsked(params), EDIT_DEBOUNCE_MS);
    return () => window.clearTimeout(t);
  }, [params]);

  const { data: result, loading, error } = useAsync(
    runName ? `${runName}|transition-risk|${period ?? ''}|${JSON.stringify(asked)}` : null,
    () => fetchRunAnalysis(runName as string, 'transition-risk', { period, ...asked }),
  );
  const summary = result?.summary;
  const shown = (result?.companies ?? []).slice(0, PALETTE.length);

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
        <label>Demand %/yr
          <input type="number" step={1} value={params.demandGrowthPct}
            onChange={(e) => set({ demandGrowthPct: Number(e.target.value) || 0 })} />
        </label>
        <label>Fuel price %/yr
          <input type="number" step={1} value={params.fuelGrowthPct}
            onChange={(e) => set({ fuelGrowthPct: Number(e.target.value) || 0 })} />
        </label>
        <label>Stranded ≤ {cur}
          <input type="number" step={1000} value={params.strandedThreshold}
            onChange={(e) => set({ strandedThreshold: Number(e.target.value) || 0 })} />
        </label>
      </div>

      {!runName && <p className="dashboard-cell-missing">Transition risk needs a stored run.</p>}
      {error && <p className="dashboard-cell-missing" role="alert">Could not load the transition risk: {error}</p>}
      {runName && !result && !error && <p className="dashboard-cell-missing" aria-busy="true">Loading transition risk…</p>}
      {result && summary && (
        <div aria-busy={loading}>
          <div className="econ-kpi-row">
            <div className="econ-kpi">
              <div className="econ-kpi-label">Companies at risk</div>
              <div className={`econ-kpi-value${summary.strandedCount > 0 ? ' econ-negative' : ''}`}>{summary.strandedCount} / {summary.companyCount}</div>
              <div className="econ-kpi-unit">net margin ≤ {money(result.strandedThreshold, cur)} within horizon</div>
            </div>
            <div className="econ-kpi">
              <div className="econ-kpi-label">Earliest stranding</div>
              <div className="econ-kpi-value">{summary.earliestStrandedYear ?? '—'}</div>
              <div className="econ-kpi-unit">first year any owner turns loss-making</div>
            </div>
            <div className="econ-kpi">
              <div className="econ-kpi-label">Total margin at risk</div>
              <div className="econ-kpi-value econ-negative">{money(summary.totalMarginAtRisk, cur)}</div>
              <div className="econ-kpi-unit">cumulative erosion vs {result.baseYear} over {result.trajectory.length - 1} yr</div>
            </div>
            <div className="econ-kpi">
              <div className="econ-kpi-label">Carbon price {result.trajectory[0].year}→{result.trajectory[result.trajectory.length - 1].year}</div>
              <div className="econ-kpi-value">{cur}{Math.round(result.trajectory[0].price)}→{Math.round(result.trajectory[result.trajectory.length - 1].price)}</div>
              <div className="econ-kpi-unit">/tCO₂ at {asked.escalationPct}%/yr</div>
            </div>
          </div>

          <MarginChart companies={shown} baseline={result.strandedThreshold} currency={cur} />

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
        </div>
      )}

      <p className="econ-footnote">
        Dispatch held at the solved outcome; the carbon price rises along the trajectory, and
        (optionally) demand and fuel prices escalate — scaling the volume-linked revenue, fuel and
        emissions while capex/interest stay fixed. A company is stranded the first year its net
        margin falls to/below the threshold.
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
