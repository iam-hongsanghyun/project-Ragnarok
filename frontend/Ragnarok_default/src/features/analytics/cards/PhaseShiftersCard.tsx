/**
 * PhaseShiftersCard (P12) — optimised phase-shifting transformer angles.
 *
 * A transformer with `phase_shift_min < phase_shift_max` has its angle chosen by
 * the optimiser per snapshot (`phase_shift_opt`, degrees). The table gives each
 * unit's bounds, mean / min / max chosen angle and the share of snapshots sitting
 * at a bound (a binding phase shifter); the chart plots the chosen angle over the
 * horizon against the bounds for the selected transformer.
 */
import React, { useState } from 'react';
import { PhaseShiftersResult, PhaseShifterRow } from 'lib/types';

const deg = (v: number) => v.toLocaleString(undefined, { maximumFractionDigits: 3 });

/** Polyline points for the series scaled into the plot box; bounds set the y range. */
export function phaseShiftPoints(
  row: PhaseShifterRow, width: number, height: number,
): { points: string; yOf: (v: number) => number } {
  const lo = Math.min(row.phaseShiftMinDeg, row.minDeg);
  const hi = Math.max(row.phaseShiftMaxDeg, row.maxDeg);
  const span = hi - lo || 1;
  const yOf = (v: number) => height - ((v - lo) / span) * height;
  const n = row.series.length;
  const points = row.series
    .map((p, i) => `${((n <= 1 ? 0 : i / (n - 1)) * width).toFixed(1)},${yOf(p.phaseShiftDeg).toFixed(1)}`)
    .join(' ');
  return { points, yOf };
}

function SeriesChart({ row }: { row: PhaseShifterRow }) {
  const W = 520, H = 160, PAD_L = 48, PAD_R = 8, PAD_T = 8, PAD_B = 8;
  const { points, yOf } = phaseShiftPoints(row, W, H);
  const first = row.series[0]?.snapshot ?? '';
  const last = row.series[row.series.length - 1]?.snapshot ?? '';
  return (
    <svg viewBox={`0 0 ${W + PAD_L + PAD_R} ${H + PAD_T + PAD_B}`} width="100%" role="img" aria-label={`${row.name} optimised phase shift`}>
      <g transform={`translate(${PAD_L},${PAD_T})`}>
        {[row.phaseShiftMinDeg, row.phaseShiftMaxDeg].map((b, i) => (
          <g key={i}>
            <line x1={0} x2={W} y1={yOf(b)} y2={yOf(b)} stroke="var(--text-muted,#6b7280)" strokeDasharray="4 3" />
            <text x={-4} y={yOf(b) + 3} textAnchor="end" fontSize={10} fill="var(--text-muted,#6b7280)">{deg(b)}</text>
          </g>
        ))}
        <polyline points={points} fill="none" stroke="var(--accent,#2563eb)" strokeWidth={1.5}>
          <title>{`${row.name}: ${first} to ${last}`}</title>
        </polyline>
      </g>
    </svg>
  );
}

interface Props {
  data: PhaseShiftersResult;
}

export function PhaseShiftersCard({ data }: Props) {
  const rows = data.transformers;
  const [selected, setSelected] = useState<string>(rows[0]?.name ?? '');
  if (!rows.length) return <p className="dashboard-cell-missing">No optimised phase shifters in this run.</p>;
  const current = rows.find((r) => r.name === selected) ?? rows[0];
  return (
    <div className="econ-card">
      <div className="econ-body">
        <div className="econ-table-col">
          <p className="econ-section-label">Optimised phase-shift angle (degrees)</p>
          <div className="econ-table-wrap">
            <table className="econ-table">
              <thead>
                <tr>
                  <th>Transformer</th>
                  <th className="num">Min bound</th>
                  <th className="num">Max bound</th>
                  <th className="num">Mean</th>
                  <th className="num">Min</th>
                  <th className="num">Max</th>
                  <th className="num">At bound</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.name} onClick={() => setSelected(r.name)} style={{ cursor: 'pointer', fontWeight: r.name === current.name ? 600 : undefined }}>
                    <td>{r.name}</td>
                    <td className="num">{deg(r.phaseShiftMinDeg)}</td>
                    <td className="num">{deg(r.phaseShiftMaxDeg)}</td>
                    <td className="num">{deg(r.meanDeg)}</td>
                    <td className="num">{deg(r.minDeg)}</td>
                    <td className="num">{deg(r.maxDeg)}</td>
                    <td className="num">{(Math.min(r.shareAtBound, 1) * 100).toFixed(0)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
      <div className="econ-body">
        <div className="econ-table-col">
          <p className="econ-section-label">
            <label>
              Series for{' '}
              <select value={current.name} onChange={(e) => setSelected(e.target.value)} aria-label="Transformer">
                {rows.map((r) => <option key={r.name} value={r.name}>{r.name}</option>)}
              </select>
            </label>
            {' '}— dashed lines are the bounds
          </p>
          <SeriesChart row={current} />
        </div>
      </div>
      <p className="econ-note">
        The angle is a per-snapshot decision variable of <code>n.optimize()</code> for transformers whose
        <code> phase_shift_min</code> is below <code>phase_shift_max</code>. A high share at a bound means the
        phase shifter is limiting: widening that bound would change the dispatch.
      </p>
    </div>
  );
}
