/**
 * Duration curve of the system price or load, derived on the server
 * (`GET /api/runs/{name}/derived/{metric}`, WA7) from the stored run's output
 * series, so a light (stored) bundle needs no per-asset hydration to draw it.
 * Values are sorted descending here; the load curve drops non-positive snapshots,
 * as the in-memory version does.
 */
import React from 'react';
import { fetchDerivedSeries } from 'lib/api/derivedSeries';
import { useAsync } from '../../../shared/hooks/useAsync';
import { DurationCurveCard } from './DurationCurveCard';

// Above any realistic snapshot count so the server does not downsample (a duration
// curve needs every snapshot, like the in-memory one).
const NO_DOWNSAMPLE = 100_000_000;

interface Props {
  runName: string;
  source: 'price' | 'load';
  currencySymbol: string;
}

export function ServerDurationCurveCard({ runName, source, currencySymbol }: Props) {
  const metric = source === 'price' ? 'system_price' : 'load';
  const { data, loading, error } = useAsync(
    `${runName}|${metric}`,
    () => fetchDerivedSeries(runName, metric, { maxPoints: NO_DOWNSAMPLE }),
  );
  const values = React.useMemo(() => {
    const raw = data?.series[0]?.values ?? [];
    const kept = source === 'load' ? raw.filter((v) => v > 0) : raw;
    return [...kept].sort((a, b) => b - a);
  }, [data, source]);

  if (error) return <p className="dashboard-cell-missing" role="alert">Could not load the {source} duration curve: {error}</p>;
  if (loading || !data) return <p className="dashboard-cell-missing" aria-busy="true">Loading {source} duration curve…</p>;
  return (
    <DurationCurveCard
      title={source === 'price' ? `Marginal price (${currencySymbol}/MWh)` : 'Load (MW)'}
      data={[{
        key: source,
        label: source === 'price' ? 'Marginal price' : 'Load',
        color: source === 'price' ? 'var(--text)' : 'var(--warm)',
        values,
      }]}
      unit={source === 'price' ? `${currencySymbol}/MWh` : 'MW'}
      showLegend={false}
    />
  );
}
