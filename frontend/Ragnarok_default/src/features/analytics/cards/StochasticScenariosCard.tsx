/**
 * Per-scenario breakdown for a stochastic run.
 *
 * Renders one row per scenario with operating cost, emissions, energy
 * served, and load shedding, plus an "Expected" footer that probability-
 * weights the totals. The representative scenario (the one whose dispatch
 * is shown in every other chart) is highlighted.
 */
import React from 'react';
import { StochasticResult } from 'lib/types';

interface Props {
  stochastic: StochasticResult;
  currencySymbol: string;
  /** Server probability-weighted totals (`analysis/totals`); null while loading. */
  expected?: {
    expectedEnergyMwh: number;
    expectedEmissionsTco2: number;
    expectedOperatingCost: number;
    expectedLoadShedMwh: number;
  } | null;
}

function fmt(n: number, digits = 0): string {
  return n.toLocaleString(undefined, { maximumFractionDigits: digits });
}

export function StochasticScenariosCard({ stochastic, currencySymbol, expected = null }: Props) {
  const { scenarios, representativeScenario } = stochastic;
  if (!scenarios.length) return null;

  return (
    <div className="stochastic-card">
      <div className="stochastic-card-header">
        <div>
          <h3>Stochastic scenarios</h3>
          <p>
            Two-stage solve across {scenarios.length} probability-weighted scenarios. Detailed
            charts elsewhere on this page show <strong>{representativeScenario}</strong> — the
            highest-weighted scenario; aggregate metrics here are probability-weighted across
            all scenarios.
          </p>
        </div>
      </div>
      <table className="stochastic-table">
        <thead>
          <tr>
            <th>Scenario</th>
            <th>Weight</th>
            <th>Overrides</th>
            <th>Energy (MWh)</th>
            <th>Emissions (tCO₂e)</th>
            <th>Operating cost</th>
            <th>Load shed (MWh)</th>
          </tr>
        </thead>
        <tbody>
          {scenarios.map((s) => (
            <tr
              key={s.name}
              className={s.name === representativeScenario ? 'stochastic-representative' : undefined}
            >
              <td>
                {s.name}
                {s.name === representativeScenario && (
                  <span className="chart-unit-note">(shown above)</span>
                )}
              </td>
              <td>{s.weight.toFixed(2)}</td>
              <td>{s.overrideCount}</td>
              <td>{fmt(s.totalEnergyMwh)}</td>
              <td>{fmt(s.totalEmissionsTco2)}</td>
              <td>{fmt(s.totalOperatingCost)} {currencySymbol}</td>
              <td>{fmt(s.loadShedEnergyMwh)}</td>
            </tr>
          ))}
          <tr style={{ fontWeight: 600 }}>
            <td>Expected (probability-weighted)</td>
            <td>—</td>
            <td>—</td>
            <td>{expected ? fmt(expected.expectedEnergyMwh) : '—'}</td>
            <td>{expected ? fmt(expected.expectedEmissionsTco2) : '—'}</td>
            <td>{expected ? `${fmt(expected.expectedOperatingCost)} ${currencySymbol}` : '—'}</td>
            <td>{expected ? fmt(expected.expectedLoadShedMwh) : '—'}</td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}
