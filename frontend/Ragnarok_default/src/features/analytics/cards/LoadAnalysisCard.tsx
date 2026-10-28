/**
 * System-wide and per-bus demand analytics.
 *
 * Exposes **utilisation** metrics that aren't visible from the shape of a single curve:
 *   - System load factor       = avg load / peak load
 *   - Coincidence factor       = system peak / sum of per-bus peaks
 *     (lower coincidence = more diversification, lower required reserve)
 *   - Per-bus contribution     = each bus's share of total energy
 *
 * Every figure is a server value (`GET /api/runs/{name}/analysis/load-analysis`, one
 * investment period with `period`); the card only formats it. Buses arrive sorted by
 * energy, largest first.
 */
import React from 'react';
import { fetchRunAnalysis } from 'lib/api/resultsDerived';
import { useAsync } from '../../../shared/hooks/useAsync';

interface Props {
  /** Stored run backing the view. */
  runName?: string | null;
  /** Pathway investment period; null = the whole horizon. */
  period?: number | null;
  currencySymbol: string;
}

function fmt(n: number, digits = 0): string {
  return n.toLocaleString(undefined, { maximumFractionDigits: digits });
}

const pct = (frac: number | null): string => (frac !== null ? `${(frac * 100).toFixed(1)}%` : '—');

export function LoadAnalysisCard({ runName, period = null }: Props) {
  const { data, loading, error } = useAsync(
    runName ? `${runName}|load-analysis|${period ?? ''}` : null,
    () => fetchRunAnalysis(runName as string, 'load-analysis', { period }),
  );
  if (!runName) return <p className="dashboard-cell-missing">Load analysis needs a stored run.</p>;
  if (error) return <p className="dashboard-cell-missing" role="alert">Could not load the load analysis: {error}</p>;
  if (loading || !data) return <p className="dashboard-cell-missing" aria-busy="true">Loading load analysis…</p>;
  if (data.systemEnergyMwh <= 0) return null;

  return (
    <div className="stochastic-card">
      <div className="stochastic-card-header">
        <div>
          <h3>Load analysis</h3>
          <p>
            System-wide demand metrics and per-bus contribution.
            Load factor is average / peak — a higher value means the demand profile is
            flatter. Coincidence factor is the system peak divided by the sum of per-bus
            peaks; values below 1 indicate temporal diversification across buses.
          </p>
        </div>
      </div>

      <div className="kpi-strip" style={{ marginBottom: 12 }}>
        <div className="kpi-card">
          <span className="kpi-label">System peak</span>
          <span className="kpi-value">{fmt(data.systemPeakMw)}</span>
          <span className="kpi-unit">MW</span>
        </div>
        <div className="kpi-card">
          <span className="kpi-label">System energy</span>
          <span className="kpi-value">{fmt(data.systemEnergyMwh)}</span>
          <span className="kpi-unit">MWh</span>
        </div>
        <div className="kpi-card">
          <span className="kpi-label">Load factor</span>
          <span className="kpi-value">{pct(data.systemLoadFactor)}</span>
          <span className="kpi-unit">avg / peak</span>
        </div>
        <div className="kpi-card">
          <span className="kpi-label">Coincidence</span>
          <span className="kpi-value">{pct(data.coincidenceFactor)}</span>
          <span className="kpi-unit">sys / Σ bus</span>
        </div>
      </div>

      <table className="stochastic-table">
        <thead>
          <tr>
            <th>Bus</th>
            <th>Peak load (MW)</th>
            <th>Energy (MWh)</th>
            <th>Load factor</th>
            <th>Share of energy</th>
          </tr>
        </thead>
        <tbody>
          {data.buses.map((r) => (
            <tr key={r.name}>
              <td>{r.name}</td>
              <td>{fmt(r.peakMw)}</td>
              <td>{fmt(r.energyMwh)}</td>
              <td>{pct(r.loadFactor)}</td>
              <td>{pct(r.share)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
