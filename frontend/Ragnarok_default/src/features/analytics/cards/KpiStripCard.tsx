/**
 * KPI strip card — Bloomberg-style terminal row with 9 headline
 * metrics for a finished run. Every figure is read from the server
 * (`GET /api/runs/{name}/kpis`, with `period` for one investment period of a pathway
 * run); the browser derives none of them. Results imported from a file are stored as
 * runs, so they take the same route.
 */
import React from 'react';
import { fetchRunKpis, RunKpis } from 'lib/api/resultsDerived';
import { useAsync } from '../../../shared/hooks/useAsync';

interface KpiCardProps {
  label: string;
  value: string;
  unit: string;
  green?: boolean;
}

function KpiCard({ label, value, unit, green }: KpiCardProps) {
  return (
    <div className={`kpi-card${green ? ' kpi-card--green' : ''}`}>
      <div className="kpi-label">{label}</div>
      <div className="kpi-value">{value}</div>
      <div className="kpi-unit">{unit}</div>
    </div>
  );
}

interface Props {
  currencySymbol?: string;
  /** Stored run to read the KPIs from. */
  runName?: string | null;
  /** Pathway investment period; null/absent = the whole horizon. */
  period?: number | null;
}

export function KpiStrip({ kpis }: { kpis: RunKpis }) {
  const cur = kpis.currencySymbol;
  const weight = kpis.snapshotWeightHours ?? 0;
  return (
    <div className="kpi-strip">
      <KpiCard label="Total cost"   value={kpis.totalCost ?? '—'} unit="" />
      <KpiCard label="Dispatch"     value={Math.round(kpis.dispatchMwh).toLocaleString()} unit="MWh" />
      <KpiCard label="Avg price (load-wtd)" value={kpis.avgPrice.toFixed(1)} unit={`${cur}/MWh`} />
      <KpiCard label="Min · Max"    value={kpis.minPrice !== null && kpis.maxPrice !== null ? `${kpis.minPrice.toFixed(0)} · ${kpis.maxPrice.toFixed(0)}` : '—'} unit={`${cur}/MWh`} />
      <KpiCard label="Peak load"    value={kpis.peakLoadMw !== null ? Math.round(kpis.peakLoadMw).toLocaleString() : '—'} unit="MW" />
      <KpiCard label="Load factor"  value={kpis.loadFactor !== null ? `${(kpis.loadFactor * 100).toFixed(1)}%` : '—'} unit="" />
      <KpiCard label="Renewables"   value={`${kpis.renewableSharePct.toFixed(1)}%`} unit="" green={kpis.renewableSharePct >= 50} />
      <KpiCard label="Emissions"    value={kpis.emissions ?? '—'} unit="" />
      <KpiCard label="Snapshots"    value={String(kpis.snapshotCount ?? '—')} unit={`× ${Number(weight.toFixed(2))}h`} />
    </div>
  );
}

export function KpiStripCard({ currencySymbol = '$', runName, period = null }: Props) {
  const { data, loading, error } = useAsync(
    runName ? `${runName}|${currencySymbol}|${period ?? ''}` : null,
    () => fetchRunKpis(runName as string, currencySymbol, period),
  );
  if (!runName) return <p className="dashboard-cell-missing">KPIs are read from a stored run; this result has none.</p>;
  if (error) return <p className="dashboard-cell-missing" role="alert">Could not load KPIs: {error}</p>;
  if (loading || !data) return <p className="dashboard-cell-missing" aria-busy="true">Loading KPIs…</p>;
  return <KpiStrip kpis={data.kpis} />;
}
