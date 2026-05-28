import { useMemo } from 'react';
import {
  AnalyticsFocus,
  GroupByOption,
  MetricOption,
  RunResults,
  TimeSeriesRow,
  TimeSeriesSeries,
  WorkbookModel,
} from '../../shared/types';
import { carrierColor, hashColor, numberValue, orderByCarrierRows } from '../../shared/utils/helpers';
import { buildRowsFromGeneratorDetails, buildSystemLoadRows, normalizeSeriesPoint } from '../../shared/utils/analytics';

// ── Multi-generator aggregation ───────────────────────────────────────────────

type GenField = 'output' | 'curtailment' | 'available' | 'emissions';

function getGenSeries(
  gen: RunResults['assetDetails']['generators'][string],
  field: GenField,
): Array<{ label: string; timestamp: string; [k: string]: number | string }> {
  switch (field) {
    case 'output':      return gen.outputSeries      as any;
    case 'curtailment': return gen.curtailmentSeries as any;
    case 'available':   return gen.availableSeries   as any;
    case 'emissions':   return gen.emissionsSeries   as any;
  }
}

function getGenFieldValue(pt: Record<string, unknown>, field: GenField): number {
  return (pt[field] as number) ?? 0;
}

function buildMultiGenMetric(
  assetDetails: RunResults['assetDetails'],
  genNames: string[],
  field: GenField,
  groupBy: GroupByOption,
  model: WorkbookModel,
): { rows: TimeSeriesRow[]; series: TimeSeriesSeries[] } {
  // Bucket by full timestamp, not label. Backend labels are "HH:MM" which
  // collide every 24 h — bucketing by label collapses a multi-day window
  // into 24 rows.
  const byTimestamp = new Map<string, { label: string; timestamp: string; vals: Record<string, number> }>();

  for (const name of genNames) {
    const gen = assetDetails.generators[name];
    if (!gen) continue;
    const seriesKey = groupBy === 'carrier' ? (gen.carrier || 'Unknown') : name;

    for (const pt of getGenSeries(gen, field)) {
      const val = getGenFieldValue(pt as any, field);
      const ts = String(pt.timestamp ?? pt.label);
      if (!byTimestamp.has(ts)) {
        byTimestamp.set(ts, { label: String(pt.label), timestamp: ts, vals: {} });
      }
      const e = byTimestamp.get(ts)!;
      e.vals[seriesKey] = (e.vals[seriesKey] || 0) + val;
    }
  }

  const rawSeriesKeys = Array.from(
    new Set(Array.from(byTimestamp.values()).flatMap((e) => Object.keys(e.vals))),
  );
  const seriesKeys = groupBy === 'carrier' ? orderByCarrierRows(model.carriers, rawSeriesKeys) : rawSeriesKeys;

  const rows: TimeSeriesRow[] = Array.from(byTimestamp.values())
    .sort((a, b) => a.timestamp.localeCompare(b.timestamp))
    .map((e) => ({ label: e.label, timestamp: e.timestamp, ...e.vals }));

  const series: TimeSeriesSeries[] = seriesKeys.map((k) => ({
    key: k,
    label: k,
    color: groupBy === 'carrier' ? carrierColor(k) : (assetDetails.generators[k]?.color || hashColor(k)),
  }));

  return { rows, series };
}

// Build all 4 generator metrics for multi-asset selection
function buildMultiGenOptions(
  assetDetails: RunResults['assetDetails'],
  genNames: string[],
  groupBy: GroupByOption,
  model: WorkbookModel,
): MetricOption[] {
  const GEN_FIELDS: Array<{ field: GenField; label: string; unit: string; reducer: MetricOption['reducer'] }> = [
    { field: 'output',      label: 'Output',          unit: 'MW',     reducer: 'mean' },
    { field: 'available',   label: 'Available output', unit: 'MW',     reducer: 'mean' },
    { field: 'curtailment', label: 'Curtailment',      unit: 'MW',     reducer: 'mean' },
    { field: 'emissions',   label: 'Emissions',        unit: 'tCO2e',  reducer: 'sum'  },
  ];

  return GEN_FIELDS.map(({ field, label, unit, reducer }) => {
    const { rows, series } = buildMultiGenMetric(assetDetails, genNames, field, groupBy, model);
    return { key: field, label, unit, rows, series, reducer, allowDonut: groupBy === 'carrier' };
  });
}

