/**
 * Per-carrier operational analytics.
 *
 * Surfaces derived metrics that aren't already in the energy-mix donut or
 * emissions breakdown:
 *   - Capacity factor (CF) = energy / (installed capacity × modelled hours)
 *   - Curtailment ratio    = Σ curtailed / Σ available, in %
 *   - Effective cost       = Σ (energy × marginal_cost) / Σ energy ($/MWh)
 *   - Emissions intensity  = Σ emissions / Σ energy (tCO₂e/MWh)
 *
 * Carriers used only by the load-shedding backstop are excluded.
 */
import React from 'react';
import { RunResults, WorkbookModel } from 'lib/types';
import { numberValue, carrierColor, stringValue } from 'lib/utils/helpers';

interface Props {
  results: RunResults;
  currencySymbol: string;
  /** Optional: used as fallback when assetDetails.generators is empty (analytics bundle). */
  model?: WorkbookModel;
}

interface CarrierRow {
  carrier: string;
  color: string;
  generatorCount: number;
  capacityMw: number;
  energyMwh: number;
  capacityFactor: number;
  curtailmentMwh: number | null;
  effectiveCost: number;
  emissionsIntensity: number;
}

function fmt(n: number, digits = 0): string {
  return n.toLocaleString(undefined, { maximumFractionDigits: digits });
}

export function CarrierAnalysisCard({ results, currencySymbol, model }: Props) {
  const generators = Object.values(results.assetDetails.generators);

  const snapshotWeight = results.runMeta.snapshotWeight ?? 1;
  const modelledHours = (results.runMeta.snapshotCount ?? 0) * snapshotWeight;
  if (modelledHours <= 0) return null;

  // ── Fallback path: analytics bundle (outputs.series = null) ─────────────
  // When viewing a stored run via the light analytics endpoint, assetDetails
  // is empty because per-snapshot series were stripped. Use the pre-computed
  // generatorEnergy aggregate + outputs.static for capacity instead.
  if (generators.length === 0) {
    const genEnergy = results.generatorEnergy;
    if (!genEnergy || genEnergy.length === 0) return null;

    const staticGens = results.outputs?.static?.['generators'] ?? {};
    const modelGens: Record<string, number> = {};
    for (const row of model?.generators ?? []) {
      const name = stringValue(row.name);
      if (name) modelGens[name] = numberValue(row.p_nom);
    }

    const byCarrier = new Map<string, {
      capacity: number; energy: number; count: number;
      curtEnergy: number; hasCurt: boolean;
    }>();
    for (const ge of genEnergy) {
      if (!ge.name || ge.name.startsWith('load_shedding_')) continue;
      const carrier = ge.carrier || 'Other';
      if (!byCarrier.has(carrier)) byCarrier.set(carrier, { capacity: 0, energy: 0, count: 0, curtEnergy: 0, hasCurt: false });
      const b = byCarrier.get(carrier)!;
      b.energy += ge.value;
      b.count += 1;
      // p_nom_opt from solved static output, else input p_nom from model sheet
      const pNomOpt = numberValue((staticGens[ge.name] as Record<string, unknown> | undefined)?.['p_nom_opt'] as string | number | undefined);
      const pNomIn = modelGens[ge.name] ?? 0;
      b.capacity += pNomOpt > 0 ? pNomOpt : pNomIn;
      // Curtailed energy (MWh) from the backend — present only for renewables
      // with a time-varying p_max_pu; null for thermal units.
      if (ge.curtailmentMwh != null) {
        b.curtEnergy += ge.curtailmentMwh;
        b.hasCurt = true;
      }
    }

    const fallbackRows: CarrierRow[] = Array.from(byCarrier.entries()).map(([carrier, b]) => ({
      carrier,
      color: carrierColor(carrier),
      generatorCount: b.count,
      capacityMw: b.capacity,
      energyMwh: b.energy,
      capacityFactor: b.capacity > 0 ? b.energy / (b.capacity * modelledHours) : 0,
      curtailmentMwh: b.hasCurt ? b.curtEnergy : null,
      effectiveCost: 0,
      emissionsIntensity: 0,
    })).sort((a, b) => b.energyMwh - a.energyMwh);

    if (fallbackRows.length === 0) return null;
    return <CarrierTable rows={fallbackRows} currencySymbol={currencySymbol} cfOnly />;
  }

  // ── Full path: live run or imported project (series available) ───────────
  // Curtailment is only meaningful for generators with a time-varying p_max_pu
  // (renewables) — a thermal unit at static availability running below p_nom
  // is part-loaded, not curtailed. Without the model sheet, fall back to
  // counting every generator (legacy behaviour).
  const tvGenNames = model
    ? new Set(model['generators-p_max_pu']?.length ? Object.keys(model['generators-p_max_pu'][0]) : [])
    : null;

  const byCarrier = new Map<string, {
    capacity: number;
    energy: number;
    curtailment: number;
    hasCurt: boolean;
    marginalCostWeighted: number;
    emissions: number;
    generatorCount: number;
  }>();

  for (const gen of generators) {
    // Skip the load-shedding backstop carrier rows
    if (gen.name.startsWith('load_shedding_')) continue;
    const carrier = gen.carrier || 'Other';
    if (!byCarrier.has(carrier)) {
      byCarrier.set(carrier, { capacity: 0, energy: 0, curtailment: 0, hasCurt: false, marginalCostWeighted: 0, emissions: 0, generatorCount: 0 });
    }
    const bucket = byCarrier.get(carrier)!;
    bucket.generatorCount += 1;
    const isCurtailable = !tvGenNames || tvGenNames.has(gen.name);

    // Capacity: use the maximum availability point as a proxy for installed capacity.
    const peakAvailable = gen.availableSeries.reduce((m, p) => Math.max(m, p.available), 0);
    bucket.capacity += peakAvailable;

    let genEnergy = 0;
    let genCurt = 0;
    let genEmissions = 0;
    for (let i = 0; i < gen.outputSeries.length; i++) {
      const out = Math.max(0, gen.outputSeries[i].output);
      const curt = gen.curtailmentSeries[i]?.curtailment ?? 0;
      const emi = gen.emissionsSeries[i]?.emissions ?? 0;
      genEnergy += out * snapshotWeight;
      genCurt += Math.max(0, curt) * snapshotWeight;
      genEmissions += emi * snapshotWeight;
    }
    bucket.energy += genEnergy;
    if (isCurtailable) {
      bucket.curtailment += genCurt;
      bucket.hasCurt = true;
    }
    bucket.emissions += genEmissions;

    // Effective cost — use the static marginal_cost from the summary's "Operating cost" formatting.
    const opCostItem = gen.summary.find((s) => s.label.toLowerCase().includes('operating'));
    const opCost = opCostItem ? numberValue(opCostItem.value.replace(/[,\s]/g, '').match(/-?[0-9.]+/)?.[0] ?? '0') : 0;
    bucket.marginalCostWeighted += opCost;
  }

  const rows: CarrierRow[] = Array.from(byCarrier.entries()).map(([carrier, b]) => ({
    carrier,
    color: carrierColor(carrier),
    generatorCount: b.generatorCount,
    capacityMw: b.capacity,
    energyMwh: b.energy,
    capacityFactor: b.capacity > 0 && modelledHours > 0 ? b.energy / (b.capacity * modelledHours) : 0,
    curtailmentMwh: b.hasCurt ? b.curtailment : null,
    effectiveCost: b.energy > 0 ? b.marginalCostWeighted / b.energy : 0,
    emissionsIntensity: b.energy > 0 ? b.emissions / b.energy : 0,
  })).sort((a, b) => b.energyMwh - a.energyMwh);

  if (rows.length === 0) return null;
  return <CarrierTable rows={rows} currencySymbol={currencySymbol} />;
}

