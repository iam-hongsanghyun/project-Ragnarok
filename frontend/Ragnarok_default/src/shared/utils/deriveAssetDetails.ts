/**
 * Derive per-asset detail records (generators, buses, storage units, stores,
 * branches) on the frontend from the schema-driven backend output cache plus
 * the input workbook.
 *
 * Purpose: keep the backend a stateless solver. After a run, the backend sends
 * `outputs.{static,series}` (the raw PyPSA dataset) and nothing else
 * asset-specific. All UI-friendly aggregations live here, so that imported
 * projects, plugins, and analytics all read from the same in-memory cache.
 */
import {
  BranchDetail,
  BusDetail,
  GeneratorDetail,
  GridRow,
  MixItem,
  ProcessDetail,
  ShuntImpedanceDetail,
  RunResults,
  StorageUnitDetail,
  StoreDetail,
  SummaryItem,
  WorkbookModel,
} from '../types';
import { carrierColor, numberValue, resolvedColor, stringValue } from './helpers';

type SeriesMap = Record<string, GridRow[]>;
type StaticMap = Record<string, Record<string, Record<string, unknown>>>;

interface DeriveInput {
  model: WorkbookModel;
  outputs: NonNullable<RunResults['outputs']>;
  currencySymbol?: string;
  snapshotWeight?: number;
}

export type AssetDetails = RunResults['assetDetails'];

const EMPTY_DETAILS: AssetDetails = {
  generators: {},
  buses: {},
  storageUnits: {},
  stores: {},
  branches: {},
  processes: {},
  shuntImpedances: {},
};

/** Build a `name -> row` index for a static input sheet. */
function indexByName(rows: GridRow[] | undefined): Record<string, GridRow> {
  const out: Record<string, GridRow> = {};
  (rows ?? []).forEach((row) => {
    const name = stringValue(row.name);
    if (name) out[name] = row;
  });
  return out;
}

/** Snapshot label "HH:MM" extracted from an ISO timestamp without TZ shifts. */
function isoToLabel(iso: string): string {
  const t = iso.indexOf('T');
  if (t < 0 || iso.length < t + 6) return iso;
  return iso.slice(t + 1, t + 6);
}

/** Read the snapshot timestamps from any output series sheet (PyPSA-standard
 * `snapshot` index column). */
function pickSnapshots(series: SeriesMap, preferred: string[]): string[] {
  for (const key of preferred) {
    const rows = series[key];
    if (rows && rows.length) return rows.map((r) => stringValue(r.snapshot));
  }
  // Fallback: any non-empty series
  for (const key of Object.keys(series)) {
    const rows = series[key];
    if (rows && rows.length) return rows.map((r) => stringValue(r.snapshot));
  }
  return [];
}

/** Look up a numeric value in an output series sheet at a given snapshot. */
function seriesValue(rows: GridRow[] | undefined, rowIndex: number, column: string): number {
  if (!rows || rowIndex >= rows.length) return 0;
  return numberValue(rows[rowIndex]?.[column]);
}

/** Resolve a static output scalar (e.g. `p_nom_opt`) with input fallback. */
function staticOrInput(
  staticMap: StaticMap,
  sheet: string,
  name: string,
  attr: string,
  fallback: number,
): number {
  const v = staticMap[sheet]?.[name]?.[attr];
  if (v === undefined || v === null || v === '') return fallback;
  return numberValue(v as never);
}

/**
 * Look up an input time-series value at a given snapshot row index.
 * The input ts sheet stores rows aligned with the snapshots sheet; we trust
 * the row order matches the solved snapshot order (PyPSA's invariant).
 *
 * The temporal series wins over the static scalar whenever the component has a
 * column in the time-series sheet — matching PyPSA's convention that
 * `loads_t.p_set` overrides `loads.p_set`. The static `fallback` is used only
 * for components absent from the temporal sheet entirely; otherwise a non-zero
 * static value would shadow the profile and flatten it.
 */
function inputSeriesValue(
  inputTs: GridRow[] | undefined,
  rowIndex: number,
  column: string,
  fallback: number,
): number {
  const hasTemporalColumn = !!inputTs && inputTs.length > 0 && column in inputTs[0];
  if (!hasTemporalColumn) return fallback;
  if (rowIndex >= inputTs!.length) return 0;
  const cell = inputTs![rowIndex]?.[column];
  if (cell === undefined || cell === null || cell === '') return 0;
  return numberValue(cell);
}

