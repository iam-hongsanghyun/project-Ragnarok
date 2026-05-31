/**
 * Cross-scenario pivot card.
 *
 * Groups run-history entries by their `scenarioLabel`, picks the latest
 * run per scenario, and pivots a small set of headline KPIs into a
 * scenario-wise comparison table. Complements the existing
 * RunComparisonTable (which compares individual runs, not scenarios).
 *
 * The card only renders when ≥ 2 distinct scenarios are present in the
 * included runs — otherwise it's redundant with the per-run comparison.
 */
import React from 'react';
import { RunHistoryEntry, RunResults } from 'lib/types';

interface Props {
  runs: RunHistoryEntry[];
  activeResults: RunResults | null;
  currencySymbol: string;
}

interface ScenarioRow {
  label: string;
  entry: RunHistoryEntry;
  isActive: boolean;
}

interface MetricRow {
  label: string;
  unit: string;
  values: Array<{ scenarioLabel: string; value: number; raw: string | null }>;
}

function pickNumericSummary(entry: RunHistoryEntry, predicate: (label: string) => boolean): { value: number; raw: string } | null {
  const s = entry.results.summary.find((x) => predicate(x.label));
  if (!s) return null;
  const m = s.value.replace(/,/g, '').match(/[-+]?[0-9]*\.?[0-9]+/);
  const n = m ? parseFloat(m[0]) : NaN;
  if (!Number.isFinite(n)) return null;
  return { value: n, raw: s.value };
}

function carrierMixGwh(entry: RunHistoryEntry): number {
  return entry.results.carrierMix.reduce((sum, m) => sum + m.value, 0) / 1000;
}

export function ScenarioPivotCard({ runs, activeResults, currencySymbol }: Props) {
  // Group by scenarioLabel, taking the latest savedAt per group.
  const byScenario = new Map<string, RunHistoryEntry>();
  for (const entry of runs) {
    const key = (entry.scenarioLabel ?? '').trim();
    if (!key) continue;
    const existing = byScenario.get(key);
    if (!existing || entry.savedAt > existing.savedAt) byScenario.set(key, entry);
  }

  if (byScenario.size < 2) return null;

  const scenarios: ScenarioRow[] = Array.from(byScenario.entries()).map(([label, entry]) => ({
    label,
    entry,
    isActive: entry.results === activeResults,
  }));

  const metricRows: MetricRow[] = [
    {
      label: 'Total dispatch',
      unit: 'GWh',
      values: scenarios.map((s) => ({ scenarioLabel: s.label, value: carrierMixGwh(s.entry), raw: null })),
    },
    {
      label: 'Emissions',
      unit: 'tCO₂e',
      values: scenarios.map((s) => {
        const picked = pickNumericSummary(s.entry, (l) => l.toLowerCase().includes('emission'));
        return { scenarioLabel: s.label, value: picked?.value ?? 0, raw: picked?.raw ?? null };
      }),
    },
    {
      label: 'Average price',
      unit: `${currencySymbol}/MWh`,
      values: scenarios.map((s) => {
        const picked = pickNumericSummary(s.entry, (l) => l.toLowerCase().includes('avg') && l.toLowerCase().includes('price'));
        return { scenarioLabel: s.label, value: picked?.value ?? 0, raw: picked?.raw ?? null };
      }),
    },
    {
      label: 'Peak load',
      unit: 'MW',
      values: scenarios.map((s) => {
        const picked = pickNumericSummary(s.entry, (l) => l.toLowerCase().includes('peak') && l.toLowerCase().includes('load'));
        return { scenarioLabel: s.label, value: picked?.value ?? 0, raw: picked?.raw ?? null };
      }),
    },
  ].filter((row) => row.values.some((v) => v.value !== 0 || v.raw !== null));

  if (metricRows.length === 0) return null;

  return (
    <div className="stochastic-card">
      <div className="stochastic-card-header">
        <div>
          <h3>Cross-scenario comparison</h3>
          <p>
            Latest run from each scenario preset, side by side. Δ columns show the
            difference from the leftmost scenario. The active run is highlighted.
          </p>
        </div>
      </div>
      <table className="stochastic-table">
        <thead>
          <tr>
            <th>Metric</th>
            {scenarios.map((s) => (
              <th key={s.label} className={s.isActive ? 'stochastic-representative' : undefined}>
                {s.label}
              </th>
            ))}
            {scenarios.length > 1 && scenarios.slice(1).map((s) => (
              <th key={`delta-${s.label}`}>Δ vs {scenarios[0].label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {metricRows.map((row) => (
            <tr key={row.label}>
              <td>{row.label}{row.unit && <span className="chart-unit-note">({row.unit})</span>}</td>
              {row.values.map((v, i) => (
                <td
                  key={`${row.label}-${v.scenarioLabel}`}
                  className={scenarios[i].isActive ? 'stochastic-representative' : undefined}
                >
                  {v.value.toLocaleString(undefined, { maximumFractionDigits: 1 })}
                </td>
              ))}
              {row.values.length > 1 && row.values.slice(1).map((v) => {
                const delta = v.value - row.values[0].value;
                const pct = row.values[0].value !== 0 ? (delta / row.values[0].value) * 100 : null;
                return (
                  <td key={`delta-${row.label}-${v.scenarioLabel}`}>
                    {delta > 0 ? '+' : ''}{delta.toLocaleString(undefined, { maximumFractionDigits: 1 })}
                    {pct !== null && (
                      <span className="chart-unit-note">
                        ({pct > 0 ? '+' : ''}{pct.toFixed(1)}%)
                      </span>
                    )}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
