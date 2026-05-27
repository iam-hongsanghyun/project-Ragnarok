/**
 * LoadAnalysisCard — first-class view of the demand side. Loads drive every
 * dispatch outcome, price, and imbalance, but there was no dedicated surface
 * for them. Derives entirely from (model, results) so it works on imported
 * projects with no backend call.
 *
 * Per-bus stats come from results.assetDetails.buses[*].netSeries.load (MW per
 * snapshot). Energy uses the modelled hours-per-snapshot weight:
 *   hoursPerSnapshot = runMeta.modeledHours / runMeta.snapshotCount
 *   energy_MWh       = mean(load) * modeledHours
 *   loadFactor       = mean(load) / peak(load)
 */
import React, { useMemo, useState } from 'react';
import { RunResults, WorkbookModel } from '../../../shared/types';
import { stringValue } from '../../../shared/utils/helpers';

interface Props {
  model: WorkbookModel;
  results: RunResults;
}

interface BusLoadStat {
  bus: string;
  loadCount: number;
  peak: number;
  average: number;
  energy: number;
  loadFactor: number;
}

type SortKey = 'bus' | 'peak' | 'average' | 'energy' | 'loadFactor';

export function LoadAnalysisCard({ model, results }: Props) {
  const [sortKey, setSortKey] = useState<SortKey>('peak');
  const [sortAsc, setSortAsc] = useState(false);

  const modeledHours = results.runMeta.modeledHours || 0;

  // How many load components sit on each bus (for context in the table).
  const loadsPerBus = useMemo(() => {
    const counts: Record<string, number> = {};
    (model.loads ?? []).forEach((row) => {
      const bus = stringValue(row.bus);
      if (!bus) return;
      counts[bus] = (counts[bus] ?? 0) + 1;
    });
    return counts;
  }, [model.loads]);

  const { busStats, systemPeak, systemAverage, systemEnergy, systemLoadFactor } = useMemo(() => {
    const stats: BusLoadStat[] = [];
    // Align bus profiles by snapshot index to build a system profile.
    let snapshotCount = 0;
    Object.values(results.assetDetails.buses).forEach((detail) => {
      snapshotCount = Math.max(snapshotCount, detail.netSeries.length);
    });
    const systemProfile = new Array(snapshotCount).fill(0);

    Object.values(results.assetDetails.buses).forEach((detail) => {
      const loads = detail.netSeries.map((pt) => Math.max(0, pt.load));
      detail.netSeries.forEach((pt, i) => {
        systemProfile[i] += Math.max(0, pt.load);
      });
      const peak = loads.length ? Math.max(...loads) : 0;
      if (peak <= 0) return; // skip buses with no demand
      const average = loads.reduce((s, v) => s + v, 0) / loads.length;
      stats.push({
        bus: detail.name,
        loadCount: loadsPerBus[detail.name] ?? 0,
        peak,
        average,
        energy: average * modeledHours,
        loadFactor: peak > 0 ? average / peak : 0,
      });
    });

    const sysPeak = systemProfile.length ? Math.max(...systemProfile) : 0;
    const sysAvg = systemProfile.length
      ? systemProfile.reduce((s, v) => s + v, 0) / systemProfile.length
      : 0;
    return {
      busStats: stats,
      systemPeak: sysPeak,
      systemAverage: sysAvg,
      systemEnergy: sysAvg * modeledHours,
      systemLoadFactor: sysPeak > 0 ? sysAvg / sysPeak : 0,
    };
  }, [results.assetDetails.buses, loadsPerBus, modeledHours]);

  const sorted = useMemo(() => {
    const rows = [...busStats];
    rows.sort((a, b) => {
      if (sortKey === 'bus') {
        return sortAsc ? a.bus.localeCompare(b.bus) : b.bus.localeCompare(a.bus);
      }
      const av = a[sortKey];
      const bv = b[sortKey];
      return sortAsc ? av - bv : bv - av;
    });
    return rows;
  }, [busStats, sortKey, sortAsc]);

  if (busStats.length === 0) {
    return (
      <p className="empty-text" style={{ padding: '16px' }}>
        No load profile available — add loads with a demand time series and run the model.
      </p>
    );
  }

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) setSortAsc((a) => !a);
    else { setSortKey(key); setSortAsc(key === 'bus'); }
  };

  const arrow = (key: SortKey) => (sortKey === key ? (sortAsc ? ' ↑' : ' ↓') : '');
  const mw = (v: number) => v.toLocaleString(undefined, { maximumFractionDigits: 1 });

  return (
    <div>
      <div className="kpi-strip">
        <div className="kpi-card">
          <div className="kpi-label">Peak demand</div>
          <div className="kpi-value">{mw(systemPeak)}</div>
          <div className="kpi-unit">MW</div>
        </div>
        <div className="kpi-card">
          <div className="kpi-label">Average demand</div>
          <div className="kpi-value">{mw(systemAverage)}</div>
          <div className="kpi-unit">MW</div>
        </div>
        <div className="kpi-card">
          <div className="kpi-label">Total energy</div>
          <div className="kpi-value">{Math.round(systemEnergy).toLocaleString()}</div>
          <div className="kpi-unit">MWh</div>
        </div>
        <div className="kpi-card">
          <div className="kpi-label">System load factor</div>
          <div className="kpi-value">{(systemLoadFactor * 100).toFixed(1)}</div>
          <div className="kpi-unit">%</div>
        </div>
      </div>

      <div style={{ overflowX: 'auto', marginTop: 12 }}>
        <table className="comparison-table">
          <thead>
            <tr>
              <th onClick={() => toggleSort('bus')} style={{ cursor: 'pointer' }}>Bus{arrow('bus')}</th>
              <th>Loads</th>
              <th onClick={() => toggleSort('peak')} style={{ cursor: 'pointer' }}>Peak (MW){arrow('peak')}</th>
              <th onClick={() => toggleSort('average')} style={{ cursor: 'pointer' }}>Average (MW){arrow('average')}</th>
              <th onClick={() => toggleSort('energy')} style={{ cursor: 'pointer' }}>Energy (MWh){arrow('energy')}</th>
              <th onClick={() => toggleSort('loadFactor')} style={{ cursor: 'pointer' }}>Load factor{arrow('loadFactor')}</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((row) => (
              <tr key={row.bus}>
                <td>{row.bus}</td>
                <td>{row.loadCount || '—'}</td>
                <td>{mw(row.peak)}</td>
                <td>{mw(row.average)}</td>
                <td>{Math.round(row.energy).toLocaleString()}</td>
                <td>{(row.loadFactor * 100).toFixed(1)}%</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
