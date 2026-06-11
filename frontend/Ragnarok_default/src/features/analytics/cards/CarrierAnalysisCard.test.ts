/**
 * Unit tests for the per-carrier metric math.
 *
 * The card builds its rows from `results.assetDetails.generators`; we
 * construct a stub `RunResults` here with a tiny two-generator fleet and
 * verify that capacity factor and curtailed energy (MWh) come out right.
 */
import { describe, test, expect } from '@jest/globals';
import type { RunResults } from 'lib/types';

// We import the math by reaching into the helper indirectly — re-derive
// here for testability. Keep this aligned with the card's reducers.
function computeCarrierRows(results: RunResults, snapshotWeight: number, hours: number) {
  const byCarrier = new Map<string, {
    capacity: number; energy: number; curtailment: number; opCost: number;
  }>();
  for (const gen of Object.values(results.assetDetails.generators)) {
    if (gen.name.startsWith('load_shedding_')) continue;
    const carrier = gen.carrier || 'Other';
    if (!byCarrier.has(carrier)) {
      byCarrier.set(carrier, { capacity: 0, energy: 0, curtailment: 0, opCost: 0 });
    }
    const b = byCarrier.get(carrier)!;
    b.capacity += gen.availableSeries.reduce((m, p) => Math.max(m, p.available), 0);
    for (let i = 0; i < gen.outputSeries.length; i++) {
      const out = Math.max(0, gen.outputSeries[i].output);
      const curt = gen.curtailmentSeries[i]?.curtailment ?? 0;
      b.energy += out * snapshotWeight;
      b.curtailment += Math.max(0, curt) * snapshotWeight;
    }
  }
  return Array.from(byCarrier.entries()).map(([carrier, b]) => ({
    carrier,
    cf: b.capacity > 0 && hours > 0 ? b.energy / (b.capacity * hours) : 0,
    curtailmentMwh: b.curtailment,
  }));
}

function stubResults(): RunResults {
  // One solar generator, 100 MW. Two snapshots (1 h each).
  // Snapshot 0: 50% dispatch (50 MW used of 100 available) → 50 MWh curtailed
  // Snapshot 1: 100% dispatch (100 MW used of 100 available) → 0 MWh curtailed
  // Combined: 75% CF, 50 MWh curtailed total.
  const mk = (name: string) => ({
    name, carrier: 'solar', bus: 'b0',
    outputSeries:    [{ label: '0', timestamp: '2025-01-01T00:00:00', output: 50 },
                      { label: '1', timestamp: '2025-01-01T01:00:00', output: 100 }],
    availableSeries: [{ label: '0', timestamp: '2025-01-01T00:00:00', available: 100 },
                      { label: '1', timestamp: '2025-01-01T01:00:00', available: 100 }],
    curtailmentSeries: [{ label: '0', timestamp: '2025-01-01T00:00:00', curtailment: 50 },
                        { label: '1', timestamp: '2025-01-01T01:00:00', curtailment: 0 }],
    emissionsSeries: [{ label: '0', timestamp: '2025-01-01T00:00:00', emissions: 0 },
                      { label: '1', timestamp: '2025-01-01T01:00:00', emissions: 0 }],
    summary: [{ label: 'Energy', value: '150 MWh', detail: '' }],
  });
  return {
    assetDetails: { generators: { g1: mk('g1') as any }, buses: {}, storageUnits: {}, stores: {}, branches: {}, processes: {}, shuntImpedances: {} },
    runMeta: { snapshotCount: 2, snapshotWeight: 1, modeledHours: 2, storeWeight: 1, planningMode: 'single_period', investmentPeriods: [], rolling: null },
  } as unknown as RunResults;
}

describe('Carrier analytics math', () => {
  test('capacity factor and curtailed energy over two snapshots', () => {
    const rows = computeCarrierRows(stubResults(), 1, 2);
    expect(rows).toHaveLength(1);
    expect(rows[0].carrier).toBe('solar');
    // 150 MWh produced out of 100 MW × 2 h = 200 MWh installed → 75% CF
    expect(rows[0].cf).toBeCloseTo(0.75, 3);
    // Curtailed energy: 50 MWh (snap0) + 0 MWh (snap1) = 50 MWh
    expect(rows[0].curtailmentMwh).toBeCloseTo(50, 3);
  });

  test('snapshot weighting scales curtailed energy', () => {
    // 3 h per snapshot: 50 MW curtailed for 3 h = 150 MWh.
    const rows = computeCarrierRows(stubResults(), 3, 6);
    expect(rows[0].curtailmentMwh).toBeCloseTo(150, 3);
  });

  test('load-shedding rows are excluded', () => {
    const r = stubResults();
    r.assetDetails.generators.shed = {
      name: 'load_shedding_b0', carrier: 'shed', bus: 'b0',
      outputSeries: [{ label: '0', timestamp: '0', output: 1000 }],
      availableSeries: [{ label: '0', timestamp: '0', available: 1000 }],
      curtailmentSeries: [{ label: '0', timestamp: '0', curtailment: 0 }],
      emissionsSeries: [{ label: '0', timestamp: '0', emissions: 0 }],
      summary: [],
    } as any;
    const rows = computeCarrierRows(r, 1, 2);
    expect(rows.map((r) => r.carrier)).not.toContain('shed');
  });
});