function fmt(n: number, digits = 0): string {
  return n.toLocaleString(undefined, { maximumFractionDigits: digits });
}

// ── Generators ───────────────────────────────────────────────────────────────

function buildGenerators(input: DeriveInput, snapshots: string[]): Record<string, GeneratorDetail> {
  const { model, outputs, currencySymbol = '$', snapshotWeight = 1 } = input;
  const series = outputs.series;
  const staticOut = outputs.static;
  const genStatic = indexByName(model.generators);
  const carrierStatic = indexByName(model.carriers);

  const pSeries = series['generators-p'];
  const inputPMaxPu = model['generators-p_max_pu'];
  const labels = snapshots.map(isoToLabel);

  const details: Record<string, GeneratorDetail> = {};
  for (const name of Object.keys(genStatic)) {
    const row = genStatic[name];
    const carrier = stringValue(row.carrier) || 'Other';
    const bus = stringValue(row.bus);
    const color = resolvedColor(row.color, row.carrier);
    const pNomInput = numberValue(row.p_nom);
    const pNom = staticOrInput(staticOut, 'generators', name, 'p_nom_opt', pNomInput);
    const mc = numberValue(row.marginal_cost);
    const pMaxPuStatic = row.p_max_pu === null || row.p_max_pu === undefined || row.p_max_pu === ''
      ? 1
      : numberValue(row.p_max_pu);
    const ef = numberValue(carrierStatic[carrier]?.co2_emissions);

    const outputSeries: GeneratorDetail['outputSeries'] = [];
    const emissionsSeries: GeneratorDetail['emissionsSeries'] = [];
    const availableSeries: GeneratorDetail['availableSeries'] = [];
    const curtailmentSeries: GeneratorDetail['curtailmentSeries'] = [];

    let energy = 0;
    let totalEmissions = 0;
    for (let i = 0; i < snapshots.length; i++) {
      const out = seriesValue(pSeries, i, name);
      const pos = Math.max(out, 0);
      const ratio = inputSeriesValue(inputPMaxPu, i, name, pMaxPuStatic);
      const avail = Math.max(ratio * pNom, pos); // observed dispatch can't exceed availability
      const emissions = pos * ef;
      energy += pos * snapshotWeight;
      totalEmissions += emissions * snapshotWeight;
      const label = labels[i];
      const stamp = snapshots[i];
      outputSeries.push({ label, timestamp: stamp, output: out });
      emissionsSeries.push({ label, timestamp: stamp, emissions });
      availableSeries.push({ label, timestamp: stamp, available: avail });
      curtailmentSeries.push({ label, timestamp: stamp, curtailment: Math.max(avail - pos, 0) });
    }

    const summary: SummaryItem[] = [
      { label: 'Energy', value: `${fmt(energy)} MWh`, detail: `${snapshotWeight} h weighting applied` },
      { label: 'Operating cost', value: `${fmt(energy * mc)} ${currencySymbol}`, detail: `${mc.toFixed(1)} ${currencySymbol}/MWh marginal cost` },
      { label: 'Emissions', value: `${fmt(totalEmissions)} tCO2e`, detail: `${ef.toFixed(2)} t/MWh carrier factor` },
    ];

    details[name] = {
      name, carrier, color, bus,
      summary, outputSeries, emissionsSeries, availableSeries, curtailmentSeries,
    };
  }
  return details;
}

// ── Buses ────────────────────────────────────────────────────────────────────

