/**
 * Derive a full `RunResults` object on the frontend from `(model, outputs)`.
 *
 * Currently used by the project-import path so an imported workbook restores
 * the Result / Analytics tabs immediately without a fresh solve. The math
 * mirrors `backend/pypsa/results/__init__.py:run_pypsa` post-solve aggregation.
 *
 * No backend round-trip is needed — the imported workbook already contains
 * every output attribute the backend produced.
 */
import {
  CarbonPriceScheduleEntry,
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
import { carrierColor, numberValue, resolvedColor, stringValue } from 'lib/utils/helpers';
import {
  deriveAssetDetails,
  filterSeriesByPeriod,
  generatorEmissionFactor,
  indexInputByTimestamp,
  inputAveragingFromSampling,
  inputSeriesValueAtStamp,
  snapshotPeriods,
} from 'lib/results/assetDetails';

export interface DeriveRunResultsOptions {
  carbonPrice?: number;
  currencySymbol?: string;
  discountRate?: number;
  snapshotWeight?: number;
  narrative?: string[];
  selectedPeriod?: number | null;
  pathway?: RunResults['pathway'] | null;
  rolling?: RunResults['rolling'] | null;
  /** Year -> price schedule the run solved with; supersedes the scalar
   *  `carbonPrice` exactly like the backend `build_price_series`. */
  carbonPriceSchedule?: CarbonPriceScheduleEntry[] | null;
  /** `runMeta.sampling` of the run (drives averaged-profile input lookups). */
  sampling?: RunResults['runMeta']['sampling'];
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

// Input-sheet timestamp indexing (`indexInputByTimestamp` /
// `inputSeriesValueAtStamp`) lives in assetDetails.ts — single source of
// truth, imported above, so both derivers hit the identical fix for reading
// input time series by snapshot timestamp instead of row position (breaks
// once outputs are filtered to a non-first investment period).

/**
 * Carbon price for one snapshot — mirrors backend `build_price_series`: with a
 * schedule, the latest entry whose year <= the snapshot's year (investment
 * period in pathway runs, else the calendar year of the stamp), the first
 * entry before the schedule starts; the scalar only when there is no schedule.
 */
export function carbonPriceAt(
  scalar: number,
  schedule: CarbonPriceScheduleEntry[] | null | undefined,
  period: number | null,
  stamp: string,
): number {
  const entries = (schedule ?? [])
    .map((row) => ({ year: Number(row.year), price: Number(row.price) }))
    .filter((row) => Number.isFinite(row.year) && row.year > 0 && Number.isFinite(row.price))
    .sort((a, b) => a.year - b.year);
  if (entries.length === 0) return scalar;
  const year = period !== null ? period : Number.parseInt(stamp.slice(0, 4), 10);
  if (!Number.isFinite(year)) return entries[0].price;
  let applicable = entries[0].price;
  for (const entry of entries) if (entry.year <= year) applicable = entry.price;
  return applicable;
}

/** Solved capacity: `<attr>_opt` when > 0, else the input rating (PyPSA leaves
 *  `_opt` at 0 for non-extendable units on some versions). */
function solvedCapacity(
  staticMap: StaticMap, sheet: string, name: string, attr: string, inputCap: number,
): number {
  const opt = staticOutValue(staticMap, sheet, name, `${attr}_opt`, 0);
  return opt > 0 ? opt : inputCap;
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
    carbonPriceSchedule = null,
    sampling = null,
  } = options;

  // The light analytics view ships `series: null` (the heavy per-component
  // output series are stripped and fetched windowed on demand). A result
  // restored from it that lacks server-derived analytics still flows through
  // here — normalise once so EVERY series/static access below (period
  // detection, branch loading, per-period filters, capacity lookups) is
  // null-safe rather than guarding each call site. Missing data simply derives
  // to empty dispatch / mix / loading.
  outputs = { ...outputs, series: outputs.series ?? {}, static: outputs.static ?? {} };

  const detectedPeriods = detectPeriods(outputs.series);
  const activePeriod =
    detectedPeriods.length > 0
      ? (selectedPeriod !== null && detectedPeriods.includes(selectedPeriod) ? selectedPeriod : detectedPeriods[0])
      : null;
  const visibleSeries = filterSeriesByPeriod(outputs.series, activePeriod);
  const visibleOutputs = { ...outputs, series: visibleSeries };
  const snapshots = pickSnapshots(visibleOutputs.series);
  const labels = snapshots.map(isoToLabel);
  const PERIOD_SHEETS = ['generators-p', 'buses-marginal_price', 'storage_units-p', 'stores-p'];
  // Investment period of each visible snapshot — input lookups key by
  // `period|snapshot` so every pathway period reads its own profile.
  const periodOf = snapshotPeriods(visibleOutputs.series, PERIOD_SHEETS);
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
  const averaging = inputAveragingFromSampling(sampling, snapshots[0]);
  const loadInputByStamp = indexInputByTimestamp(loadInputTs, averaging);
  const mcInputByStamp = indexInputByTimestamp(model['generators-marginal_cost']);

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
    // Thermal-basis (fuel) emission factor: carrier co2_emissions / efficiency
    // (M3) — matches the backend Emissions Breakdown card and per-asset
    // detail (assetDetails.ts) so the same run reports the same emissions
    // everywhere in the dashboard, regardless of how the result arrived.
    genEf[name] = generatorEmissionFactor(row, carrierStatic);
  }

  // ── Dispatch by carrier and load profile per snapshot ─────────────────────
  // Carrier-aware for sector coupling (mirrors backend electricity_dispatch_by
  // _carrier): the mix is the ELECTRICITY vector, so only generators on
  // electricity buses count, plus conversion-Link injections into electricity
  // buses under the Link's carrier. A blank bus carrier defaults to electricity.
  const ELEC_CARRIERS = new Set(['', 'ac', 'dc', 'electricity', 'elec', 'power']);
  const isElec = (c: unknown): boolean => {
    const s = String(c ?? '').trim().toLowerCase();
    return s === '' || s === 'nan' || ELEC_CARRIERS.has(s);
  };
  const elecBuses = new Set(buses.filter((b) => isElec(busStatic[b]?.carrier)));
  // System aggregates (demand, price, generator capacity) are scoped to the
  // electricity buses of a sector-coupled model, like the backend
  // `electricity_bus_scope`; null (= every bus) for single-vector models or
  // models with no identifiable electricity bus.
  const elecScope: Set<string> | null =
    elecBuses.size === 0 || elecBuses.size === buses.length ? null : elecBuses;
  const inScope = (bus: string): boolean => elecScope === null || elecScope.has(bus);

  const carrierDispatch: Record<string, number[]> = {};
  // Backend `electricity_dispatch_by_carrier` (the carrierMix source) is
  // generators + conversion-Link injections only — storage discharge is
  // NOT part of the mix (it shows via its own storage series/band).
  // `carrierDispatch` (above) also feeds the dispatch STACK chart, which
  // does show a storage band, so track the mix-only accumulation
  // separately rather than filtering storage back out of carrierDispatch.
  const carrierMixDispatch: Record<string, number[]> = {};
  const generatorDispatch: Record<string, number[]> = {};
  const loadPerSnapshot: number[] = new Array(snapshots.length).fill(0);
  const emissionsPerSnapshot: number[] = new Array(snapshots.length).fill(0);

  for (const name of generators) {
    const carrier = genCarrier[name];
    const ef = genEf[name];
    const onElec = elecBuses.has(genBus[name]);
    const arr: number[] = new Array(snapshots.length).fill(0);
    generatorDispatch[name] = arr;
    if (onElec && !carrierDispatch[carrier]) {
      carrierDispatch[carrier] = new Array(snapshots.length).fill(0);
      carrierMixDispatch[carrier] = new Array(snapshots.length).fill(0);
    }
    for (let i = 0; i < snapshots.length; i++) {
      const v = seriesValueAt(pGen, i, name);
      arr[i] = v;
      const pos = Math.max(v, 0);
      // Fuel-supply generators on non-electricity buses (e.g. gas) are not part
      // of the electricity mix — but they still emit (counted below).
      if (onElec) {
        carrierDispatch[carrier][i] += pos;
        carrierMixDispatch[carrier][i] += pos;
      }
      emissionsPerSnapshot[i] += pos * ef;
    }
  }
  // Add storage discharge contribution to the dispatch STACK only (its own
  // band) — excluded from carrierMixDispatch/carrierMix, matching the
  // backend mix.
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
  // Conversion-Link electricity output (e.g. CCGT gas→elec) under the Link's
  // carrier, using p0 × efficiency. Only links whose input bus is NOT
  // electricity count as supply, so transmission links stay out. Period-
  // filtered like every other series read in this deriver — the unfiltered
  // `outputs.series` here showed period-1 flows regardless of the selected
  // pathway period.
  const pLink = visibleOutputs.series['links-p0'];
  if (pLink) {
    const ports: [string, string][] = [['bus1', 'efficiency'], ['bus2', 'efficiency2'], ['bus3', 'efficiency3']];
    for (const name of Object.keys(linksStatic)) {
      const l = linksStatic[name];
      if (elecBuses.has(stringValue(l.bus0))) continue;
      const carrier = stringValue(l.carrier) || name;
      for (const [busCol, effCol] of ports) {
        const outBus = stringValue(l[busCol]);
        if (!outBus || !elecBuses.has(outBus)) continue;
        const raw = l[effCol];
        const eff = raw !== undefined && raw !== null && raw !== '' ? numberValue(raw) : (busCol === 'bus1' ? 1 : 0);
        if (!eff) continue;
        if (!carrierDispatch[carrier]) carrierDispatch[carrier] = new Array(snapshots.length).fill(0);
        if (!carrierMixDispatch[carrier]) carrierMixDispatch[carrier] = new Array(snapshots.length).fill(0);
        for (let i = 0; i < snapshots.length; i++) {
          const injected = Math.max(seriesValueAt(pLink, i, name), 0) * eff;
          carrierDispatch[carrier][i] += injected;
          carrierMixDispatch[carrier][i] += injected;
        }
      }
    }
  }

  for (let i = 0; i < snapshots.length; i++) {
    let total = 0;
    for (const ln of Object.keys(loadStatic)) {
      if (!inScope(stringValue(loadStatic[ln].bus))) continue;
      total += inputSeriesValueAtStamp(
        loadInputByStamp, snapshots[i], ln, numberValue(loadStatic[ln].p_set), periodOf[i],
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
      if (!inScope(bus)) continue;
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
  // Mirrors backend `build_storage_series`: StorageUnits AND Stores, with charge
  // and discharge split PER UNIT before summing (netting units first understated
  // throughput when one charged while another discharged). State sums
  // `state_of_charge` (StorageUnits) and `e` (Stores); a Store's `p` has the same
  // sign convention (positive = discharge into the bus).
  const storageSeries: StoragePoint[] = [];
  const storeNames = Object.keys(indexByName(model.stores));
  const pStoreP = visibleOutputs.series['stores-p'];
  const eStore = visibleOutputs.series['stores-e'];
  const storageSources: Array<{ names: string[]; p: GridRow[] | undefined; state: GridRow[] | undefined }> = [
    { names: storageUnits, p: pStore, state: socStore },
    { names: storeNames, p: pStoreP, state: eStore },
  ];
  for (let i = 0; i < snapshots.length; i++) {
    let charge = 0;
    let discharge = 0;
    let state = 0;
    for (const src of storageSources) {
      for (const unit of src.names) {
        const p = seriesValueAt(src.p, i, unit);
        charge += Math.abs(Math.min(p, 0));
        discharge += Math.max(p, 0);
        state += seriesValueAt(src.state, i, unit);
      }
    }
    storageSeries.push({ label: labels[i], timestamp: snapshots[i], charge, discharge, state });
  }

  // ── Carrier mix (weighted energy) ─────────────────────────────────────────
  // Built from carrierMixDispatch (generators + conversion-Link injections),
  // NOT carrierDispatch — the backend carrierMix excludes storage discharge
  // (backend/pypsa/results/__init__.py electricity_dispatch_by_carrier), so
  // the derived tile must mean the same thing as the backend one.
  const carrierEnergy: Record<string, number> = {};
  for (const [c, arr] of Object.entries(carrierMixDispatch)) {
    let sum = 0;
    for (let i = 0; i < snapshots.length; i++) sum += arr[i] * W;
    if (sum > 0) carrierEnergy[c] = sum;
  }
  const carrierMix: MixItem[] = Object.entries(carrierEnergy)
    .sort((a, b) => b[1] - a[1])
    .map(([c, v]) => ({ label: c, value: v, color: carrierColor(c) }));

  // ── Cost breakdown (fuel + carbon + load shedding + capex) ────────────────
  // Same split as the backend: fuel = E * marginal_cost (the INPUT cost, which
  // does not contain the carbon adder), carbon = E * ef * carbon price with the
  // price resolved per snapshot (schedule by period / calendar year, else the
  // scalar). Subtracting a scalar carbon term from a cost that never had it
  // understated fuel and ignored the schedule.
  let fuelCost = 0;
  let carbonCost = 0;
  let shedCost = 0;
  const carbonAtSnapshot = snapshots.map(
    (stamp, i) => carbonPriceAt(carbonPrice, carbonPriceSchedule, periodOf[i], stamp),
  );
  for (const name of generators) {
    const arr = generatorDispatch[name];
    const ef = genEf[name];
    const isShed = name.startsWith('load_shedding_');
    for (let i = 0; i < snapshots.length; i++) {
      const energyMWh = Math.max(arr[i], 0) * W;
      if (energyMWh === 0) continue;
      const mc = Math.max(
        0, inputSeriesValueAtStamp(mcInputByStamp, snapshots[i], name, genMc[name], periodOf[i]),
      );
      if (isShed) {
        shedCost += energyMWh * mc;
      } else {
        fuelCost += energyMWh * mc;
        carbonCost += energyMWh * ef * carbonAtSnapshot[i];
      }
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
  // `capex_annual` is a full-year annuity; the other components are window
  // totals, so pro-rate onto the modelled window (x H/8760) like the backend.
  const HOURS_PER_YEAR = 8760;
  const windowHours = snapshots.length * W;
  const totalCapexWindow = windowHours > 0 ? totalCapex * (windowHours / HOURS_PER_YEAR) : totalCapex;

  const costBreakdown: Array<{ label: string; value: number }> = [
    { label: 'Fuel cost', value: Math.round(fuelCost) },
    { label: 'Carbon cost', value: Math.round(carbonCost) },
    { label: 'Load shedding', value: Math.round(shedCost) },
  ];
  if (totalCapex > 0) {
    costBreakdown.push({ label: 'Capital cost (annuity, pro-rated to window)', value: Math.round(totalCapexWindow) });
  }

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
          loadInputByStamp, snapshots[i], ln, numberValue(loadStatic[ln]?.p_set), periodOf[i],
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
    // Period-filtered like every other series read here — the unfiltered
    // `outputs.series` showed period-1 flows regardless of the selected
    // pathway period, so line loading / transmission stress / map colouring
    // never reflected the selected period.
    const p0 = visibleOutputs.series[p0Sheet];
    if (!p0) return;
    for (const name of Object.keys(rows)) {
      // Use optimised capacity when available (extendable lines after solve),
      // otherwise fall back to the input nominal rating.
      const inputCap = numberValue(rows[name][capAttr]);
      const cap = solvedCapacity(outputs.static, staticSheet, name, capAttr, inputCap);
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
  // Generator vs storage capacity (and reserve) reported separately, each as
  // installed nameplate p_nom minus peak demand.
  // Solved capacity (p_nom_opt where > 0, else the input rating); the load-
  // shedding backstop and non-electricity fuel-supply generators are not
  // installed electric capacity.
  let genCap = 0;
  for (const n of generators) {
    if (n.startsWith('load_shedding_') || !inScope(genBus[n])) continue;
    genCap += solvedCapacity(outputs.static, 'generators', n, 'p_nom', numberValue(genStatic[n].p_nom));
  }
  let storCap = 0;
  for (const n of storageUnits) {
    storCap += solvedCapacity(outputs.static, 'storage_units', n, 'p_nom', numberValue(storageStatic[n].p_nom));
  }
  const peakLoad = loadPerSnapshot.reduce((m, v) => (v > m ? v : m), 0);
  const avgPrice = systemPriceSeries.length
    ? systemPriceSeries.reduce((s, p) => s + p.value, 0) / systemPriceSeries.length
    : 0;
  const peakPriceEntry = systemPriceSeries.length
    ? systemPriceSeries.reduce((best, p) => (p.value > best.value ? p : best))
    : null;
  const peakPrice = peakPriceEntry?.value ?? 0;
  const totalEmissionsKt =
    Object.values(carrierEmissionsMap).reduce((a, b) => a + b, 0) / 1000;
  const avgLoading = lineLoading.length
    ? lineLoading.reduce((s, x) => s + x.value, 0) / lineLoading.length : 0;
  const stressedCount = lineLoading.filter((x) => x.value > 80).length;

  const summary: SummaryItem[] = [
    { label: 'Generator capacity', value: `${fmt(genCap)} MW`,
      detail: `${generators.length} generators (installed, solved p_nom_opt)` },
    { label: 'Storage capacity', value: `${fmt(storCap)} MW`,
      detail: `${storageUnits.length} storage units (installed, solved p_nom_opt)` },
    { label: 'Peak demand', value: `${fmt(peakLoad)} MW`, detail: 'from workbook load profile' },
    { label: 'Generator reserve', value: `${fmt(genCap - peakLoad)} MW`,
      detail: 'generator capacity vs peak demand' },
    { label: 'Storage reserve', value: `${fmt(storCap - peakLoad)} MW`,
      detail: 'storage capacity vs peak demand' },
    { label: 'Peak price', value: `${fmt(peakPrice)} ${currencySymbol}/MWh`,
      detail: peakPriceEntry ? `at ${peakPriceEntry.label}` : 'no price series' },
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
        const periodPriceBus = periodSeries['buses-marginal_price'];
        const loadByStamp = indexInputByTimestamp(model['loads-p_set']);   // keyed period|stamp
        let totalDispatch = 0;
        let totalEmissions = 0;
        let peakLoad = 0;
        let priceSum = 0;
        let priceCount = 0;
        for (let i = 0; i < periodSnapshots.length; i++) {
          let loadAtT = 0;
          for (const ln of Object.keys(loadStatic)) {
            if (!inScope(stringValue(loadStatic[ln].bus))) continue;
            loadAtT += inputSeriesValueAtStamp(
              loadByStamp, periodSnapshots[i], ln, numberValue(loadStatic[ln].p_set), period,
            );
          }
          peakLoad = Math.max(peakLoad, loadAtT);
          // Same basis as the backend period summary: real generation only —
          // the load-shedding backstop and storage discharge are not supply
          // (storage energy is recycled generation, shedding is unserved load).
          let dispatchAtT = 0;
          for (const name of generators) {
            if (name.startsWith('load_shedding_')) continue;
            const value = Math.max(seriesValueAt(periodPGen, i, name), 0);
            dispatchAtT += value;
            totalEmissions += value * genEf[name] * W;
          }
          totalDispatch += dispatchAtT * W;
          const prices = buses.filter(inScope).map((bus) => seriesValueAt(periodPriceBus, i, bus));
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
