/**
 * PowerFlowCard — results of a power-flow study run (pf/lpf).
 *
 * Shows convergence, method, active losses (AC), and the per-bus voltage
 * profile. Branch loading is rendered by the existing line-loading card; this
 * card is physics-only (no costs/prices, which a power flow doesn't produce).
 */
import React from 'react';
import { PowerFlowResult } from 'lib/types';

interface Props {
  data: PowerFlowResult;
}

export function PowerFlowCard({ data }: Props) {
  if (data.error) {
    return (
      <div className="econ-card">
        <div className="econ-kpi-row">
          <div className="econ-kpi">
            <div className="econ-kpi-label">{data.method}</div>
            <div className="econ-kpi-value econ-shortfall">Failed</div>
            <div className="econ-kpi-unit">did not run</div>
          </div>
        </div>
        <p className="econ-note">{data.error}</p>
      </div>
    );
  }

  const v = data.voltageProfile;
  const vmin = v.length ? Math.min(...v.map((x) => x.min)) : null;
  const vmax = v.length ? Math.max(...v.map((x) => x.max)) : null;

  return (
    <div className="econ-card">
      <div className="econ-kpi-row">
        <div className="econ-kpi">
          <div className="econ-kpi-label">Method</div>
          <div className="econ-kpi-value">{data.linear ? 'Linear (DC)' : 'AC (NR)'}</div>
          <div className="econ-kpi-unit">{data.method}</div>
        </div>
        <div className="econ-kpi">
          <div className="econ-kpi-label">Convergence</div>
          <div className={`econ-kpi-value ${data.converged ? 'econ-recovered' : 'econ-shortfall'}`}>
            {data.linear ? 'n/a' : data.converged ? 'Converged' : 'Diverged'}
          </div>
          <div className="econ-kpi-unit">
            {data.linear
              ? 'direct solve'
              : `≤${data.iterations} iters · max mismatch ${data.maxError.toExponential(1)}`}
          </div>
        </div>
        {!data.linear && (
          <div className="econ-kpi">
            <div className="econ-kpi-label">Active losses</div>
            <div className="econ-kpi-value">{Math.round(data.lossesMwh).toLocaleString()} MWh</div>
            <div className="econ-kpi-unit">peak {Math.round(data.peakLossMw).toLocaleString()} MW</div>
          </div>
        )}
        {vmin != null && vmax != null && (
          <div className="econ-kpi">
            <div className="econ-kpi-label">Voltage range</div>
            <div className="econ-kpi-value">{vmin.toFixed(3)}–{vmax.toFixed(3)}</div>
            <div className="econ-kpi-unit">pu (bus magnitude)</div>
          </div>
        )}
      </div>

      {v.length > 0 ? (
        <div className="econ-body">
          <div className="econ-table-col">
            <p className="econ-section-label">Bus voltage profile (pu)</p>
            <div className="econ-table-wrap">
              <table className="econ-table">
                <thead>
                  <tr>
                    <th>Bus</th>
                    <th className="num">Min</th>
                    <th className="num">Mean</th>
                    <th className="num">Max</th>
                  </tr>
                </thead>
                <tbody>
                  {v.map((b) => (
                    <tr key={b.bus}>
                      <td>{b.bus}</td>
                      <td className={`num ${b.min < 0.95 ? 'econ-shortfall' : ''}`}>{b.min.toFixed(3)}</td>
                      <td className="num">{b.mean.toFixed(3)}</td>
                      <td className={`num ${b.max > 1.05 ? 'econ-shortfall' : ''}`}>{b.max.toFixed(3)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      ) : (
        <p className="econ-note">
          {data.linear
            ? 'Linear (DC) power flow assumes unit voltage magnitude (1.0 pu) — no voltage profile.'
            : 'No bus voltages reported.'}
        </p>
      )}

      <p className="econ-note">
        Power flow reports network physics only — branch loading is in the line-loading card; no costs or prices.
      </p>
    </div>
  );
}