function buildBuses(input: DeriveInput, snapshots: string[]): Record<string, BusDetail> {
  const { model, outputs, currencySymbol = '$', snapshotWeight = 1 } = input;
  const series = outputs.series;
  const labels = snapshots.map(isoToLabel);

  const busStatic = indexByName(model.buses);
  const genStatic = indexByName(model.generators);
  const loadStatic = indexByName(model.loads);
  const carrierStatic = indexByName(model.carriers);

  const pSeries = series['generators-p'];
  const priceSeries = series['buses-marginal_price'];
  const vMagSeries = series['buses-v_mag_pu'];
  const vAngSeries = series['buses-v_ang'];
  const loadInputTs = model['loads-p_set'];

  // Index generators / loads by bus once
  const genByBus: Record<string, string[]> = {};
  const loadsByBus: Record<string, string[]> = {};
  Object.values(genStatic).forEach((row) => {
    const b = stringValue(row.bus);
    if (!b) return;
    (genByBus[b] ??= []).push(stringValue(row.name));
  });
  Object.values(loadStatic).forEach((row) => {
    const b = stringValue(row.bus);
    if (!b) return;
    (loadsByBus[b] ??= []).push(stringValue(row.name));
  });

  const details: Record<string, BusDetail> = {};
  for (const name of Object.keys(busStatic)) {
    const gens = genByBus[name] ?? [];
    const loads = loadsByBus[name] ?? [];
    const netSeries: BusDetail['netSeries'] = [];
    const carrierMix: Record<string, number> = {};

    let loadAvg = 0;
    let genAvg = 0;
    let priceAvg = 0;
    let priceCount = 0;
    let hasV = false;
    let hasA = false;

    for (let i = 0; i < snapshots.length; i++) {
      let loadAtT = 0;
      for (const ln of loads) {
        loadAtT += inputSeriesValue(
          loadInputTs, i, ln, numberValue(loadStatic[ln]?.p_set),
        );
      }
      let genAtT = 0;
      let emissionsAtT = 0;
      for (const gn of gens) {
        const out = seriesValue(pSeries, i, gn);
        const pos = Math.max(out, 0);
        genAtT += pos;
        const carrier = stringValue(genStatic[gn]?.carrier) || 'Other';
        const ef = numberValue(carrierStatic[carrier]?.co2_emissions);
        emissionsAtT += pos * ef;
        carrierMix[carrier] = (carrierMix[carrier] ?? 0) + pos * snapshotWeight;
      }
      const smp = priceSeries ? seriesValue(priceSeries, i, name) : 0;
      if (priceSeries) priceCount += 1;
      const vMag = vMagSeries ? seriesValue(vMagSeries, i, name) : 0;
      const vAng = vAngSeries ? seriesValue(vAngSeries, i, name) : 0;
      if (vMagSeries && vMag !== 0) hasV = true;
      if (vAngSeries && vAng !== 0) hasA = true;

      loadAvg += loadAtT;
      genAvg += genAtT;
      priceAvg += smp;
      netSeries.push({
        label: labels[i],
        timestamp: snapshots[i],
        load: loadAtT,
        generation: genAtT,
        smp,
        emissions: emissionsAtT,
        v_mag_pu: vMag,
        v_ang: vAng,
      });
    }
    const n = snapshots.length || 1;
    loadAvg /= n;
    genAvg /= n;
    priceAvg = priceCount ? priceAvg / priceCount : 0;

    details[name] = {
      name,
      summary: [
        { label: 'Average load', value: `${fmt(loadAvg)} MW`, detail: `${loads.length} load(s) attached` },
        { label: 'Average generation', value: `${fmt(genAvg)} MW`, detail: `${gens.length} generator(s) attached` },
        { label: 'Average SMP', value: `${fmt(priceAvg)} ${currencySymbol}/MWh`, detail: 'Bus marginal price' },
      ],
      netSeries,
      hasVoltageMagnitude: !!vMagSeries && hasV,
      hasVoltageAngle: !!vAngSeries && hasA,
      carrierMix: Object.entries(carrierMix)
        .filter(([, v]) => v > 0)
        .sort((a, b) => b[1] - a[1])
        .map(([c, v]): MixItem => ({ label: c, value: v, color: carrierColor(c) })),
    };
  }
  return details;
}

// ── Storage units ────────────────────────────────────────────────────────────

