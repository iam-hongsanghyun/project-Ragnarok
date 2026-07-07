/**
 * RampCard — timestep-weighted ramp-rate limit results.
 *
 * KPI row from the backend summary (binding hours, mean/max |Δp|), plus a
 * by-carrier donut of mean |Δp|.
 */
import React, { useMemo } from 'react';
import { RampResult } from 'lib/types';
import { DonutChart } from './DonutChart';

interface Props {
  data: RampResult;
}

export function RampCard({ data }: Props) {
  const summary = useMemo(() => (Array.isArray(data?.summary) ? data.summary : []), [data]);
  const byCarrier = useMemo(() => (Array.isArray(data?.byCarrier) ? data.byCarrier : []), [data]);

  if (!data || !data.enabled) return null;

  return (
    <div className="econ-card">
      <div className="econ-kpi-row">
        {summary.map((s) => (
          <div className="econ-kpi" key={s.label}>
            <div className="econ-kpi-label">{s.label}</div>
            <div className="econ-kpi-value">{s.value}</div>
            {s.detail && <div className="econ-kpi-unit">{s.detail}</div>}
          </div>
        ))}
        <div className="econ-kpi">
          <div className="econ-kpi-label">Binding hours</div>
          <div className="econ-kpi-value">{data.bindingHours?.toLocaleString() ?? '—'}</div>
          <div className="econ-kpi-unit">snapshots where a ramp limit bound</div>
        </div>
      </div>

      {byCarrier.length > 0 && (
        <div className="econ-body">
          <div className="econ-table-col">
            <p className="econ-section-label">Mean |Δoutput| by carrier</p>
            <DonutChart data={byCarrier.map((c) => ({ label: c.label, value: c.value, color: c.color ?? 'var(--muted, #6b7280)' }))} unit="MW" />
          </div>
        </div>
      )}

      {data.note && <p className="econ-note">{data.note}</p>}
    </div>
  );
}
