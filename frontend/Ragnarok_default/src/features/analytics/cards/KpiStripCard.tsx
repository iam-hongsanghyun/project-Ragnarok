/**
 * KPI strip card — Bloomberg-style terminal row with 9 headline
 * metrics for a finished run. A stored run reads them from the server
 * (`GET /api/runs/{name}/kpis`, WA7); a result with no stored run (an imported
 * project) or a pathway run (period-specific view) derives them locally via
 * `kpisFromResults`. Both produce the same `RunKpis`.
 */
import React from 'react';
import { RunResults, WorkbookModel } from 'lib/types';
import { fetchRunKpis, RunKpis } from 'lib/api/resultsDerived';
import { kpisFromResults } from 'lib/results/kpis';
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
  results: RunResults;
  model: WorkbookModel;
  currencySymbol?: string;
  /** Stored run to read the KPIs from; null/absent derives them locally. */
  runName?: string | null;
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

function ServerKpis({ runName, currencySymbol }: { runName: string; currencySymbol: string }) {
  const { data, loading, error } = useAsync(
    `${runName}|${currencySymbol}`,
    () => fetchRunKpis(runName, currencySymbol),
  );
  if (error) return <p className="dashboard-cell-missing" role="alert">Could not load KPIs: {error}</p>;
  if (loading || !data) return <p className="dashboard-cell-missing" aria-busy="true">Loading KPIs…</p>;
  return <KpiStrip kpis={data.kpis} />;
}

export function KpiStripCard({ results, model, currencySymbol = '$', runName }: Props) {
  const local = !runName || !!results.pathway?.enabled;
  const localKpis = React.useMemo(
    () => (local ? kpisFromResults(results, model, currencySymbol) : null),
    [local, results, model, currencySymbol],
  );
  if (localKpis) return <KpiStrip kpis={localKpis} />;
  return <ServerKpis runName={runName as string} currencySymbol={currencySymbol} />;
}
