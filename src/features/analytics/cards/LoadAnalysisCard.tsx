/**
 * System-wide and per-bus demand analytics.
 *
 * Differentiates from the existing system-load timeseries chart and load
 * duration curve by exposing **utilisation** metrics that aren't visible
 * from the shape of a single curve:
 *   - System load factor       = avg load / peak load
 *   - Coincidence factor       = system peak / Σ(per-bus peaks)
 *     (lower coincidence ≈ more diversification, lower required reserve)
 *   - Per-bus contribution     = each bus's share of total energy
 *
 * Per-bus rows are sorted by total energy descending; the top contributors
 * are usually the ones worth scrutinising.
 */
import React from 'react';
import { RunResults } from '../../../shared/types';

interface Props {
  results: RunResults;
  currencySymbol: string;
}

function fmt(n: number, digits = 0): string {
  return n.toLocaleString(undefined, { maximumFractionDigits: digits });
}

interface BusRow {
  name: string;
  peakMw: number;
  energyMwh: number;
  loadFactor: number | null;
  share: number;
}

export function LoadAnalysisCard({ results, currencySymbol: _currencySymbol }: Props) {
  const buses = Object.values(results.assetDetails.buses);
  if (buses.length === 0) return null;

  const snapshotWeight = results.runMeta.snapshotWeight ?? 1;

  // Per-bus aggregates
  const busRows: BusRow[] = buses.map((bus) => {
    const loads = bus.netSeries.map((p) => Math.max(0, p.load));
    if (loads.length === 0) {
      return { name: bus.name, peakMw: 0, energyMwh: 0, loadFactor: null, share: 0 };
    }
    const peak = loads.reduce((m, v) => Math.max(m, v), 0);
    const energy = loads.reduce((s, v) => s + v, 0) * snapshotWeight;
    const avg = loads.reduce((s, v) => s + v, 0) / loads.length;
    return {
      name: bus.name,
      peakMw: peak,
      energyMwh: energy,
      loadFactor: peak > 0 ? avg / peak : null,
      share: 0, // filled below
    };
  });

  const totalEnergy = busRows.reduce((s, r) => s + r.energyMwh, 0);
  for (const r of busRows) {
    r.share = totalEnergy > 0 ? r.energyMwh / totalEnergy : 0;
  }
  busRows.sort((a, b) => b.energyMwh - a.energyMwh);

  // System-wide aggregates (sum over buses at each snapshot)
  const snapshots = buses[0]?.netSeries.length ?? 0;
  const systemLoadAtT: number[] = new Array(snapshots).fill(0);
  for (const bus of buses) {
    for (let i = 0; i < snapshots; i++) {
      systemLoadAtT[i] += Math.max(0, bus.netSeries[i]?.load ?? 0);
    }
  }
  const systemPeak = systemLoadAtT.reduce((m, v) => Math.max(m, v), 0);
  const systemAvg = snapshots > 0 ? systemLoadAtT.reduce((s, v) => s + v, 0) / snapshots : 0;
  const sumBusPeaks = busRows.reduce((s, r) => s + r.peakMw, 0);
  const systemLoadFactor = systemPeak > 0 ? systemAvg / systemPeak : null;
  const coincidenceFactor = sumBusPeaks > 0 ? systemPeak / sumBusPeaks : null;

  if (totalEnergy <= 0) return null;

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
          <span className="kpi-value">{fmt(systemPeak)}</span>
          <span className="kpi-unit">MW</span>
        </div>
        <div className="kpi-card">
          <span className="kpi-label">System energy</span>
          <span className="kpi-value">{fmt(totalEnergy)}</span>
          <span className="kpi-unit">MWh</span>
        </div>
        <div className="kpi-card">
          <span className="kpi-label">Load factor</span>
          <span className="kpi-value">{systemLoadFactor !== null ? `${(systemLoadFactor * 100).toFixed(1)}%` : '—'}</span>
          <span className="kpi-unit">avg / peak</span>
        </div>
        <div className="kpi-card">
          <span className="kpi-label">Coincidence</span>
          <span className="kpi-value">{coincidenceFactor !== null ? `${(coincidenceFactor * 100).toFixed(1)}%` : '—'}</span>
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
          {busRows.filter((r) => r.energyMwh > 0).map((r) => (
            <tr key={r.name}>
              <td>{r.name}</td>
              <td>{fmt(r.peakMw)}</td>
              <td>{fmt(r.energyMwh)}</td>
              <td>{r.loadFactor !== null ? `${(r.loadFactor * 100).toFixed(1)}%` : '—'}</td>
              <td>{`${(r.share * 100).toFixed(1)}%`}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
