/**
 * MaintenanceCard (P11) — scheduled maintenance of `maintainable` units.
 *
 * One Gantt-like row per unit: the strip spans the solved horizon (snapshot
 * index on the x axis) and is filled where the optimiser placed the unit in
 * maintenance. Beside it: the number of maintenance events, the hours spent in
 * maintenance (weighted by the snapshot weighting) and the derating factor
 * (`maintenance_pu`) applied while in maintenance.
 */
import React from 'react';
import { CommitmentSegment, MaintenanceResult } from 'lib/types';

const num = (v: number, d = 1) => v.toLocaleString(undefined, { maximumFractionDigits: d });

/** Start index and length of every in-maintenance run. */
export function maintenanceSpans(segments: CommitmentSegment[]): Array<{ start: number; length: number }> {
  const out: Array<{ start: number; length: number }> = [];
  let at = 0;
  for (const s of segments) {
    if (s.on) out.push({ start: at, length: s.length });
    at += s.length;
  }
  return out;
}

/** Number of snapshots a run-length encoding covers. */
export function segmentTotal(segments: CommitmentSegment[]): number {
  return segments.reduce((a, s) => a + s.length, 0);
}

function Strip({ segments, total, label }: { segments: CommitmentSegment[]; total: number; label: string }) {
  const W = 360, H = 16;
  const spans = maintenanceSpans(segments);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} preserveAspectRatio="none" style={{ display: 'block', minWidth: 160 }} role="img" aria-label={label}>
      <rect x={0} y={0} width={W} height={H} fill="var(--border,#e5e7eb)" fillOpacity={0.35} />
      {spans.map((s) => (
        <rect key={s.start} x={(s.start / (total || 1)) * W} y={0} width={Math.max((s.length / (total || 1)) * W, 1)} height={H} fill="var(--accent,#b45309)">
          <title>{`Snapshots ${s.start} to ${s.start + s.length - 1} (${s.length})`}</title>
        </rect>
      ))}
    </svg>
  );
}

interface Props {
  data: MaintenanceResult;
}

export function MaintenanceCard({ data }: Props) {
  const { units, totals } = data;
  if (!units.length) return <p className="dashboard-cell-missing">No maintainable units in this run.</p>;
  const total = Math.max(...units.map((u) => segmentTotal(u.segments)), 1);
  const hours = units.reduce((a, u) => a + u.hoursInMaintenance, 0);
  return (
    <div className="econ-card">
      <div className="econ-kpi-row">
        <div className="econ-kpi">
          <div className="econ-kpi-label">Maintainable units</div>
          <div className="econ-kpi-value">{totals.unitCount.toLocaleString()}</div>
        </div>
        <div className="econ-kpi">
          <div className="econ-kpi-label">Maintenance events</div>
          <div className="econ-kpi-value">{totals.events.toLocaleString()}</div>
        </div>
        <div className="econ-kpi">
          <div className="econ-kpi-label">Hours in maintenance</div>
          <div className="econ-kpi-value">{num(hours, 0)}</div>
          <div className="econ-kpi-unit">summed over units</div>
        </div>
      </div>
      <div className="econ-body">
        <div className="econ-table-col">
          <p className="econ-section-label">Maintenance schedule — filled = in maintenance, over {total.toLocaleString()} snapshots</p>
          <div className="econ-table-wrap">
            <table className="econ-table">
              <thead>
                <tr>
                  <th>Unit</th>
                  <th>Schedule</th>
                  <th className="num">Events</th>
                  <th className="num">Hours</th>
                  <th className="num">Derating (pu)</th>
                </tr>
              </thead>
              <tbody>
                {units.map((u) => (
                  <tr key={`${u.component}-${u.name}`}>
                    <td>{u.name} <span className="econ-sub">{u.component}</span></td>
                    <td style={{ width: '55%' }}><Strip segments={u.segments} total={total} label={`${u.name} maintenance schedule`} /></td>
                    <td className="num">{u.events.toLocaleString()}</td>
                    <td className="num">{num(u.hoursInMaintenance)}</td>
                    <td className="num">{num(u.maintenancePu, 3)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
      <p className="econ-note">
        Units with <code>maintainable</code> set get a binary maintenance decision (the solve is a MILP) and
        must be in maintenance for <code>maintenance_duration</code> snapshots; while in maintenance the
        available capacity is scaled by <code>maintenance_pu</code>. Hours are weighted by the snapshot weighting.
      </p>
    </div>
  );
}