function buildStorageUnits(input: DeriveInput, snapshots: string[]): Record<string, StorageUnitDetail> {
  const { model, outputs } = input;
  const series = outputs.series;
  const staticIn = indexByName(model.storage_units);
  const pSeries = series['storage_units-p'];
  const socSeries = series['storage_units-state_of_charge'];
  const labels = snapshots.map(isoToLabel);

  const details: Record<string, StorageUnitDetail> = {};
  for (const name of Object.keys(staticIn)) {
    const row = staticIn[name];
    const bus = stringValue(row.bus);
    const pNom = numberValue(row.p_nom);
    const maxHours = numberValue(row.max_hours);

    const dispatchSeries: StorageUnitDetail['dispatchSeries'] = [];
    const chargeSeries: StorageUnitDetail['chargeSeries'] = [];
    const dischargeSeries: StorageUnitDetail['dischargeSeries'] = [];
    const stateSeries: StorageUnitDetail['stateSeries'] = [];
    let peakState = 0;

    for (let i = 0; i < snapshots.length; i++) {
      const p = seriesValue(pSeries, i, name);
      const soc = seriesValue(socSeries, i, name);
      peakState = Math.max(peakState, soc);
      const label = labels[i];
      const stamp = snapshots[i];
      dispatchSeries.push({ label, timestamp: stamp, dispatch: p });
      chargeSeries.push({ label, timestamp: stamp, charge: Math.abs(Math.min(p, 0)) });
      dischargeSeries.push({ label, timestamp: stamp, discharge: Math.max(p, 0) });
      stateSeries.push({ label, timestamp: stamp, state: soc });
    }

    details[name] = {
      name, bus,
      summary: [
        { label: 'Power rating', value: `${fmt(pNom)} MW`, detail: 'Storage unit dispatch limit' },
        { label: 'Energy capacity', value: `${fmt(pNom * maxHours)} MWh`, detail: `${maxHours.toFixed(1)} h max_hours` },
        { label: 'Peak state', value: `${fmt(peakState)} MWh`, detail: 'Maximum state of charge' },
      ],
      dispatchSeries, chargeSeries, dischargeSeries, stateSeries,
    };
  }
  return details;
}

// ── Stores ───────────────────────────────────────────────────────────────────

function buildStores(input: DeriveInput, snapshots: string[]): Record<string, StoreDetail> {
  const { model, outputs } = input;
  const series = outputs.series;
  const staticIn = indexByName(model.stores);
  const eSeries = series['stores-e'];
  const pSeries = series['stores-p'];
  const labels = snapshots.map(isoToLabel);

  const details: Record<string, StoreDetail> = {};
  for (const name of Object.keys(staticIn)) {
    const row = staticIn[name];
    const bus = stringValue(row.bus);
    const eNom = numberValue(row.e_nom);

    const energySeries: StoreDetail['energySeries'] = [];
    const powerSeries: StoreDetail['powerSeries'] = [];
    let peakE = 0;
    let peakP = 0;

    for (let i = 0; i < snapshots.length; i++) {
      const e = seriesValue(eSeries, i, name);
      const p = seriesValue(pSeries, i, name);
      peakE = Math.max(peakE, e);
      peakP = Math.max(peakP, Math.abs(p));
      const label = labels[i];
      const stamp = snapshots[i];
      energySeries.push({ label, timestamp: stamp, energy: e });
      powerSeries.push({ label, timestamp: stamp, power: p });
    }

    details[name] = {
      name, bus,
      summary: [
        { label: 'Energy rating', value: `${fmt(eNom)} MWh`, detail: 'Store nominal energy' },
        { label: 'Peak energy', value: `${fmt(peakE)} MWh`, detail: 'Maximum stored energy' },
        { label: 'Peak power', value: `${fmt(peakP)} MW`, detail: 'Maximum absolute store power' },
      ],
      energySeries, powerSeries,
    };
  }
  return details;
}

// ── Branches (lines / links / transformers) ──────────────────────────────────

function buildBranchGroup(
  rows: GridRow[] | undefined,
  component: BranchDetail['component'],
  capacityAttr: 's_nom' | 'p_nom',
  unit: 'MVA' | 'MW',
  p0Sheet: string,
  p1Sheet: string,
  outputs: DeriveInput['outputs'],
  snapshots: string[],
): Record<string, BranchDetail> {
  const labels = snapshots.map(isoToLabel);
  const p0Series = outputs.series[p0Sheet];
  const p1Series = outputs.series[p1Sheet];
  const out: Record<string, BranchDetail> = {};
  if (!p0Series && !p1Series) return out;
  for (const row of rows ?? []) {
    const name = stringValue(row.name);
    if (!name) continue;
    const capacity = Math.max(numberValue(row[capacityAttr]), 1);
    const bus0 = stringValue(row.bus0);
    const bus1 = stringValue(row.bus1);

    const flowSeries: BranchDetail['flowSeries'] = [];
    const loadingSeries: BranchDetail['loadingSeries'] = [];
    const lossesSeries: BranchDetail['lossesSeries'] = [];
    let peakFlow = 0;
    let peakLoading = 0;

    for (let i = 0; i < snapshots.length; i++) {
      const p0 = seriesValue(p0Series, i, name);
      const p1 = seriesValue(p1Series, i, name);
      const flow = Math.max(Math.abs(p0), Math.abs(p1));
      const loading = (flow / capacity) * 100;
      peakFlow = Math.max(peakFlow, flow);
      peakLoading = Math.max(peakLoading, loading);
      flowSeries.push({ label: labels[i], timestamp: snapshots[i], p0, p1 });
      loadingSeries.push({ label: labels[i], timestamp: snapshots[i], loading });
      lossesSeries.push({ label: labels[i], timestamp: snapshots[i], losses: Math.abs(p0 + p1) });
    }

    out[name] = {
      name, component, bus0, bus1,
      summary: [
        { label: component === 'line' || component === 'transformer' ? 'Thermal rating' : 'Transfer rating',
          value: `${fmt(capacity)} ${unit}`,
          detail: `Static ${component} rating` },
        { label: 'Peak flow', value: `${fmt(peakFlow)} MW`, detail: 'Maximum terminal flow' },
        { label: 'Peak loading', value: `${fmt(peakLoading)}%`, detail: 'Maximum utilization' },
      ],
      flowSeries, loadingSeries, lossesSeries,
    };
  }
  return out;
}