// Generic multi-asset merge (by asset name) — used for Bus, Branch, Storage, Store
function buildMultiAssetOptions(
  assetDetails: RunResults['assetDetails'],
  assetKeys: string[],
  focusType: Exclude<AnalyticsFocus['type'], 'system'>,
  currencySymbol: string = '$',
): MetricOption[] {
  const byMetric = new Map<string, MetricOption>();

  for (const assetKey of assetKeys) {
    const singleFocus = { type: focusType, key: assetKey } as AnalyticsFocus;
    const opts = buildSingleAssetOptions(assetDetails, singleFocus, currencySymbol);

    for (const opt of opts) {
      const merged = byMetric.get(opt.key) ?? {
        key: opt.key,
        label: opt.label,
        unit: opt.unit,
        rows: [] as TimeSeriesRow[],
        series: [] as TimeSeriesSeries[],
        reducer: opt.reducer,
        allowDonut: false,
      };

      const rowMap = new Map(merged.rows.map((r) => [`${r.timestamp ?? ''}|${r.label}`, r]));

      for (const s of opt.series) {
        const sk = opt.series.length === 1 ? assetKey : `${assetKey}__${s.key}`;
        const sl = opt.series.length === 1 ? assetKey : `${assetKey} ${s.label}`;
        if (!merged.series.some((x) => x.key === sk)) {
          merged.series.push({ key: sk, label: sl, color: hashColor(`${focusType}:${assetKey}:${s.key}`) });
        }
        for (const row of opt.rows) {
          const rid = `${row.timestamp ?? ''}|${row.label}`;
          const target = rowMap.get(rid) ?? { label: row.label, timestamp: row.timestamp };
          target[sk] = row[s.key];
          rowMap.set(rid, target);
        }
      }

      merged.rows = Array.from(rowMap.values());
      byMetric.set(opt.key, merged);
    }
  }

  return Array.from(byMetric.values());
}

// ── Single-asset options (unchanged logic) ────────────────────────────────────

