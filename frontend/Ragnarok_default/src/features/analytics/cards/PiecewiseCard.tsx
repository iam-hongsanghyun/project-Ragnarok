/**
 * PiecewiseCard (P30) — piecewise-linear cost curves and what the solve did with them.
 *
 * One row per curve: the breakpoints, whether PyPSA solved it as an LP (convex /
 * linear) or added binaries (non-convex), and the realised `marginal_cost_piecewise_opt`
 * (the average cost per MWh the optimiser ended up paying) or `capital_cost_piecewise_opt`
 * (average annual capital cost per unit of the optimal capacity). The totals are
 * the objective terms the curves contribute, so they add into the cost breakdown.
 */
import React from 'react';
import { PiecewiseResult } from 'lib/types';

interface Props {
  data: PiecewiseResult;
  currencySymbol?: string;
}

const num = (v: number, d = 2) => v.toLocaleString(undefined, { maximumFractionDigits: d });
const SHAPE_LABEL = { convex: 'convex (LP)', linear: 'linear (LP)', nonconvex: 'non-convex (MIP)' } as const;

export function PiecewiseCard({ data, currencySymbol }: Props) {
  const cur = currencySymbol ?? '';
  return (
    <div className="econ-card">
      <div className="econ-kpi-row">
        <div className="econ-kpi">
          <div className="econ-kpi-label">Curves</div>
          <div className="econ-kpi-value">{data.curves.length}</div>
        </div>
        <div className="econ-kpi">
          <div className="econ-kpi-label">Operating cost on curves</div>
          <div className="econ-kpi-value">{cur}{num(data.totalOperatingCost, 0)}</div>
        </div>
        <div className="econ-kpi">
          <div className="econ-kpi-label">Annual capital cost on curves</div>
          <div className="econ-kpi-value">{cur}{num(data.totalCapitalCost, 0)}</div>
        </div>
      </div>
      <table className="econ-table">
        <thead>
          <tr>
            <th>Component</th>
            <th>Curve</th>
            <th>Breakpoints ({'x → y'})</th>
            <th>Solve</th>
            <th>Realised average</th>
          </tr>
        </thead>
        <tbody>
          {data.curves.map((c) => (
            <tr key={`${c.list}-${c.name}-${c.attribute}`}>
              <td>{c.name} <span className="econ-sub">{c.component}</span></td>
              <td>{c.attribute}</td>
              <td>{c.breakpoints.map((b) => `${num(b.x, 3)}→${num(b.y, 3)}`).join('  ')}</td>
              <td>{SHAPE_LABEL[c.shape]}</td>
              <td>
                {c.solved && 'averagePerMWh' in c.solved
                  ? `${cur}${num(c.solved.averagePerMWh)}/MWh (${num(c.solved.minPerMWh)}–${num(c.solved.maxPerMWh)}) over ${num(c.solved.energyMWh, 0)} MWh`
                  : c.solved && 'averagePerUnit' in c.solved
                    ? `${cur}${num(c.solved.averagePerUnit)}/unit × ${num(c.solved.capacityOpt)} = ${cur}${num(c.solved.annualCost, 0)}`
                    : '—'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
