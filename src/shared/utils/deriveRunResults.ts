/**
 * Derive a full `RunResults` object on the frontend from `(model, outputs)`.
 *
 * Currently used by the project-import path so an imported workbook restores
 * the Result / Analytics tabs immediately without a fresh solve. The math
 * mirrors `backend/lib/results/__init__.py:run_pypsa` post-solve aggregation.
 *
 * No backend round-trip is needed — the imported workbook already contains
 * every output attribute the backend produced.
 */
import {
  CarrierEmission,
  Co2Shadow,
  ExpansionAsset,
  GeneratorEmission,
  GridRow,
  MeritOrderEntry,
  MixItem,
  PlanningMode,
  Primitive,
  PathwayPeriodSummary,
  RunResults,
  SeriesPoint,
  StoragePoint,
  SummaryItem,
  ValuePoint,
  WorkbookModel,
} from '../types';
import { carrierColor, numberValue, resolvedColor, stringValue } from './helpers';
import { deriveAssetDetails } from './deriveAssetDetails';

export interface DeriveRunResultsOptions {
  carbonPrice?: number;
  currencySymbol?: string;
  discountRate?: number;
  snapshotWeight?: number;
  narrative?: string[];
  selectedPeriod?: number | null;
  pathway?: RunResults['pathway'] | null;
  rolling?: RunResults['rolling'] | null;
}

type SeriesMap = NonNullable<RunResults['outputs']>['series'];
type StaticMap = NonNullable<RunResults['outputs']>['static'];

// ── Helpers ─────────────────────────────────────────────────────────────────

function indexByName(rows: GridRow[] | undefined): Record<string, GridRow> {
  const out: Record<string, GridRow> = {};
  (rows ?? []).forEach((row) => {
    const name = stringValue(row.name);
    if (name) out[name] = row;
  });
  return out;
}

function isoToLabel(iso: string): string {
  const t = iso.indexOf('T');
  if (t < 0 || iso.length < t + 6) return iso;
  return iso.slice(t + 1, t + 6);
}

function pickSnapshots(series: SeriesMap): string[] {
  for (const key of ['generators-p', 'buses-marginal_price', 'storage_units-p', 'stores-p']) {
    const rows = series[key];
    if (rows && rows.length) return rows.map((r) => stringValue(r.snapshot));
  }
  for (const rows of Object.values(series)) {
    if (rows && rows.length) return rows.map((r) => stringValue(r.snapshot));
  }
  return [];
}

function detectPeriods(series: SeriesMap): number[] {
  const found = new Set<number>();
  for (const rows of Object.values(series)) {
    for (const row of rows ?? []) {
      const raw = row.period;
      if (typeof raw === 'number' && Number.isFinite(raw)) found.add(raw);
      else if (typeof raw === 'string' && raw.trim() !== '') {
        const parsed = Number(raw);
        if (Number.isFinite(parsed)) found.add(parsed);
      }
    }
  }
  return Array.from(found).sort((left, right) => left - right);
}

function filterSeriesByPeriod(series: SeriesMap, period: number | null): SeriesMap {
  if (period === null) return series;
  const filtered: SeriesMap = {};
  Object.entries(series).forEach(([sheet, rows]) => {
    filtered[sheet] = (rows ?? []).filter((row) => numberValue(row.period) === period);
  });
  return filtered;
}

function seriesValueAt(rows: GridRow[] | undefined, i: number, col: string): number {
  if (!rows || i >= rows.length) return 0;
  return numberValue(rows[i]?.[col]);
}

function staticOutValue(
  staticMap: StaticMap, sheet: string, name: string, attr: string, fallback: number,
): number {
  const v = staticMap[sheet]?.[name]?.[attr];
  if (v === undefined || v === null || v === '') return fallback;
  return numberValue(v as Primitive);
}

// PyPSA's canonical time-index column. All temporal data is canonicalised to
// this single column name + ISO-`T` values on entry (see
// `canonicalizeTemporalSheets` in workbook.ts), so matching here is exact —
// no format-tolerance band-aid.
const SNAPSHOT_COL = 'snapshot';

interface InputTemporalIndex {
  /** Rows keyed by canonical ISO snapshot timestamp. */
  byStamp: Record<string, GridRow>;
  /** Component names that have a column in the temporal sheet. */
  columns: Set<string>;
}