function buildSingleAssetOptions(
  assetDetails: RunResults['assetDetails'],
  focus: AnalyticsFocus,
  currencySymbol: string = '$',
): MetricOption[] {
  if (focus.type === 'generator') {
    const g = assetDetails.generators[focus.key];
    if (!g) return [];
    const c = g.color || carrierColor(g.carrier || 'Other');
    return [
      { key: 'output',      label: 'Output',          unit: 'MW',    rows: g.outputSeries.map((p)      => ({ label: p.label, timestamp: p.timestamp, output: p.output })),           series: [{ key: 'output',      label: 'Output MW',         color: c }],         reducer: 'mean', allowDonut: false },
      { key: 'available',   label: 'Available output', unit: 'MW',    rows: g.availableSeries.map((p)   => ({ label: p.label, timestamp: p.timestamp, available: p.available })),     series: [{ key: 'available',   label: 'Available MW',      color: '#0f766e' }], reducer: 'mean', allowDonut: false },
      { key: 'curtailment', label: 'Curtailment',      unit: 'MW',    rows: g.curtailmentSeries.map((p) => ({ label: p.label, timestamp: p.timestamp, curtailment: p.curtailment })), series: [{ key: 'curtailment', label: 'Curtailment MW',    color: '#f59e0b' }], reducer: 'mean', allowDonut: false },
      { key: 'emissions',   label: 'Emissions',        unit: 'tCO2e', rows: g.emissionsSeries.map((p)   => ({ label: p.label, timestamp: p.timestamp, emissions: p.emissions })),     series: [{ key: 'emissions',   label: 'Emissions tCO2e',  color: '#16a34a' }], reducer: 'sum',  allowDonut: false },
    ];
  }
  if (focus.type === 'bus') {
    const b = assetDetails.buses[focus.key];
    if (!b) return [];
    return [
      { key: 'load',       label: 'Load',             unit: 'MW',     rows: b.netSeries.map((p) => ({ label: p.label, timestamp: p.timestamp, load: p.load })),             series: [{ key: 'load',       label: 'Load MW',         color: '#f97316' }],  reducer: 'mean', allowDonut: false },
      { key: 'generation', label: 'Generation',        unit: 'MW',     rows: b.netSeries.map((p) => ({ label: p.label, timestamp: p.timestamp, generation: p.generation })), series: [{ key: 'generation', label: 'Generation MW',    color: '#2563eb' }],  reducer: 'mean', allowDonut: false },
      { key: 'smp',        label: 'SMP',               unit: `${currencySymbol}/MWh`,  rows: b.netSeries.map((p) => ({ label: p.label, timestamp: p.timestamp, smp: p.smp })),               series: [{ key: 'smp',        label: `SMP ${currencySymbol}/MWh`,       color: '#111827' }],  reducer: 'mean', allowDonut: false },
      { key: 'emissions',  label: 'Emissions',          unit: 'tCO2e', rows: b.netSeries.map((p) => ({ label: p.label, timestamp: p.timestamp, emissions: p.emissions })),   series: [{ key: 'emissions',  label: 'Emissions tCO2e', color: '#16a34a' }],  reducer: 'sum',  allowDonut: false },
      ...(b.hasVoltageMagnitude ? [{ key: 'v_mag_pu', label: 'Voltage magnitude', unit: 'p.u.',     rows: b.netSeries.map((p) => ({ label: p.label, timestamp: p.timestamp, v_mag_pu: p.v_mag_pu })), series: [{ key: 'v_mag_pu', label: 'Voltage p.u.',    color: '#7c3aed' }], reducer: 'mean' as const, allowDonut: false }] : []),
      ...(b.hasVoltageAngle    ? [{ key: 'v_ang',     label: 'Voltage angle',     unit: 'deg/rad',  rows: b.netSeries.map((p) => ({ label: p.label, timestamp: p.timestamp, v_ang: p.v_ang })),       series: [{ key: 'v_ang',     label: 'Voltage angle',  color: '#8b5cf6' }], reducer: 'mean' as const, allowDonut: false }] : []),
    ];
  }
  if (focus.type === 'storageUnit') {
    const su = assetDetails.storageUnits[focus.key];
    if (!su) return [];
    return [
      { key: 'dispatch',      label: 'Dispatch',        unit: 'MW',  rows: su.dispatchSeries.map((p) => ({ label: p.label, timestamp: p.timestamp, dispatch: p.dispatch })), series: [{ key: 'dispatch', label: 'Dispatch MW', color: '#2563eb' }], reducer: 'mean', allowDonut: false },
      { key: 'storage_power', label: 'Storage power',   unit: 'MW',  rows: su.chargeSeries.map((p, i) => ({ label: p.label, timestamp: p.timestamp, charge: p.charge, discharge: su.dischargeSeries[i]?.discharge || 0 })), series: [{ key: 'charge', label: 'Charge MW', color: '#0ea5e9' }, { key: 'discharge', label: 'Discharge MW', color: '#f97316' }], reducer: 'mean', allowDonut: true },
      { key: 'state',         label: 'State of charge', unit: 'MWh', rows: su.stateSeries.map((p) => ({ label: p.label, timestamp: p.timestamp, state: p.state })), series: [{ key: 'state', label: 'State MWh', color: '#14b8a6' }], reducer: 'mean', allowDonut: false },
    ];
  }
  if (focus.type === 'store') {
    const st = assetDetails.stores[focus.key];
    if (!st) return [];
    return [
      { key: 'energy', label: 'Energy', unit: 'MWh', rows: st.energySeries.map((p) => ({ label: p.label, timestamp: p.timestamp, energy: p.energy })), series: [{ key: 'energy', label: 'Energy MWh', color: '#7c3aed' }], reducer: 'mean', allowDonut: false },
      { key: 'power',  label: 'Power',  unit: 'MW',  rows: st.powerSeries.map((p)  => ({ label: p.label, timestamp: p.timestamp, power: p.power })),   series: [{ key: 'power',  label: 'Power MW',   color: '#6d28d9' }], reducer: 'mean', allowDonut: false },
    ];
  }
  if (focus.type === 'branch') {
    const br = assetDetails.branches[focus.key];
    if (!br) return [];
    return [
      { key: 'terminal_flows', label: 'Terminal flows', unit: 'MW', rows: br.flowSeries.map((p)    => ({ label: p.label, timestamp: p.timestamp, p0: p.p0, p1: p.p1 })),       series: [{ key: 'p0', label: 'P0 MW', color: '#2563eb' }, { key: 'p1', label: 'P1 MW', color: '#1d4ed8' }], reducer: 'mean', allowDonut: true  },
      { key: 'loading',        label: 'Loading',        unit: '%',  rows: br.loadingSeries.map((p) => ({ label: p.label, timestamp: p.timestamp, loading: p.loading })),         series: [{ key: 'loading', label: 'Loading %',  color: '#ea580c' }], reducer: 'mean', allowDonut: false },
      { key: 'losses',         label: 'Losses',         unit: 'MW', rows: br.lossesSeries.map((p)  => ({ label: p.label, timestamp: p.timestamp, losses: p.losses })),           series: [{ key: 'losses',  label: 'Losses MW', color: '#dc2626' }], reducer: 'mean', allowDonut: false },
    ];
  }
  if (focus.type === 'process') {
    const pr = assetDetails.processes[focus.key];
    if (!pr) return [];
    const c = pr.color || carrierColor(pr.carrier || 'Other');
    return [
      { key: 'throughput',     label: 'Throughput',     unit: 'MW', rows: pr.throughputSeries.map((p) => ({ label: p.label, timestamp: p.timestamp, throughput: p.throughput })), series: [{ key: 'throughput', label: 'Throughput MW', color: c }],                                                          reducer: 'mean', allowDonut: false },
      { key: 'terminal_flows', label: 'Terminal flows', unit: 'MW', rows: pr.p0Series.map((p, i)      => ({ label: p.label, timestamp: p.timestamp, p0: p.p0, p1: pr.p1Series[i]?.p1 ?? 0 })), series: [{ key: 'p0', label: 'P0 MW', color: '#2563eb' }, { key: 'p1', label: 'P1 MW', color: '#1d4ed8' }],  reducer: 'mean', allowDonut: true  },
    ];
  }
  if (focus.type === 'shuntImpedance') {
    const sh = assetDetails.shuntImpedances[focus.key];
    if (!sh) return [];
    return [
      { key: 'active_power',   label: 'Active power',   unit: 'MW',   rows: sh.pSeries.map((p) => ({ label: p.label, timestamp: p.timestamp, p: p.p })), series: [{ key: 'p', label: 'P MW',   color: '#0ea5e9' }], reducer: 'mean', allowDonut: false },
      { key: 'reactive_power', label: 'Reactive power', unit: 'MVar', rows: sh.qSeries.map((p) => ({ label: p.label, timestamp: p.timestamp, q: p.q })), series: [{ key: 'q', label: 'Q MVar', color: '#7c3aed' }], reducer: 'mean', allowDonut: false },
    ];
  }
  return [];
}