interface TableProps {
  rows: CarrierRow[];
  currencySymbol: string;
  /** True when curtailment / cost / intensity are unavailable (analytics bundle fallback). */
  cfOnly?: boolean;
}

function CarrierTable({ rows, currencySymbol, cfOnly = false }: TableProps) {
  return (
    <div className="stochastic-card">
      <div className="stochastic-card-header">
        <div>
          <h3>Carrier performance</h3>
          <p>
            Derived operational metrics per carrier. Capacity factor measures how hard the
            fleet was used; curtailment shows how much available renewable energy was not dispatched.
            {cfOnly ? ' Cost and intensity require a full-series view.' : ' Carriers that were never dispatched are omitted. Load-shedding backstop excluded.'}
          </p>
        </div>
      </div>
      <table className="stochastic-table">
        <thead>
          <tr>
            <th>Carrier</th>
            <th>Generators</th>
            <th>Capacity (MW)</th>
            <th>Energy (MWh)</th>
            <th>CF</th>
            {!cfOnly && <th>Eff. cost ({currencySymbol}/MWh)</th>}
            {!cfOnly && <th>Intensity (t/MWh)</th>}
            <th>Curtailment (MWh)</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.carrier}>
              <td>
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
                  <span style={{ width: 10, height: 10, borderRadius: 999, background: r.color }} />
                  {r.carrier}
                </span>
              </td>
              <td>{r.generatorCount}</td>
              <td>{fmt(r.capacityMw)}</td>
              <td>{fmt(r.energyMwh)}</td>
              <td>{r.capacityFactor > 0 ? `${(r.capacityFactor * 100).toFixed(1)}%` : '—'}</td>
              {!cfOnly && <td>{r.energyMwh > 0 ? r.effectiveCost.toFixed(1) : '—'}</td>}
              {!cfOnly && <td>{r.emissionsIntensity > 0 ? r.emissionsIntensity.toFixed(3) : '—'}</td>}
              <td>{r.curtailmentMwh === null || r.curtailmentMwh <= 0 ? '—' : fmt(r.curtailmentMwh)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