function buildBranches(input: DeriveInput, snapshots: string[]): Record<string, BranchDetail> {
  return {
    ...buildBranchGroup(input.model.lines, 'line', 's_nom', 'MVA', 'lines-p0', 'lines-p1', input.outputs, snapshots),
    ...buildBranchGroup(input.model.links, 'link', 'p_nom', 'MW', 'links-p0', 'links-p1', input.outputs, snapshots),
    ...buildBranchGroup(input.model.transformers, 'transformer', 's_nom', 'MVA', 'transformers-p0', 'transformers-p1', input.outputs, snapshots),
  };
}

// ── Processes ────────────────────────────────────────────────────────────────

function buildProcesses(input: DeriveInput, snapshots: string[]): Record<string, ProcessDetail> {
  const { model, outputs, currencySymbol = '$', snapshotWeight = 1 } = input;
  const series = outputs.series;
  const staticOut = outputs.static;
  const processStatic = indexByName(model.processes);
  const labels = snapshots.map(isoToLabel);

  const p0Series = series['processes-p0'];
  const p1Series = series['processes-p1'];

  const details: Record<string, ProcessDetail> = {};
  for (const name of Object.keys(processStatic)) {
    const row = processStatic[name];
    const carrier = stringValue(row.carrier) || 'Other';
    const color = resolvedColor(row.color, row.carrier);
    const bus0 = stringValue(row.bus0);
    const bus1 = stringValue(row.bus1);
    const pNomInput = numberValue(row.p_nom);
    const pNom = staticOrInput(staticOut, 'processes', name, 'p_nom_opt', pNomInput);
    const mc = numberValue(row.marginal_cost);

    const p0Out: ProcessDetail['p0Series'] = [];
    const p1Out: ProcessDetail['p1Series'] = [];
    const throughputOut: ProcessDetail['throughputSeries'] = [];

    let throughputEnergy = 0;
    let weightedRatioNum = 0;
    let weightedRatioDen = 0;

    for (let i = 0; i < snapshots.length; i++) {
      const p0 = seriesValue(p0Series, i, name);
      const p1 = seriesValue(p1Series, i, name);
      const throughput = Math.abs(p0);
      throughputEnergy += throughput * snapshotWeight;
      if (Math.abs(p0) > 1e-9) {
        // efficiency_t ≈ |p1| / |p0| weighted by throughput so quiet hours
        // don't dominate the mean.
        weightedRatioNum += (Math.abs(p1) / Math.abs(p0)) * throughput;
        weightedRatioDen += throughput;
      }
      const label = labels[i];
      const stamp = snapshots[i];
      p0Out.push({ label, timestamp: stamp, p0 });
      p1Out.push({ label, timestamp: stamp, p1 });
      throughputOut.push({ label, timestamp: stamp, throughput });
    }

    const realisedEfficiency = weightedRatioDen > 0 ? weightedRatioNum / weightedRatioDen : 0;
    const summary: SummaryItem[] = [
      { label: 'Power rating', value: `${fmt(pNom)} MW`, detail: pNom !== pNomInput ? 'Solved p_nom_opt' : 'Input p_nom' },
      { label: 'Throughput', value: `${fmt(throughputEnergy)} MWh`, detail: `${snapshotWeight} h weighting applied` },
      { label: 'Realised efficiency', value: realisedEfficiency > 0 ? realisedEfficiency.toFixed(3) : '—', detail: 'Throughput-weighted |p1|/|p0|' },
      { label: 'Operating cost', value: `${fmt(throughputEnergy * mc)} ${currencySymbol}`, detail: `${mc.toFixed(1)} ${currencySymbol}/MWh marginal cost` },
    ];

    details[name] = {
      name, carrier, color, bus0, bus1,
      summary,
      p0Series: p0Out,
      p1Series: p1Out,
      throughputSeries: throughputOut,
    };
  }
  return details;
}

