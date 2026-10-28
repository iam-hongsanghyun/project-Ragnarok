import { useMemo } from 'react';
import {
  AnalyticsFocus,
  GroupByOption,
  MetricOption,
  RunResults,
  TimeSeriesRow,
  WorkbookModel,
} from 'lib/types';
import { carrierColor, hashColor, numberValue, orderByCarrierRows } from 'lib/utils/helpers';
import { fetchRunMetrics } from 'lib/api/resultsDerived';
import { fetchDerivedSeries } from 'lib/api/derivedSeries';
import { useAsync } from '../../shared/hooks/useAsync';
import { filterRowsByPeriod, normalizeSeriesPoint, selectGeneratorEnergy } from 'lib/results/analytics';

// ── Public hook ───────────────────────────────────────────────────────────────

/** Where a per-asset chart's data comes from: the stored run, read from the server
 *  (`GET /api/runs/{name}/metrics`). The browser derives no per-asset metric; without a stored run a
 *  per-asset focus has no options. The system focus plots the payload's inline series as given. */
export interface MetricsSource {
  runName: string;
  /** Snapshots to load (the chart's slider right edge, rounded up); null = the whole run. */
  end: number | null;
}

export interface MetricOptionsState {
  options: MetricOption[];
  loading: boolean;
  error: string | null;
}

/** ISO stamp -> the "HH:MM" the series rows label their x axis with. */
function labelOfStamp(stamp: string): string {
  const t = stamp.indexOf('T');
  return t < 0 || stamp.length < t + 6 ? stamp : stamp.slice(t + 1, t + 6);
}

