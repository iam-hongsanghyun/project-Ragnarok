/**
 * GeneratorEconomicsCard — F0 competitive-benchmark asset economics.
 *
 * Reads revenue / gross margin / capex-recovery that the backend computes from
 * the cost-min solve (no extra solve): under the least-cost LP, optimal dispatch
 * is the perfectly-competitive profit-max equilibrium, so these are each asset's
 * competitive economics. Money columns are on the modeled-horizon basis;
 * `recoveryPct` compares the horizon margin to the annualised fixed cost and is
 * scale-invariant. Table-focused, mirroring CapacityExpansionCard.
 */
import React from 'react';
import { GeneratorEconomics } from 'lib/types';

function compactMoney(v: number, currency: string): string {
  const sign = v < 0 ? '−' : '';
  const abs = Math.abs(v);
  if (abs >= 1e9) return `${sign}${currency}${(abs / 1e9).toFixed(1)}B`;
  if (abs >= 1e6) return `${sign}${currency}${(abs / 1e6).toFixed(1)}M`;
  if (abs >= 1e3) return `${sign}${currency}${(abs / 1e3).toFixed(0)}k`;
  return `${sign}${currency}${Math.round(abs).toLocaleString()}`;
}

function fullMoney(v: number, currency: string): string {
  return `${v < 0 ? '−' : ''}${currency}${Math.abs(Math.round(v)).toLocaleString()}`;
}

function RecoveryCell({ pct }: { pct: number | null }) {
  if (pct == null) return <td className="num econ-muted">—</td>;
  const cls = pct >= 100 ? 'econ-recovered' : 'econ-shortfall';
  const text = pct >= 1000 ? `${Math.round(pct).toLocaleString()}%` : `${pct.toFixed(0)}%`;
  return <td className={`num ${cls}`}>{text}</td>;
}

function NetCell({ v, currency }: { v: number; currency: string }) {
  const cls = v > 0 ? 'econ-recovered' : v < 0 ? 'econ-shortfall' : '';
  return <td className={`num ${cls}`}>{fullMoney(v, currency)}</td>;
}

interface Props {
  data: GeneratorEconomics;
  currencySymbol?: string;
}