/**
 * Build a timestamp → row lookup from an input temporal sheet so values can be
 * read by snapshot timestamp instead of by position. Positional indexing breaks
 * once outputs are filtered to a non-first investment period, because the input
 * sheet still holds every period's rows in order. Also records which component
 * columns are present so the temporal series can win over the static scalar.
 */
function indexInputByTimestamp(rows: GridRow[] | undefined): InputTemporalIndex {
  const byStamp: Record<string, GridRow> = {};
  const columns = new Set<string>();
  if (!rows || rows.length === 0 || !(SNAPSHOT_COL in rows[0])) return { byStamp, columns };
  for (const key of Object.keys(rows[0])) {
    if (key !== SNAPSHOT_COL && key !== 'period') columns.add(key);
  }
  for (const row of rows) {
    const stamp = stringValue(row[SNAPSHOT_COL]);
    if (stamp) byStamp[stamp] = row;
  }
  return { byStamp, columns };
}

/**
 * Resolve a component's value at a snapshot. The temporal series wins over the
 * static scalar whenever the component has a column in the time-series sheet —
 * matching PyPSA's convention that `loads_t.p_set` overrides `loads.p_set`.
 * The static `fallback` is used only for components absent from the temporal
 * sheet entirely. Timestamps match exactly (both sides are canonical ISO-`T`).
 */
function inputSeriesValueAtStamp(
  idx: InputTemporalIndex, stamp: string, col: string, fallback: number,
): number {
  if (!idx.columns.has(col)) return fallback;
  const row = idx.byStamp[stamp];
  const cell = row?.[col];
  if (cell === undefined || cell === null || cell === '') return 0;
  return numberValue(cell);
}

function fmt(n: number, digits = 0): string {
  return n.toLocaleString(undefined, { maximumFractionDigits: digits });
}

/** Annuity factor — same formula as backend `annuity_factor(rate, lifetime)`. */
function annuityFactor(rate: number, lifetime: number): number {
  if (lifetime <= 0) return 1;
  if (rate <= 0) return 1 / lifetime;
  return rate / (1 - Math.pow(1 + rate, -lifetime));
}

// ── Main entry ──────────────────────────────────────────────────────────────