export function useMetricOptions(
  results: RunResults | null,
  _model: WorkbookModel,
  focusType: AnalyticsFocus['type'],
  focusKeys: string[],       // [] = all assets of that type; ['x'] = single
  groupBy: GroupByOption,    // how multi-asset series are combined
  currencySymbol: string = '$',
  busFilter: string[] = [],     // narrow generator/storage/store assets to these buses ([] = all)
  carrierFilter: string[] = [], // narrow generators to these carriers ([] = all)
  source: MetricsSource | null = null,
): MetricOptionsState {
  // ── Server path: per-asset focus of a stored run ────────────────────────────
  const serverFocus = source && focusType !== 'system' ? focusType : null;
  const period = results?.pathway?.enabled ? results.pathway.selectedPeriod ?? null : null;
  const remote = useAsync<MetricOption[]>(
    serverFocus && source
      ? [source.runName, serverFocus, focusKeys.join(','), groupBy, busFilter.join(','), carrierFilter.join(','),
        currencySymbol, period ?? '', source.end ?? ''].join('|')
      : null,
    async () => (await fetchRunMetrics(source!.runName, {
      focus: serverFocus!, keys: focusKeys, groupBy, busFilter, carrierFilter, period,
      end: source!.end, currency: currencySymbol,
    })).items,
  );

  // The system dispatch chart reads the inline aggregate; a bundle without it
  // (light result of a stored run) gets the server's per-carrier dispatch.
  const inlineDispatch = (results?.dispatchSeries || []).length > 0;
  const dispatchFallback = useAsync<TimeSeriesRow[]>(
    source && !inlineDispatch && focusType === 'system' && !period ? `${source.runName}|dispatch_by_carrier` : null,
    async () => {
      const d = await fetchDerivedSeries(source!.runName, 'dispatch_by_carrier', { maxPoints: 100_000_000 });
      return d.labels.map((l, i) => {
        const stamp = String(l);
        const row: TimeSeriesRow = { label: labelOfStamp(stamp), timestamp: stamp };
        for (const s of d.series) row[s.key] = s.values[i] ?? 0;
        return row;
      });
    },
  );

  // ── System-level derived rows (always computed, cheap) ──────────────────────
  const rawDispatch  = (results?.dispatchSeries          || []).map(normalizeSeriesPoint);
  const rawGenDisp   = (results?.generatorDispatchSeries || []).map(normalizeSeriesPoint);
  // `period` tags a pathway row with its investment period; it is not a series.
  const SKIP         = new Set(['label', 'timestamp', 'total', 'period']);
  const hasValues    = (rows: TimeSeriesRow[]) =>
    rows.some((r) => Object.keys(r).some((k) => !SKIP.has(k) && Math.abs(numberValue(r[k] as any)) > 1e-6));

  const sysDispatchRows  = hasValues(rawDispatch)  ? rawDispatch
    : (dispatchFallback.data ?? []);

  // For per-unit dispatch, fall back to a synthetic single-row from the compact
  // generatorEnergy aggregate when both the per-snapshot series and assetDetails
  // are absent (analytics-bundle view). buildDonutFromMetric sums across rows and
  // scales by snapshotWeight, so store the rate-equivalent (MWh / weight) here —
  // generatorEnergy.value is already snapshot-weighted MWh from the backend.
  const snapshotWeightForRows = results?.runMeta?.snapshotWeight || 1;
  const selectedPeriod = results?.pathway?.enabled ? results.pathway.selectedPeriod : null;
  // One family only: whole-horizon entries, or the selected period's entries.
  const genEnergyFallback = selectGeneratorEnergy(results?.generatorEnergy, selectedPeriod);
  const baseGenDispRows = hasValues(rawGenDisp) ? rawGenDisp : [];
  const sysGenDispRows: TimeSeriesRow[] =
    baseGenDispRows.length > 0 || !genEnergyFallback || genEnergyFallback.length === 0
      ? baseGenDispRows
      : [genEnergyFallback.filter((ge) => !ge.name.startsWith('load_shedding_')).reduce(
          (row, ge) => { row[ge.name] = ge.value / snapshotWeightForRows; return row; },
          { label: 'Total', timestamp: '' } as TimeSeriesRow,
        )];

  // System curtailment by carrier: the backend per-carrier aggregate (full and light bundle).
  const sysCurtailRows = filterRowsByPeriod((results?.curtailmentSeries || []).map(normalizeSeriesPoint), selectedPeriod);
  const sysCurtailKeys = Array.from(new Set(sysCurtailRows.flatMap((r) => Object.keys(r).filter((k) => !SKIP.has(k)))));
  const sysCurtailSeries = sysCurtailKeys.map((k) => ({ key: k, label: k, color: carrierColor(k) }));

  // Storage SoC by carrier: the backend per-carrier aggregate.
  const sysSocRows = filterRowsByPeriod((results?.storageSocSeries || []).map(normalizeSeriesPoint), selectedPeriod);
  const sysSocKeys = Array.from(new Set(sysSocRows.flatMap((r) => Object.keys(r).filter((k) => !SKIP.has(k)))));
  const sysSocSeries = sysSocKeys.map((k) => ({ key: k, label: k, color: carrierColor(k) }));

  const rawSysDispKeys   = Array.from(new Set(sysDispatchRows.flatMap((r) => Object.keys(r).filter((k) => !SKIP.has(k)))));
  const sysDispKeys      = orderByCarrierRows(_model.carriers, rawSysDispKeys);
  const sysGenDispKeys   = Array.from(new Set(sysGenDispRows.flatMap((r) => Object.keys(r).filter((k) => !SKIP.has(k)))));
  const sysDispSeries    = sysDispKeys.map((k) => ({ key: k, label: k, color: carrierColor(k) }));
  const sysGenDispSeries = sysGenDispKeys.map((k) => ({
    key: k, label: k,
    color: genEnergyFallback?.find((ge) => ge.name === k)?.color || hashColor(k),
  }));
  const sysPriceRows     = (results?.systemPriceSeries     || []).map((p) => ({ label: p.label, timestamp: p.timestamp, price: p.value }));
  const sysEmissionsRows = (results?.systemEmissionsSeries || []).map((p) => ({ label: p.label, timestamp: p.timestamp, emissions: p.value }));
  const storageRows      = (results?.storageSeries         || []).map((p) => ({ label: p.label, timestamp: p.timestamp, charge: p.charge, discharge: p.discharge, state: p.state }));
  const sysLoadRows      = (results?.dispatchSeries || []).map((p) => ({ label: p.label, timestamp: p.timestamp, load: numberValue(p.total) }));

  const local = useMemo((): MetricOption[] => {
    if (!results) return [];
    if (serverFocus) return []; // served by `remote`

    // ── System ────────────────────────────────────────────────────────────────
    if (focusType === 'system') {
      return [
        { key: 'dispatch',          label: 'Dispatch by carrier',       unit: 'MW',     rows: sysDispatchRows,  series: sysDispSeries,                                                                                                                                           reducer: 'mean', allowDonut: true  },
        { key: 'dispatch_by_gen',   label: 'Dispatch by generator',     unit: 'MW',     rows: sysGenDispRows,   series: sysGenDispSeries,                                                                                                                                        reducer: 'mean', allowDonut: true  },
        { key: 'curtailment',       label: 'Curtailment by carrier',     unit: 'MW',     rows: sysCurtailRows,   series: sysCurtailSeries,                                                                                                                                        reducer: 'mean', allowDonut: true  },
        { key: 'load',              label: 'Total load',                 unit: 'MW',     rows: sysLoadRows,      series: [{ key: 'load',      label: 'Load MW',         color: '#f97316' }],                                                                                    reducer: 'mean', allowDonut: false },
        { key: 'system_price',      label: 'System marginal price',      unit: `${currencySymbol}/MWh`,  rows: sysPriceRows,     series: [{ key: 'price',     label: `Price ${currencySymbol}/MWh`,     color: '#111827' }],                                                                                    reducer: 'mean', allowDonut: false },
        { key: 'system_emissions',  label: 'System emissions',           unit: 'tCO2e',  rows: sysEmissionsRows, series: [{ key: 'emissions', label: 'Emissions tCO2e', color: '#16a34a' }],                                                                                    reducer: 'sum',  allowDonut: false },
        { key: 'storage_power',     label: 'Storage power',              unit: 'MW',     rows: storageRows,      series: [{ key: 'charge',    label: 'Charge MW',       color: '#0ea5e9' }, { key: 'discharge', label: 'Discharge MW', color: '#f97316' }],                    reducer: 'mean', allowDonut: true  },
        { key: 'storage_state',     label: 'Storage state of charge',    unit: 'MWh',    rows: storageRows,      series: [{ key: 'state',     label: 'State of charge', color: '#14b8a6' }],                                                                                    reducer: 'mean', allowDonut: false },
        { key: 'storage_soc_by_carrier', label: 'Storage SoC by carrier', unit: 'MWh',   rows: sysSocRows,       series: sysSocSeries,                                                                                                                                            reducer: 'mean', allowDonut: false },
      ];
    }

    // Per-asset focus: served by `remote` (needs a stored run); nothing is derived here.
    return [];
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [results, focusType, currencySymbol, serverFocus,
      sysDispatchRows, sysDispSeries, sysGenDispRows, sysGenDispSeries,
      sysLoadRows, sysPriceRows, sysEmissionsRows, storageRows]);

  if (serverFocus) return { options: remote.data ?? [], loading: remote.loading, error: remote.error };
  return { options: local, loading: false, error: null };
}
