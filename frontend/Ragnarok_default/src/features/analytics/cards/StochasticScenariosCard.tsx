/**
 * Per-scenario breakdown for a stochastic run.
 *
 * Renders one row per scenario with operating cost, emissions, energy
 * served, and load shedding, plus an "Expected" footer that probability-
 * weights the totals. The representative scenario (the one whose dispatch
 * is shown in every other chart) is highlighted.
 */
import React from 'react';
import { StochasticResult } from '../../../shared/types';

interface Props {
  stochastic: StochasticResult;
  currencySymbol: string;
}

function fmt(n: number, digits = 0): string {
  return n.toLocaleString(undefined, { maximumFractionDigits: digits });
}

export function StochasticScenariosCard({ stochastic, currencySymbol }: Props) {
  const { scenarios, representativeScenario } = stochastic;
  if (!scenarios.length) return null;

  const expected = scenarios.reduce(
    (acc, s) => {
      acc.energy += s.totalEnergyMwh * s.weight;
      acc.emissions += s.totalEmissionsTco2 * s.weight;
      acc.cost += s.totalOperatingCost * s.weight;
      acc.shed += s.loadShedEnergyMwh * s.weight;
      return acc;
    },
    { energy: 0, emissions: 0, cost: 0, shed: 0 },
  );

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
            <td>{fmt(expected.energy)}</td>
            <td>{fmt(expected.emissions)}</td>
            <td>{fmt(expected.cost)} {currencySymbol}</td>
            <td>{fmt(expected.shed)}</td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}