export function deriveRunResults(
  model: WorkbookModel,
  outputs: NonNullable<RunResults['outputs']>,
  options: DeriveRunResultsOptions = {},
): RunResults {
  const {
    carbonPrice = 0,
    currencySymbol = '$',
    discountRate = 0.05,
    snapshotWeight: weightHint,
    narrative = ['Imported project. Outputs restored from workbook — no fresh solve.'],
    selectedPeriod = null,
    pathway = null,
    rolling = null,
  } = options;

  const detectedPeriods = detectPeriods(outputs.series);
  const activePeriod =
    detectedPeriods.length > 0
      ? (selectedPeriod !== null && detectedPeriods.includes(selectedPeriod) ? selectedPeriod : detectedPeriods[0])
      : null;
  const visibleSeries = filterSeriesByPeriod(outputs.series, activePeriod);
  const visibleOutputs = { ...outputs, series: visibleSeries };
  const snapshots = pickSnapshots(visibleOutputs.series);
  const labels = snapshots.map(isoToLabel);
  const W = weightHint ?? 1;

  const genStatic = indexByName(model.generators);
  const storageStatic = indexByName(model.storage_units);
  const loadStatic = indexByName(model.loads);
  const busStatic = indexByName(model.buses);
  const carrierStatic = indexByName(model.carriers);
  const linesStatic = indexByName(model.lines);
  const linksStatic = indexByName(model.links);
  const transformersStatic = indexByName(model.transformers);

  const pGen = visibleOutputs.series['generators-p'];
  const pStore = visibleOutputs.series['storage_units-p'];
  const socStore = visibleOutputs.series['storage_units-state_of_charge'];
  const priceBus = visibleOutputs.series['buses-marginal_price'];
  const loadInputTs = model['loads-p_set'];
  const loadInputByStamp = indexInputByTimestamp(loadInputTs);

  const generators = Object.keys(genStatic);
  const storageUnits = Object.keys(storageStatic);
  const buses = Object.keys(busStatic);

  // Per-generator metadata
  const genCarrier: Record<string, string> = {};
  const genEf: Record<string, number> = {};
  const genBus: Record<string, string> = {};
  const genMc: Record<string, number> = {};
  for (const name of generators) {
    const row = genStatic[name];
    const carrier = stringValue(row.carrier) || 'Other';
    genCarrier[name] = carrier;
    genBus[name] = stringValue(row.bus);
    genMc[name] = numberValue(row.marginal_cost);
    genEf[name] = numberValue(carrierStatic[carrier]?.co2_emissions);
  }

  // ── Dispatch by carrier and load profile per snapshot ─────────────────────
  const carrierDispatch: Record<string, number[]> = {};
  const generatorDispatch: Record<string, number[]> = {};
  const loadPerSnapshot: number[] = new Array(snapshots.length).fill(0);
  const emissionsPerSnapshot: number[] = new Array(snapshots.length).fill(0);

  for (const name of generators) {
    const carrier = genCarrier[name];
    const ef = genEf[name];
    const arr: number[] = new Array(snapshots.length).fill(0);
    generatorDispatch[name] = arr;
    if (!carrierDispatch[carrier]) carrierDispatch[carrier] = new Array(snapshots.length).fill(0);
    for (let i = 0; i < snapshots.length; i++) {
      const v = seriesValueAt(pGen, i, name);
      arr[i] = v;
      const pos = Math.max(v, 0);
      carrierDispatch[carrier][i] += pos;
      emissionsPerSnapshot[i] += pos * ef;
    }
  }
  // Add storage discharge contribution to dispatch series under its carrier
  for (const name of storageUnits) {
    const row = storageStatic[name];
    const carrier = stringValue(row.carrier) || 'Storage';
    if (!carrierDispatch[carrier]) carrierDispatch[carrier] = new Array(snapshots.length).fill(0);
    for (let i = 0; i < snapshots.length; i++) {
      const v = seriesValueAt(pStore, i, name);
      // Backend includes both directions in dispatch_frame — but discharge
      // (positive) shows as supply on the carrier-stacked chart.
      if (v > 0) carrierDispatch[carrier][i] += v;
    }
  }

  for (let i = 0; i < snapshots.length; i++) {
    let total = 0;
    for (const ln of Object.keys(loadStatic)) {
      total += inputSeriesValueAtStamp(
        loadInputByStamp, snapshots[i], ln, numberValue(loadStatic[ln].p_set),
      );
    }
    loadPerSnapshot[i] = total;
  }

  // ── Time series outputs ───────────────────────────────────────────────────
  const dispatchSeries: SeriesPoint[] = [];
  const generatorDispatchSeries: SeriesPoint[] = [];
  const systemPriceSeries: ValuePoint[] = [];
  const systemEmissionsSeries: ValuePoint[] = [];
  const nodalPriceSeries: SeriesPoint[] = [];

  for (let i = 0; i < snapshots.length; i++) {
    const carrierValues: Record<string, number> = {};
    for (const [c, arr] of Object.entries(carrierDispatch)) {
      if (Math.abs(arr[i]) > 1e-6) carrierValues[c] = arr[i];
    }
    dispatchSeries.push({
      label: labels[i], timestamp: snapshots[i],
      values: carrierValues, total: loadPerSnapshot[i],
    });

    const genValues: Record<string, number> = {};
    for (const [name, arr] of Object.entries(generatorDispatch)) {
      const pos = Math.max(arr[i], 0);
      if (pos > 1e-6) genValues[name] = pos;
    }
    generatorDispatchSeries.push({
      label: labels[i], timestamp: snapshots[i],
      values: genValues, total: loadPerSnapshot[i],
    });

    let priceSum = 0;
    let priceCount = 0;
    const nodalPrices: Record<string, number> = {};
    for (const bus of buses) {
      const p = seriesValueAt(priceBus, i, bus);
      nodalPrices[bus] = Math.round(p * 100) / 100;
      priceSum += p;
      priceCount += 1;
    }
    const meanPrice = priceCount ? priceSum / priceCount : 0;
    systemPriceSeries.push({ label: labels[i], timestamp: snapshots[i], value: meanPrice });
    systemEmissionsSeries.push({ label: labels[i], timestamp: snapshots[i], value: emissionsPerSnapshot[i] });
    if (priceBus) {
      nodalPriceSeries.push({ label: labels[i], timestamp: snapshots[i], values: nodalPrices });
    }
  }

  // ── Storage system series ─────────────────────────────────────────────────
  // Aggregate-then-derive: sum raw p across all storage units per snapshot,
  // then split the aggregate into charge/discharge. SOC is summed directly.
  // Backend build_storage_series uses the same aggregate-then-derive convention.
  const storageSeries: StoragePoint[] = [];
  if (storageUnits.length > 0) {
    for (let i = 0; i < snapshots.length; i++) {
      let sumP = 0;
      let state = 0;
      for (const unit of storageUnits) {
        sumP += seriesValueAt(pStore, i, unit);
        state += seriesValueAt(socStore, i, unit);
      }
      const charge = Math.abs(Math.min(sumP, 0));
      const discharge = Math.max(sumP, 0);
      storageSeries.push({
        label: labels[i], timestamp: snapshots[i], charge, discharge, state,
      });
    }
  } else {
    for (let i = 0; i < snapshots.length; i++) {
      storageSeries.push({
        label: labels[i], timestamp: snapshots[i], charge: 0, discharge: 0, state: 0,
      });
    }
  }

  // ── Carrier mix (weighted energy) ─────────────────────────────────────────
  const carrierEnergy: Record<string, number> = {};
  for (const [c, arr] of Object.entries(carrierDispatch)) {
    let sum = 0;
    for (let i = 0; i < snapshots.length; i++) sum += arr[i] * W;
    if (sum > 0) carrierEnergy[c] = sum;
  }
  const carrierMix: MixItem[] = Object.entries(carrierEnergy)
    .sort((a, b) => b[1] - a[1])
    .map(([c, v]) => ({ label: c, value: v, color: carrierColor(c) }));

  // ── Cost breakdown (fuel + carbon + load shedding + capex) ────────────────
  let fuelCost = 0;
  let carbonCost = 0;
  let shedCost = 0;
  for (const name of generators) {
    const arr = generatorDispatch[name];
    let energyMWh = 0;
    for (let i = 0; i < snapshots.length; i++) energyMWh += Math.max(arr[i], 0) * W;
    const ef = genEf[name];
    const mc = genMc[name];
    const carbonComponent = energyMWh * ef * carbonPrice;
    const fuelComponent = energyMWh * Math.max(0, mc - ef * carbonPrice);
    if (name.startsWith('load_shedding_')) {
      shedCost += energyMWh * mc;
    } else {
      fuelCost += fuelComponent;
      carbonCost += carbonComponent;
    }
  }

  // ── Expansion results ─────────────────────────────────────────────────────
  const expansionResults: ExpansionAsset[] = [];
  const annualisedCapex = (capCost: number, lifetime: number) =>
    capCost * annuityFactor(discountRate, lifetime > 0 ? lifetime : 20);

  function pushExpansion(
    rows: GridRow[] | undefined,
    component: ExpansionAsset['component'],
    capAttr: 'p_nom' | 's_nom' | 'e_nom',
    extAttr: string,
    sheet: string,
    busAttr: 'bus' | 'bus0',
    unit?: ExpansionAsset['unit'],
  ) {
    for (const row of rows ?? []) {
      if (String(row[extAttr] ?? '').toLowerCase() !== 'true' && row[extAttr] !== true) continue;
      const name = stringValue(row.name);
      if (!name) continue;
      const inputCap = numberValue(row[capAttr]);
      const optCap = staticOutValue(outputs.static, sheet, name, `${capAttr}_opt`, inputCap);
      const rawCC = numberValue(row.capital_cost);
      const lifetime = numberValue(row.lifetime) || 20;
      const annualCC = annualisedCapex(rawCC, lifetime);
      expansionResults.push({
        name,
        component,
        carrier: stringValue(row.carrier),
        bus: stringValue(row[busAttr]),
        p_nom_mw: Math.round(inputCap * 10) / 10,
        p_nom_opt_mw: Math.round(optCap * 10) / 10,
        delta_mw: Math.round((optCap - inputCap) * 10) / 10,
        capital_cost: Math.round(annualCC * 100) / 100,
        capex_annual: Math.round(annualCC * optCap),
        unit,
      });
    }
  }

  pushExpansion(model.generators, 'Generator', 'p_nom', 'p_nom_extendable', 'generators', 'bus');
  pushExpansion(model.storage_units, 'StorageUnit', 'p_nom', 'p_nom_extendable', 'storage_units', 'bus');
  pushExpansion(model.stores, 'Store', 'e_nom', 'e_nom_extendable', 'stores', 'bus', 'MWh');
  pushExpansion(model.links, 'Link', 'p_nom', 'p_nom_extendable', 'links', 'bus0');
  pushExpansion(model.lines, 'Line', 's_nom', 's_nom_extendable', 'lines', 'bus0', 'MVA');
  const totalCapex = expansionResults.reduce((s, e) => s + e.capex_annual, 0);

  const costBreakdown: Array<{ label: string; value: number }> = [
    { label: 'Fuel cost', value: Math.round(fuelCost) },
    { label: 'Carbon cost', value: Math.round(carbonCost) },
    { label: 'Load shedding', value: Math.round(shedCost) },
  ];
  if (totalCapex > 0) costBreakdown.push({ label: 'Capital cost', value: Math.round(totalCapex) });

  // ── Nodal balance ─────────────────────────────────────────────────────────
  const nodalBalance: Array<{ label: string; load: number; generation: number }> = [];
  const loadsByBus: Record<string, string[]> = {};
  const gensByBus: Record<string, string[]> = {};
  for (const ln of Object.keys(loadStatic)) {
    const b = stringValue(loadStatic[ln].bus);
    if (!b) continue;
    (loadsByBus[b] ??= []).push(ln);
  }
  for (const gn of generators) {
    const b = genBus[gn];
    if (!b) continue;
    (gensByBus[b] ??= []).push(gn);
  }
  for (const bus of buses) {
    let lSum = 0;
    let gSum = 0;
    let lCount = 0;
    let gCount = 0;
    for (let i = 0; i < snapshots.length; i++) {
      let lT = 0;
      for (const ln of loadsByBus[bus] ?? []) {
        lT += inputSeriesValueAtStamp(
          loadInputByStamp, snapshots[i], ln, numberValue(loadStatic[ln]?.p_set),
        );
      }
      let gT = 0;
      for (const gn of gensByBus[bus] ?? []) gT += Math.max(generatorDispatch[gn][i], 0);
      lSum += lT;
      gSum += gT;
      lCount += 1;
      gCount += 1;
    }
    nodalBalance.push({
      label: bus,
      load: lCount ? lSum / lCount : 0,
      generation: gCount ? gSum / gCount : 0,
    });
  }
  nodalBalance.sort((a, b) => b.load - a.load);

  // ── Line loading ──────────────────────────────────────────────────────────
  const lineLoading: Array<{ label: string; value: number }> = [];
  function pushBranchLoading(
    rows: Record<string, GridRow>, capAttr: 's_nom' | 'p_nom', p0Sheet: string,
    staticSheet: string,
  ) {
    const p0 = outputs.series[p0Sheet];
    if (!p0) return;
    for (const name of Object.keys(rows)) {
      // Use optimised capacity when available (extendable lines after solve),
      // otherwise fall back to the input nominal rating.
      const inputCap = numberValue(rows[name][capAttr]);
      const cap = staticOutValue(outputs.static, staticSheet, name, `${capAttr}_opt`, inputCap);
      if (cap <= 0) continue;   // skip lines with no capacity (avoids ÷0 noise)
      let peak = 0;
      for (let i = 0; i < snapshots.length; i++) {
        peak = Math.max(peak, (Math.abs(seriesValueAt(p0, i, name)) / cap) * 100);
      }
      lineLoading.push({ label: name, value: peak });
    }
  }
  pushBranchLoading(linesStatic, 's_nom', 'lines-p0', 'lines');
  pushBranchLoading(linksStatic, 'p_nom', 'links-p0', 'links');
  pushBranchLoading(transformersStatic, 's_nom', 'transformers-p0', 'transformers');

  // ── Merit order ───────────────────────────────────────────────────────────
  const SYSTEM_PREFIXES = ['load_shedding_', 'system_bess'];
  const meritOrder: MeritOrderEntry[] = [];
  for (const name of generators) {
    if (SYSTEM_PREFIXES.some((p) => name.startsWith(p))) continue;
    const row = genStatic[name];
    const isExt = row.p_nom_extendable === true ||
      String(row.p_nom_extendable ?? '').toLowerCase() === 'true';
    const inputCap = numberValue(row.p_nom);
    const pNom = isExt
      ? staticOutValue(outputs.static, 'generators', name, 'p_nom_opt', inputCap)
      : inputCap;
    if (pNom <= 0) continue;
    meritOrder.push({
      name,
      carrier: genCarrier[name],
      bus: genBus[name],
      marginal_cost: Math.round(genMc[name] * 100) / 100,
      p_nom: Math.round(pNom * 10) / 10,
      cumulative_mw: 0,
      color: resolvedColor(row.color, row.carrier),
    });
  }
  meritOrder.sort((a, b) => a.marginal_cost - b.marginal_cost || a.name.localeCompare(b.name));
  let cum = 0;
  for (const r of meritOrder) {
    r.cumulative_mw = Math.round(cum * 10) / 10;
    cum += r.p_nom;
  }

  // ── Emissions breakdown ───────────────────────────────────────────────────
  const byGenerator: GeneratorEmission[] = [];
  const carrierEnergyMap: Record<string, number> = {};
  const carrierEmissionsMap: Record<string, number> = {};
  for (const name of generators) {
    if (name.startsWith('load_shedding_')) continue;
    const arr = generatorDispatch[name];
    let energyMWh = 0;
    for (let i = 0; i < snapshots.length; i++) energyMWh += Math.max(arr[i], 0) * W;
    const carrier = genCarrier[name];
    const ef = genEf[name];
    const emissions = energyMWh * ef;
    byGenerator.push({
      name, carrier, bus: genBus[name],
      energy_mwh: Math.round(energyMWh * 10) / 10,
      emissions_tco2: Math.round(emissions * 100) / 100,
      intensity_kg_mwh: Math.round(ef * 1000 * 10) / 10,
    });
    carrierEnergyMap[carrier] = (carrierEnergyMap[carrier] ?? 0) + energyMWh;
    carrierEmissionsMap[carrier] = (carrierEmissionsMap[carrier] ?? 0) + emissions;
  }
  byGenerator.sort((a, b) => b.emissions_tco2 - a.emissions_tco2);
  const byCarrier: CarrierEmission[] = Object.entries(carrierEnergyMap)
    .filter(([, e]) => e > 0)
    .sort((a, b) => b[1] - a[1])
    .map(([carrier, energy_mwh]) => {
      const ems = carrierEmissionsMap[carrier] ?? 0;
      return {
        carrier,
        energy_mwh: Math.round(energy_mwh * 10) / 10,
        emissions_tco2: Math.round(ems * 100) / 100,
        intensity_kg_mwh: energy_mwh > 0 ? Math.round((ems / energy_mwh) * 1000 * 10) / 10 : 0,
      };
    });

  // ── Summary cards ─────────────────────────────────────────────────────────
  let totalCap = 0;
  for (const n of generators) totalCap += numberValue(genStatic[n].p_nom);
  for (const n of storageUnits) totalCap += numberValue(storageStatic[n].p_nom);
  const peakLoad = loadPerSnapshot.reduce((m, v) => (v > m ? v : m), 0);
  const avgPrice = systemPriceSeries.length
    ? systemPriceSeries.reduce((s, p) => s + p.value, 0) / systemPriceSeries.length
    : 0;
  const peakPrice = systemPriceSeries.length
    ? systemPriceSeries.reduce((m, p) => (p.value > m ? p.value : m), -Infinity)
    : 0;
  const totalEmissionsKt =
    Object.values(carrierEmissionsMap).reduce((a, b) => a + b, 0) / 1000;
  const avgLoading = lineLoading.length
    ? lineLoading.reduce((s, x) => s + x.value, 0) / lineLoading.length : 0;
  const stressedCount = lineLoading.filter((x) => x.value > 80).length;

  const summary: SummaryItem[] = [
    { label: 'Installed capacity', value: `${fmt(totalCap)} MW`,
      detail: `${generators.length} generators + ${storageUnits.length} storage units` },
    { label: 'Peak demand', value: `${fmt(peakLoad)} MW`, detail: 'from workbook load profile' },
    { label: 'Reserve position', value: `${fmt(totalCap - peakLoad)} MW`,
      detail: 'installed capacity vs peak demand' },
    { label: 'Peak price', value: `${fmt(peakPrice)} ${currencySymbol}/MWh`,
      detail: `${fmt(peakLoad)} MW peak load` },
    { label: 'System emissions', value: `${fmt(totalEmissionsKt)} ktCO2e`,
      detail: `Carbon price ${fmt(carbonPrice)} ${currencySymbol}/t` },
    { label: 'Transmission stress', value: `${fmt(avgLoading)}%`,
      detail: `${stressedCount} corridors above 80%` },
  ];
  void avgPrice;   // kept in case a future card uses it

  // ── CO₂ shadow: not derivable from outputs (needs constraint duals) ──────
  const co2Shadow: Co2Shadow = {
    found: false,
    constraint_name: null,
    shadow_price: 0,
    explicit_price: Math.round(carbonPrice * 100) / 100,
    cap_ktco2: null,
    status: 'none',
    note: 'Imported project — CO₂ shadow price is only available from a fresh solve.',
  };

  // ── Asset details (reuse existing deriver) ────────────────────────────────
  const assetDetails = deriveAssetDetails(model, visibleOutputs, currencySymbol, W);

  const pathwayPeriods = pathway?.periods?.length ? pathway.periods : detectedPeriods;
  const pathwaySummaries: PathwayPeriodSummary[] =
    pathway?.summaries?.length
      ? pathway.summaries
      : pathwayPeriods.map((period) => {
        const periodSeries = filterSeriesByPeriod(outputs.series, period);
        const periodSnapshots = pickSnapshots(periodSeries);
        const periodPGen = periodSeries['generators-p'];
        const periodPStore = periodSeries['storage_units-p'];
        const periodPriceBus = periodSeries['buses-marginal_price'];
        const loadByStamp = indexInputByTimestamp(model['loads-p_set']);
        let totalDispatch = 0;
        let totalEmissions = 0;
        let peakLoad = 0;
        let priceSum = 0;
        let priceCount = 0;
        for (let i = 0; i < periodSnapshots.length; i++) {
          let loadAtT = 0;
          for (const ln of Object.keys(loadStatic)) {
            loadAtT += inputSeriesValueAtStamp(
              loadByStamp, periodSnapshots[i], ln, numberValue(loadStatic[ln].p_set),
            );
          }
          peakLoad = Math.max(peakLoad, loadAtT);
          let dispatchAtT = 0;
          for (const name of generators) {
            const value = Math.max(seriesValueAt(periodPGen, i, name), 0);
            dispatchAtT += value;
            totalEmissions += value * genEf[name] * W;
          }
          for (const name of storageUnits) {
            const value = Math.max(seriesValueAt(periodPStore, i, name), 0);
            dispatchAtT += value;
          }
          totalDispatch += dispatchAtT * W;
          const prices = buses.map((bus) => seriesValueAt(periodPriceBus, i, bus));
          const avg = prices.length ? prices.reduce((sum, value) => sum + value, 0) / prices.length : 0;
          priceSum += avg;
          priceCount += 1;
        }
        const weighting =
          pathway?.summaries?.find((row) => row.period === period)
          ?? { objectiveWeight: 1, yearsWeight: 1 };
        return {
          period,
          snapshotCount: periodSnapshots.length,
          modeledHours: periodSnapshots.length * W,
          totalDispatch,
          totalEmissions,
          averagePrice: priceCount ? priceSum / priceCount : 0,
          peakLoad,
          objectiveWeight: weighting.objectiveWeight,
          yearsWeight: weighting.yearsWeight,
        };
      });

  // ── runMeta ───────────────────────────────────────────────────────────────
  const planningMode: PlanningMode = pathwayPeriods.length > 0 ? 'pathway' : 'single_period';
  const runMeta = {
    snapshotCount: snapshots.length,
    snapshotWeight: W,
    modeledHours: snapshots.length * W,
    storeWeight: W,
    planningMode,
    investmentPeriods: pathwayPeriods,
    rolling: rolling ? {
      enabled: rolling.enabled,
      horizonSnapshots: rolling.horizonSnapshots,
      overlapSnapshots: rolling.overlapSnapshots,
      stepSnapshots: rolling.stepSnapshots,
      windowCount: rolling.windowCount,
    } : undefined,
  };

  return {
    summary,
    dispatchSeries,
    generatorDispatchSeries,
    systemPriceSeries,
    systemEmissionsSeries,
    storageSeries,
    nodalPriceSeries,
    carrierMix,
    costBreakdown,
    nodalBalance,
    lineLoading,
    expansionResults,
    meritOrder,
    co2Shadow,
    emissionsBreakdown: { byGenerator, byCarrier },
    narrative,
    runMeta,
    pathway: pathwayPeriods.length > 0 ? {
      enabled: true,
      periods: pathwayPeriods,
      selectedPeriod: activePeriod,
      snapshotMappingMode: pathway?.snapshotMappingMode ?? 'explicit_period_column',
      summaries: pathwaySummaries,
    } : undefined,
    assetDetails,
    outputs,
    rolling: rolling ?? undefined,
  };
}