// ── Shunt impedances ────────────────────────────────────────────────────────

function buildShuntImpedances(input: DeriveInput, snapshots: string[]): Record<string, ShuntImpedanceDetail> {
  const { model, outputs } = input;
  const series = outputs.series;
  const shuntStatic = indexByName(model.shunt_impedances);
  const labels = snapshots.map(isoToLabel);

  const pSeries = series['shunt_impedances-p'];
  const qSeries = series['shunt_impedances-q'];

  const details: Record<string, ShuntImpedanceDetail> = {};
  for (const name of Object.keys(shuntStatic)) {
    const row = shuntStatic[name];
    const bus = stringValue(row.bus);
    const g = numberValue(row.g);
    const b = numberValue(row.b);

    const pOut: ShuntImpedanceDetail['pSeries'] = [];
    const qOut: ShuntImpedanceDetail['qSeries'] = [];
    let peakAbsP = 0;
    let peakAbsQ = 0;

    for (let i = 0; i < snapshots.length; i++) {
      const p = seriesValue(pSeries, i, name);
      const q = seriesValue(qSeries, i, name);
      peakAbsP = Math.max(peakAbsP, Math.abs(p));
      peakAbsQ = Math.max(peakAbsQ, Math.abs(q));
      const label = labels[i];
      const stamp = snapshots[i];
      pOut.push({ label, timestamp: stamp, p });
      qOut.push({ label, timestamp: stamp, q });
    }

    const summary: SummaryItem[] = [
      { label: 'Conductance (g)', value: `${g.toFixed(3)} S`, detail: g === 0 ? 'No real-power coupling' : 'Real shunt admittance' },
      { label: 'Susceptance (b)', value: `${b.toFixed(3)} S`, detail: b > 0 ? 'Capacitive (voltage support)' : b < 0 ? 'Inductive' : 'No reactive coupling' },
      { label: 'Peak |P|', value: `${fmt(peakAbsP)} MW`, detail: 'Maximum active power absorbed' },
      { label: 'Peak |Q|', value: `${fmt(peakAbsQ)} MVar`, detail: 'Maximum reactive power exchanged' },
    ];

    details[name] = { name, bus, summary, pSeries: pOut, qSeries: qOut };
  }
  return details;
}

// ── Public entry point ──────────────────────────────────────────────────────

export function deriveAssetDetails(
  model: WorkbookModel,
  outputs: RunResults['outputs'] | null | undefined,
  currencySymbol = '$',
  snapshotWeight = 1,
): AssetDetails {
  if (!outputs) return EMPTY_DETAILS;
  const input: DeriveInput = { model, outputs, currencySymbol, snapshotWeight };
  const snapshots = pickSnapshots(outputs.series, [
    'generators-p', 'buses-marginal_price', 'storage_units-p', 'stores-p', 'processes-p0', 'shunt_impedances-p',
  ]);
  return {
    generators: buildGenerators(input, snapshots),
    buses: buildBuses(input, snapshots),
    storageUnits: buildStorageUnits(input, snapshots),
    stores: buildStores(input, snapshots),
    branches: buildBranches(input, snapshots),
    processes: buildProcesses(input, snapshots),
    shuntImpedances: buildShuntImpedances(input, snapshots),
  };
}

/**
 * Convenience wrapper: take a {@link RunResults} that already has `outputs`
 * attached and replace its `assetDetails` with a freshly derived version.
 *
 * Use this after applying a backend run response, after importing a project,
 * or when restoring a run-history entry — anywhere `model + outputs` are
 * known but `assetDetails` might be stale or missing.
 */
export function withDerivedAssetDetails(
  model: WorkbookModel,
  results: RunResults,
  currencySymbol: string,
): RunResults {
  const weight = results.runMeta?.snapshotWeight ?? 1;
  return {
    ...results,
    assetDetails: deriveAssetDetails(model, results.outputs, currencySymbol, weight),
  };
}
