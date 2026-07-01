/**
 * DemandResponseCard (M2) — shiftable-load outcome.
 *
 * Headline: total energy time-shifted and the peak-demand reduction it bought,
 * with a per-load breakdown of nominal vs post-shift peak. Energy is moved, not
 * dropped — so total demand is unchanged; the win is cheaper timing and a lower
 * peak.
 */
import React from 'react';
import { DemandResponseResult } from 'lib/types';

const gwh = (mwh: number) => (mwh >= 1e4 ? `${(mwh / 1e3).toFixed(1)} GWh` : `${Math.round(mwh).toLocaleString()} MWh`);

interface Props {
  data: DemandResponseResult;
}

export function DemandResponseCard({ data }: Props) {
  if (!data.loads.length) {
    return <p className="dashboard-cell-missing">No demand response in this run.</p>;
  }
  const shiftedLoads = data.loads.filter((l) => l.shiftedMWh > 0.05);
  const bestReduction = Math.max(0, ...data.loads.map((l) => l.peakReductionPct));

  return (
    <div className="econ-card">
      <div className="econ-kpi-row">
        <div className="econ-kpi">
          <div className="econ-kpi-label">Energy shifted</div>
          <div className="econ-kpi-value econ-recovered">{gwh(data.totalShiftedMWh)}</div>
          <div className="econ-kpi-unit">moved in time, not curtailed</div>
        </div>
        <div className="econ-kpi">
          <div className="econ-kpi-label">Loads shifted</div>
          <div className="econ-kpi-value">{shiftedLoads.length}<span className="econ-kpi-sub"> / {data.loads.length}</span></div>
          <div className="econ-kpi-unit">flexible loads that moved</div>
        </div>
        <div className="econ-kpi">
          <div className="econ-kpi-label">Best peak cut</div>
          <div className="econ-kpi-value">{bestReduction.toFixed(0)}%</div>
          <div className="econ-kpi-unit">largest per-load peak reduction</div>
        </div>
      </div>

      <div className="econ-table-wrap">
        <table className="econ-table">
          <thead>
            <tr>
              <th>Load</th>
              <th className="num">Shifted</th>
              <th className="num">Peak before</th>
              <th className="num">Peak after</th>
              <th className="num">Peak cut</th>
            </tr>
          </thead>
          <tbody>
            {data.loads.map((l) => (
              <tr key={l.name}>
                <td>{l.name}</td>
                <td className="num">{gwh(l.shiftedMWh)}</td>
                <td className="num">{Math.round(l.peakBeforeMW).toLocaleString()} MW</td>
                <td className="num">{Math.round(l.peakAfterMW).toLocaleString()} MW</td>
                <td className={`num ${l.peakReductionPct > 0 ? 'econ-recovered' : ''}`}>
                  {l.peakReductionPct > 0 ? `${l.peakReductionPct.toFixed(0)}%` : '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="econ-note">
        Each shiftable load draws from an energy buffer, so consumption can lead or lag its nominal
        profile within the configured power and duration. Total demand is unchanged — the buffer only
        re-times it into cheaper hours, which also clips the peak. Buffer round-trip is lossless in
        this model; capacity/ancillary value is not included.
      </p>
    </div>
  );
}
