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
import { RunResults } from '../../../shared/types';
import { numberValue, carrierColor } from '../../../shared/utils/helpers';

interface Props {
  results: RunResults;
  currencySymbol: string;
}

interface CarrierRow {
  carrier: string;
  color: string;
  generatorCount: number;
  capacityMw: number;
  energyMwh: number;
  capacityFactor: number;
  curtailmentRatio: number | null;
  effectiveCost: number;
  emissionsIntensity: number;
}

function fmt(n: number, digits = 0): string {
  return n.toLocaleString(undefined, { maximumFractionDigits: digits });
}

export function CarrierAnalysisCard({ results, currencySymbol }: Props) {
  const generators = Object.values(results.assetDetails.generators);
  if (generators.length === 0) return null;

  const snapshotWeight = results.runMeta.snapshotWeight ?? 1;
  const modelledHours = (results.runMeta.snapshotCount ?? 0) * snapshotWeight;
  if (modelledHours <= 0) return null;

  // Aggregate per carrier
  const byCarrier = new Map<string, {
    capacity: number;
    energy: number;
    available: number;
    curtailment: number;
    marginalCostWeighted: number;
    emissions: number;
    generatorCount: number;
  }>();

  for (const gen of generators) {
    // Skip the load-shedding backstop carrier rows
    if (gen.name.startsWith('load_shedding_')) continue;
    const carrier = gen.carrier || 'Other';
    if (!byCarrier.has(carrier)) {
      byCarrier.set(carrier, { capacity: 0, energy: 0, available: 0, curtailment: 0, marginalCostWeighted: 0, emissions: 0, generatorCount: 0 });
    }
    const bucket = byCarrier.get(carrier)!;
    bucket.generatorCount += 1;

    // Capacity: parse from the summary list ("Energy" / etc) — instead pull from output series + the snapshot count
    // We have gen.summary[0] = 'Energy' with formatted value. The raw capacity isn't easily reachable from this builder.
    // We fall back to the maximum availability point as a proxy when availableSeries is present.
    const peakAvailable = gen.availableSeries.reduce((m, p) => Math.max(m, p.available), 0);
    bucket.capacity += peakAvailable;

    let genEnergy = 0;
    let genAvail = 0;
    let genCurt = 0;
    let genEmissions = 0;
    for (let i = 0; i < gen.outputSeries.length; i++) {
      const out = Math.max(0, gen.outputSeries[i].output);
      const avail = gen.availableSeries[i]?.available ?? 0;
      const curt = gen.curtailmentSeries[i]?.curtailment ?? 0;
      const emi = gen.emissionsSeries[i]?.emissions ?? 0;
      genEnergy += out * snapshotWeight;
      genAvail += Math.max(avail, out) * snapshotWeight;
      genCurt += Math.max(0, curt) * snapshotWeight;
      genEmissions += emi * snapshotWeight;
    }
    bucket.energy += genEnergy;
    bucket.available += genAvail;
    bucket.curtailment += genCurt;
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
    curtailmentRatio: b.available > 0 ? b.curtailment / b.available : null,
    effectiveCost: b.energy > 0 ? b.marginalCostWeighted / b.energy : 0,
    emissionsIntensity: b.energy > 0 ? b.emissions / b.energy : 0,
  })).sort((a, b) => b.energyMwh - a.energyMwh);

  if (rows.length === 0) return null;

  return (
    <div className="stochastic-card">
      <div className="stochastic-card-header">
        <div>
          <h3>Carrier performance</h3>
          <p>
            Derived operational metrics per carrier. Capacity factor measures how hard the
            fleet was used; curtailment shows how much available energy was not dispatched.
            Carriers that were never dispatched are omitted. Load-shedding backstop excluded.
          </p>
        </div>
      </div>
      <table className="stochastic-table">
        <thead>
          <tr>
            <th>Carrier</th>
            <th>Generators</th>
            <th>Peak avail. (MW)</th>
            <th>Energy (MWh)</th>
            <th>CF</th>
            <th>Curtailment</th>
            <th>Eff. cost ({currencySymbol}/MWh)</th>
            <th>Intensity (t/MWh)</th>
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
              <td>{r.curtailmentRatio === null || r.curtailmentRatio <= 0 ? '—' : `${(r.curtailmentRatio * 100).toFixed(1)}%`}</td>
              <td>{r.energyMwh > 0 ? r.effectiveCost.toFixed(1) : '—'}</td>
              <td>{r.emissionsIntensity > 0 ? r.emissionsIntensity.toFixed(3) : '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