// ── Public hook ───────────────────────────────────────────────────────────────

export function useMetricOptions(
  results: RunResults | null,
  _model: WorkbookModel,
  focusType: AnalyticsFocus['type'],
  focusKeys: string[],       // [] = all assets of that type; ['x'] = single
  groupBy: GroupByOption,    // how multi-asset series are combined
  currencySymbol: string = '$',
  busFilter: string[] = [],     // narrow generator/storage/store assets to these buses ([] = all)
  carrierFilter: string[] = [], // narrow generators to these carriers ([] = all)
): MetricOption[] {
  // ── System-level derived rows (always computed, cheap) ──────────────────────
  const rawDispatch  = (results?.dispatchSeries          || []).map(normalizeSeriesPoint);
  const rawGenDisp   = (results?.generatorDispatchSeries || []).map(normalizeSeriesPoint);
  const SKIP         = new Set(['label', 'timestamp', 'total']);
  const hasValues    = (rows: TimeSeriesRow[]) =>
    rows.some((r) => Object.keys(r).some((k) => !SKIP.has(k) && Math.abs(numberValue(r[k] as any)) > 1e-6));

  const sysDispatchRows  = hasValues(rawDispatch)  ? rawDispatch  : buildRowsFromGeneratorDetails(results?.assetDetails.generators || {}, 'carrier');
  const sysGenDispRows   = hasValues(rawGenDisp)   ? rawGenDisp   : buildRowsFromGeneratorDetails(results?.assetDetails.generators || {}, 'generator');
  const rawSysDispKeys   = Array.from(new Set(sysDispatchRows.flatMap((r) => Object.keys(r).filter((k) => !SKIP.has(k)))));
  const sysDispKeys      = orderByCarrierRows(_model.carriers, rawSysDispKeys);
  const sysGenDispKeys   = Array.from(new Set(sysGenDispRows.flatMap((r) => Object.keys(r).filter((k) => !SKIP.has(k)))));
  const sysDispSeries    = sysDispKeys.map((k)    => ({ key: k, label: k, color: carrierColor(k) }));
  const sysGenDispSeries = sysGenDispKeys.map((k) => ({ key: k, label: k, color: results?.assetDetails.generators[k]?.color || hashColor(k) }));
  const sysPriceRows     = (results?.systemPriceSeries     || []).map((p) => ({ label: p.label, timestamp: p.timestamp, price: p.value }));
  const sysEmissionsRows = (results?.systemEmissionsSeries || []).map((p) => ({ label: p.label, timestamp: p.timestamp, emissions: p.value }));
  const storageRows      = (results?.storageSeries         || []).map((p) => ({ label: p.label, timestamp: p.timestamp, charge: p.charge, discharge: p.discharge, state: p.state }));
  const sysLoadRows      = buildSystemLoadRows(results);

  // Stable keys for memoisation of array deps
  const focusKeysSig    = focusKeys.join(',');
  const busFilterSig    = busFilter.join(',');
  const carrierFilterSig = carrierFilter.join(',');

  return useMemo(() => {
    if (!results) return [];

    // ── System ────────────────────────────────────────────────────────────────
    if (focusType === 'system') {
      return [
        { key: 'dispatch',          label: 'Dispatch by carrier',       unit: 'MW',     rows: sysDispatchRows,  series: sysDispSeries,                                                                                                                                           reducer: 'mean', allowDonut: true  },
        { key: 'dispatch_by_gen',   label: 'Dispatch by generator',     unit: 'MW',     rows: sysGenDispRows,   series: sysGenDispSeries,                                                                                                                                        reducer: 'mean', allowDonut: true  },
        { key: 'load',              label: 'Total load',                 unit: 'MW',     rows: sysLoadRows,      series: [{ key: 'load',      label: 'Load MW',         color: '#f97316' }],                                                                                    reducer: 'mean', allowDonut: false },
        { key: 'system_price',      label: 'System marginal price',      unit: `${currencySymbol}/MWh`,  rows: sysPriceRows,     series: [{ key: 'price',     label: `Price ${currencySymbol}/MWh`,     color: '#111827' }],                                                                                    reducer: 'mean', allowDonut: false },
        { key: 'system_emissions',  label: 'System emissions',           unit: 'tCO2e',  rows: sysEmissionsRows, series: [{ key: 'emissions', label: 'Emissions tCO2e', color: '#16a34a' }],                                                                                    reducer: 'sum',  allowDonut: false },
        { key: 'storage_power',     label: 'Storage power',              unit: 'MW',     rows: storageRows,      series: [{ key: 'charge',    label: 'Charge MW',       color: '#0ea5e9' }, { key: 'discharge', label: 'Discharge MW', color: '#f97316' }],                    reducer: 'mean', allowDonut: true  },
        { key: 'storage_state',     label: 'Storage state of charge',    unit: 'MWh',    rows: storageRows,      series: [{ key: 'state',     label: 'State of charge', color: '#14b8a6' }],                                                                                    reducer: 'mean', allowDonut: false },
      ];
    }

    const isMulti = focusKeys.length !== 1;

    // ── Single asset ──────────────────────────────────────────────────────────
    if (!isMulti) {
      // Single-asset selection ignores bus/carrier filters by design.
      return buildSingleAssetOptions(results.assetDetails, { type: focusType, key: focusKeys[0] } as AnalyticsFocus, currencySymbol);
    }

    // ── Multi / All ───────────────────────────────────────────────────────────
    // Resolve "all" (empty array) to every key present in results
    const allKeys = (() => {
      switch (focusType) {
        case 'generator':   return Object.keys(results.assetDetails.generators);
        case 'bus':         return Object.keys(results.assetDetails.buses);
        case 'storageUnit': return Object.keys(results.assetDetails.storageUnits);
        case 'store':       return Object.keys(results.assetDetails.stores);
        case 'branch':      return Object.keys(results.assetDetails.branches);
        case 'process':     return Object.keys(results.assetDetails.processes);
        case 'shuntImpedance': return Object.keys(results.assetDetails.shuntImpedances);
        default:            return [];
      }
    })();
    const resolved = focusKeys.length === 0 ? allKeys : focusKeys;

    const busSet     = new Set(busFilter);
    const carrierSet = new Set(carrierFilter);

    if (focusType === 'generator') {
      const filtered = resolved.filter((name) => {
        const g = results.assetDetails.generators[name];
        if (!g) return false;
        if (busSet.size     > 0 && !busSet.has(g.bus))         return false;
        if (carrierSet.size > 0 && !carrierSet.has(g.carrier)) return false;
        return true;
      });
      return buildMultiGenOptions(results.assetDetails, filtered, groupBy, _model);
    }

    if (focusType === 'storageUnit') {
      const filtered = busSet.size > 0
        ? resolved.filter((n) => busSet.has(results.assetDetails.storageUnits[n]?.bus ?? ''))
        : resolved;
      return buildMultiAssetOptions(results.assetDetails, filtered, focusType, currencySymbol);
    }

    if (focusType === 'store') {
      const filtered = busSet.size > 0
        ? resolved.filter((n) => busSet.has(results.assetDetails.stores[n]?.bus ?? ''))
        : resolved;
      return buildMultiAssetOptions(results.assetDetails, filtered, focusType, currencySymbol);
    }

    if (focusType === 'bus') {
      // Built-in per-bus metrics (load/gen/smp/emissions/voltage)
      const baseOptions = buildMultiAssetOptions(results.assetDetails, resolved, focusType, currencySymbol);

      // Generator-derived metrics aggregated over generators attached to the selected buses.
      const busNameSet = new Set(resolved);
      const matchingGenerators = Object.values(results.assetDetails.generators).filter(
        (g) => busNameSet.has(g.bus),
      );
      const genFields: Array<{ key: string; label: string; unit: string; field: 'output' | 'available' | 'curtailment' | 'emissions'; reducer: MetricOption['reducer'] }> = [
        { key: 'gen_output_by_bus',       label: 'Generator output',       unit: 'MW',    field: 'output',      reducer: 'mean' },
        { key: 'gen_available_by_bus',    label: 'Generator available',    unit: 'MW',    field: 'available',   reducer: 'mean' },
        { key: 'gen_curtailment_by_bus',  label: 'Generator curtailment',  unit: 'MW',    field: 'curtailment', reducer: 'mean' },
        { key: 'gen_emissions_by_bus',    label: 'Generator emissions',    unit: 'tCO2e', field: 'emissions',   reducer: 'sum'  },
      ];
      const genMetrics: MetricOption[] = genFields.map(({ key, label, unit, field, reducer }) => {
        const byTimestamp = new Map<string, { label: string; timestamp: string; vals: Record<string, number> }>();
        for (const gen of matchingGenerators) {
          const seriesKey = groupBy === 'carrier' ? (gen.carrier || 'Unknown') : gen.name;
          const series =
            field === 'output'      ? gen.outputSeries :
            field === 'available'   ? gen.availableSeries :
            field === 'curtailment' ? gen.curtailmentSeries :
                                      gen.emissionsSeries;
          for (const pt of series) {
            const ts  = String((pt as any).timestamp ?? pt.label);
            const val = Number((pt as any)[field] ?? 0);
            if (!byTimestamp.has(ts)) {
              byTimestamp.set(ts, { label: String(pt.label), timestamp: ts, vals: {} });
            }
            const e = byTimestamp.get(ts)!;
            e.vals[seriesKey] = (e.vals[seriesKey] || 0) + val;
          }
        }
        const rawSeriesKeys = Array.from(
          new Set(Array.from(byTimestamp.values()).flatMap((e) => Object.keys(e.vals))),
        );
        const seriesKeys = groupBy === 'carrier' ? orderByCarrierRows(_model.carriers, rawSeriesKeys) : rawSeriesKeys;
        const rows: TimeSeriesRow[] = Array.from(byTimestamp.values())
          .sort((a, b) => a.timestamp.localeCompare(b.timestamp))
          .map((e) => ({ label: e.label, timestamp: e.timestamp, ...e.vals }));
        const series: TimeSeriesSeries[] = seriesKeys.map((k) => ({
          key: k,
          label: k,
          color: groupBy === 'carrier'
            ? carrierColor(k)
            : (results.assetDetails.generators[k]?.color || hashColor(k)),
        }));
        return { key, label, unit, rows, series, reducer, allowDonut: groupBy === 'carrier' };
      });
      return [...baseOptions, ...genMetrics];
    }

    // Branch falls through here — merge by asset name, no bus filter.
    return buildMultiAssetOptions(results.assetDetails, resolved, focusType, currencySymbol);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [results, focusType, focusKeysSig, groupBy, busFilterSig, carrierFilterSig, currencySymbol,
      sysDispatchRows, sysDispSeries, sysGenDispRows, sysGenDispSeries,
      sysLoadRows, sysPriceRows, sysEmissionsRows, storageRows]);
}
