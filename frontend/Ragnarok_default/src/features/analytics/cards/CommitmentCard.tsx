/**
 * CommitmentCard (Tier 1) — unit-commitment results.
 *
 * For each committable generator: its on/off pattern over the horizon (a
 * run-length strip), how many times it started, the cost of those starts, and
 * how much of the horizon it ran. Makes the cost of cycling plant visible — the
 * reason a peaker's offer must cover its start-up.
 */
import React from 'react';
import { CommitmentResult, CommitmentSegment } from 'lib/types';
import { carrierColor } from 'lib/utils/helpers';

function compactMoney(v: number, currency: string): string {
  const abs = Math.abs(v);
  if (abs >= 1e9) return `${currency}${(abs / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `${currency}${(abs / 1e6).toFixed(2)}M`;
  if (abs >= 1e3) return `${currency}${(abs / 1e3).toFixed(1)}k`;
  return `${currency}${Math.round(abs).toLocaleString()}`;
}

/** A proportional on/off strip: coloured where on, faint where off. */
function StatusStrip({ segments, total, color }: { segments: CommitmentSegment[]; total: number; color: string }) {
  const W = 200, H = 14;
  let x = 0;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width={W} height={H} preserveAspectRatio="none" style={{ display: 'block' }} role="img">
      <rect x={0} y={0} width={W} height={H} fill="var(--border,#e5e7eb)" fillOpacity={0.35} />
      {segments.map((s, i) => {
        const w = (s.length / (total || 1)) * W;
        const rect = s.on ? <rect key={i} x={x} y={0} width={Math.max(w, 0.5)} height={H} fill={color} /> : null;
        x += w;
        return rect;
      })}
    </svg>
  );
}

interface Props {
  data: CommitmentResult;
}

export function CommitmentCard({ data }: Props) {
  const { currency, snapshotCount, generators, totals } = data;
  if (!generators.length) {
    return <p className="dashboard-cell-missing">No committable units in this run.</p>;
  }
  return (
    <div className="econ-card">
      <div className="econ-kpi-row">
        <div className="econ-kpi">
          <div className="econ-kpi-label">Total starts</div>
          <div className="econ-kpi-value">{totals.starts.toLocaleString()}</div>
          <div className="econ-kpi-unit">across {totals.committableCount} committable unit{totals.committableCount === 1 ? '' : 's'}</div>
        </div>
        <div className="econ-kpi">
          <div className="econ-kpi-label">Start-up cost</div>
          <div className="econ-kpi-value">{compactMoney(totals.startUpCostTotal, currency)}</div>
          <div className="econ-kpi-unit">total over the horizon</div>
        </div>
      </div>

      <div className="econ-body">
        <div className="econ-table-col">
          <p className="econ-section-label">Commitment by unit — on/off pattern over the horizon</p>
          <div className="econ-table-wrap">
            <table className="econ-table">
              <thead>
                <tr>
                  <th>Unit</th>
                  <th>Carrier</th>
                  <th>On/off pattern</th>
                  <th className="num">Starts</th>
                  <th className="num">Online</th>
                  <th className="num">Start-up cost</th>
                  <th className="num">Min up/down</th>
                </tr>
              </thead>
              <tbody>
                {generators.map((g) => (
                  <tr key={g.name}>
                    <td>{g.name}</td>
                    <td>
                      <span className="carrier-dot" style={{ backgroundColor: carrierColor(g.carrier) }} />
                      {g.carrier || '—'}
                    </td>
                    <td><StatusStrip segments={g.segments} total={snapshotCount} color={carrierColor(g.carrier)} /></td>
                    <td className="num">{g.starts.toLocaleString()}</td>
                    <td className="num">{(g.onlineFraction * 100).toFixed(0)}%</td>
                    <td className="num">{g.startUpCostTotal > 0 ? compactMoney(g.startUpCostTotal, currency) : '—'}</td>
                    <td className="num">{g.minUpTime}/{g.minDownTime}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <p className="econ-note">
        Committable units carry a binary on/off decision, a start-up cost, and minimum up/down times, so
        the solve is a MILP. The strip shows each unit's on (coloured) / off (faint) pattern; “Starts” ×
        the per-start cost gives its start-up cost. This is the cold/hot-start economics behind the price —
        a unit that must start to serve a peak has to recover that cost in its offer.
      </p>
    </div>
  );
}
