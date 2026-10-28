/**
 * Duration curve of the system price or load, ranked on the server
 * (`GET /api/runs/{name}/analysis/duration-curve`) from the stored run's output series: values
 * arrive sorted descending (the load curve omits non-positive snapshots) and, for a pathway run,
 * for the selected investment period only. The card plots them as given.
 */
import React from 'react';
import { fetchRunAnalysis } from 'lib/api/resultsDerived';
import { useAsync } from '../../../shared/hooks/useAsync';
import { DurationCurveCard } from './DurationCurveCard';

interface Props {
  runName: string;
  source: 'price' | 'load';
  currencySymbol: string;
  /** Pathway investment period; null = the whole horizon. */
  period?: number | null;
}

export function ServerDurationCurveCard({ runName, source, currencySymbol, period = null }: Props) {
  const { data, loading, error } = useAsync(
    `${runName}|duration|${source}|${period ?? ''}`,
    () => fetchRunAnalysis(runName, 'duration-curve', { source, period }),
  );
  if (error) return <p className="dashboard-cell-missing" role="alert">Could not load the {source} duration curve: {error}</p>;
  if (loading || !data) return <p className="dashboard-cell-missing" aria-busy="true">Loading {source} duration curve…</p>;
  return (
    <DurationCurveCard
      title={source === 'price' ? `Marginal price (${currencySymbol}/MWh)` : 'Load (MW)'}
      data={[{
        key: source,
        label: source === 'price' ? 'Marginal price' : 'Load',
        color: source === 'price' ? 'var(--text)' : 'var(--warm)',
        values: data.values,
      }]}
      unit={source === 'price' ? `${currencySymbol}/MWh` : 'MW'}
      showLegend={false}
    />
  );
}