export function GeneratorEconomicsCard({ data, currencySymbol }: Props) {
  const currency = currencySymbol ?? data.currency ?? '$';
  const { system, byCarrier, generators, storage } = data;

  if (!generators.length && !storage.length) {
    return (
      <div className="econ-card">
        <p className="dashboard-cell-missing">
          No asset economics — this run has no dispatched or built generators with prices.
        </p>
      </div>
    );
  }

  const horizonNote =
    `Figures cover the modeled horizon (${Math.round(data.modeledHours).toLocaleString()} h ` +
    `≈ ${data.horizonYears.toFixed(2)} yr). Recovery % compares the horizon margin to the ` +
    `annualised fixed cost, so it reads the same regardless of window length. Competitive ` +
    `benchmark — market power is not modelled.`;

  return (
    <div className="econ-card">
      <div className="econ-kpi-row">
        <div className="econ-kpi">
          <div className="econ-kpi-label">System gross margin</div>
          <div className="econ-kpi-value">{compactMoney(system.grossMargin, currency)}</div>
          <div className="econ-kpi-unit">revenue − variable cost</div>
        </div>
        <div className="econ-kpi">
          <div className="econ-kpi-label">Net of fixed cost</div>
          <div className={`econ-kpi-value ${system.netHorizon >= 0 ? 'econ-recovered' : 'econ-shortfall'}`}>
            {compactMoney(system.netHorizon, currency)}
          </div>
          <div className="econ-kpi-unit">after annualised capex</div>
        </div>
        <div className="econ-kpi">
          <div className="econ-kpi-label">Capex recovery</div>
          <div className="econ-kpi-value">
            {system.recoveryPct == null ? '—' : `${Math.round(system.recoveryPct).toLocaleString()}%`}
          </div>
          <div className="econ-kpi-unit">margin ÷ fixed cost</div>
        </div>
        <div className="econ-kpi">
          <div className="econ-kpi-label">Generators recovering</div>
          <div className="econ-kpi-value">
            {system.generatorsRecovered}<span className="econ-kpi-sub"> / {system.generatorsModeled}</span>
          </div>
          <div className="econ-kpi-unit">cover their fixed cost</div>
        </div>
      </div>

      <div className="econ-body">
        {byCarrier.length > 0 && (
          <div className="econ-table-col">
            <p className="econ-section-label">By carrier</p>
            <div className="econ-table-wrap">
              <table className="econ-table">
                <thead>
                  <tr>
                    <th>Carrier</th>
                    <th className="num">Energy (GWh)</th>
                    <th className="num">Capture ({currency}/MWh)</th>
                    <th className="num">Revenue</th>
                    <th className="num">Gross margin</th>
                    <th className="num">Fixed cost</th>
                    <th className="num">Net</th>
                    <th className="num">Recovery</th>
                  </tr>
                </thead>
                <tbody>
                  {byCarrier.map((c) => (
                    <tr key={c.carrier}>
                      <td>
                        <span className="carrier-dot" style={{ backgroundColor: c.color }} />
                        {c.carrier || '—'}
                      </td>
                      <td className="num">{(c.energyMwh / 1000).toLocaleString(undefined, { maximumFractionDigits: 1 })}</td>
                      <td className="num">{c.capturePrice == null ? '—' : c.capturePrice.toLocaleString()}</td>
                      <td className="num">{fullMoney(c.revenue, currency)}</td>
                      <td className="num">{fullMoney(c.grossMargin, currency)}</td>
                      <td className="num">{c.fixedCostHorizon > 0 ? fullMoney(c.fixedCostHorizon, currency) : '—'}</td>
                      <NetCell v={c.netHorizon} currency={currency} />
                      <RecoveryCell pct={c.recoveryPct} />
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>

      <div className="econ-body">
        <div className="econ-table-col">
          <p className="econ-section-label">By generator</p>
          <div className="econ-table-wrap">
            <table className="econ-table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Carrier</th>
                  <th className="num">Capacity (MW)</th>
                  <th className="num">Energy (GWh)</th>
                  <th className="num">Capture ({currency}/MWh)</th>
                  <th className="num">Gross margin</th>
                  <th className="num">Fixed cost</th>
                  <th className="num">Net</th>
                  <th className="num">Recovery</th>
                </tr>
              </thead>
              <tbody>
                {generators.map((g) => (
                  <tr key={g.name}>
                    <td>{g.name}</td>
                    <td>
                      <span className="carrier-dot" style={{ backgroundColor: g.color }} />
                      {g.carrier || '—'}
                    </td>
                    <td className="num">{g.capacityMw.toLocaleString()}</td>
                    <td className="num">{(g.energyMwh / 1000).toLocaleString(undefined, { maximumFractionDigits: 1 })}</td>
                    <td className="num">{g.capturePrice == null ? '—' : g.capturePrice.toLocaleString()}</td>
                    <td className="num">{fullMoney(g.grossMargin, currency)}</td>
                    <td className="num">{g.fixedCostHorizon > 0 ? fullMoney(g.fixedCostHorizon, currency) : '—'}</td>
                    <NetCell v={g.netHorizon} currency={currency} />
                    <RecoveryCell pct={g.recoveryPct} />
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {storage.length > 0 && (
        <div className="econ-body">
          <div className="econ-table-col">
            <p className="econ-section-label">Storage (arbitrage)</p>
            <div className="econ-table-wrap">
              <table className="econ-table">
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Carrier</th>
                    <th className="num">Capacity (MW)</th>
                    <th className="num">Discharged (GWh)</th>
                    <th className="num">Charged (GWh)</th>
                    <th className="num">Gross margin</th>
                    <th className="num">Fixed cost</th>
                    <th className="num">Net</th>
                    <th className="num">Recovery</th>
                  </tr>
                </thead>
                <tbody>
                  {storage.map((s) => (
                    <tr key={s.name}>
                      <td>{s.name}</td>
                      <td>
                        <span className="carrier-dot" style={{ backgroundColor: s.color }} />
                        {s.carrier || '—'}
                      </td>
                      <td className="num">{s.capacityMw.toLocaleString()}</td>
                      <td className="num">{(s.energyDischargedMwh / 1000).toLocaleString(undefined, { maximumFractionDigits: 1 })}</td>
                      <td className="num">{(s.energyChargedMwh / 1000).toLocaleString(undefined, { maximumFractionDigits: 1 })}</td>
                      <td className="num">{fullMoney(s.grossMargin, currency)}</td>
                      <td className="num">{s.fixedCostHorizon > 0 ? fullMoney(s.fixedCostHorizon, currency) : '—'}</td>
                      <NetCell v={s.netHorizon} currency={currency} />
                      <RecoveryCell pct={s.recoveryPct} />
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      <p className="econ-note">{horizonNote}</p>
    </div>
  );
}
