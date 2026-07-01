/**
 * EssCard (DW3) — battery business case by size.
 *
 * Plots NPV vs size (with the NPV-maximising size marked) and tables each size's
 * arbitrage revenue, capex, NPV, IRR and payback. Answers "is a battery viable
 * here, and at what size?" — energy-arbitrage revenue only.
 */
import React from 'react';
import { EssBusinessCaseResult } from 'lib/types';

function money(v: number, currency: string): string {
  const abs = Math.abs(v), sign = v < 0 ? '-' : '';
  if (abs >= 1e9) return `${sign}${currency}${(abs / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `${sign}${currency}${(abs / 1e6).toFixed(2)}M`;
  if (abs >= 1e3) return `${sign}${currency}${(abs / 1e3).toFixed(1)}k`;
  return `${sign}${currency}${Math.round(abs).toLocaleString()}`;
}
const pct = (v: number | null) => (v == null ? '—' : `${(v * 100).toLocaleString(undefined, { maximumFractionDigits: 1 })}%`);
const yrs = (v: number | null) => (v == null ? 'never' : `${v} yr`);

interface Props {
  data: EssBusinessCaseResult;
}

export function EssCard({ data }: Props) {
  const { currency, sizes, bestSizeMW, bestNpv, bus } = data;
  if (!sizes.length) {
    return <p className="dashboard-cell-missing">No ESS sweep for this run.</p>;
  }
  const viable = bestNpv >= 0;

  // NPV-vs-size curve.
  const W = 440, H = 220, PAD_L = 56, PAD_B = 32, PAD_T = 12, PAD_R = 12;
  const xs = sizes.map((s) => s.sizeMW);
  const ys = sizes.map((s) => s.npv);
  const xMin = Math.min(...xs), xMax = Math.max(...xs) || 1;
  const yMin = Math.min(0, ...ys), yMax = Math.max(0, ...ys) || 1;
  const plotW = W - PAD_L - PAD_R, plotH = H - PAD_T - PAD_B;
  const px = (v: number) => PAD_L + ((v - xMin) / (xMax - xMin || 1)) * plotW;
  const py = (v: number) => PAD_T + plotH - ((v - yMin) / (yMax - yMin || 1)) * plotH;
  const path = sizes.map((s, i) => `${i === 0 ? 'M' : 'L'}${px(s.sizeMW).toFixed(1)},${py(s.npv).toFixed(1)}`).join(' ');

  return (
    <div className="econ-card">
      <div className="econ-kpi-row">
        <div className="econ-kpi">
          <div className="econ-kpi-label">Best size</div>
          <div className="econ-kpi-value">{Math.round(bestSizeMW).toLocaleString()}<span className="econ-kpi-sub"> MW</span></div>
          <div className="econ-kpi-unit">{data.maxHours} h at bus “{bus}”</div>
        </div>
        <div className="econ-kpi">
          <div className="econ-kpi-label">NPV at best size</div>
          <div className={`econ-kpi-value ${viable ? 'econ-recovered' : 'econ-shortfall'}`}>{money(bestNpv, currency)}</div>
          <div className="econ-kpi-unit">{viable ? 'viable business case' : 'not viable at these costs'}</div>
        </div>
        <div className="econ-kpi">
          <div className="econ-kpi-label">Discount rate</div>
          <div className="econ-kpi-value">{pct(data.discountRate)}</div>
          <div className="econ-kpi-unit">{data.lifetimeYears}-yr life, {pct(data.roundTripEfficiency)} round-trip</div>
        </div>
      </div>

      <div className="econ-body">
        <div className="econ-table-col">
          <p className="econ-section-label">NPV vs battery size — ● = NPV-maximising size</p>
          <svg viewBox={`0 0 ${W} ${H}`} width="100%" style={{ maxWidth: W, overflow: 'visible' }} role="img">
            <line x1={PAD_L} y1={PAD_T} x2={PAD_L} y2={PAD_T + plotH} stroke="var(--border,#e5e7eb)" />
            <line x1={PAD_L} y1={py(0)} x2={PAD_L + plotW} y2={py(0)} stroke="var(--border,#e5e7eb)" />
            <text x={PAD_L - 6} y={py(yMax) + 4} textAnchor="end" fontSize={10} fill="var(--muted,#6b7280)">{money(yMax, currency)}</text>
            <text x={PAD_L - 6} y={py(yMin) + 4} textAnchor="end" fontSize={10} fill="var(--muted,#6b7280)">{money(yMin, currency)}</text>
            <text x={PAD_L} y={PAD_T + plotH + 14} textAnchor="start" fontSize={10} fill="var(--muted,#6b7280)">{Math.round(xMin)} MW</text>
            <text x={PAD_L + plotW} y={PAD_T + plotH + 14} textAnchor="end" fontSize={10} fill="var(--muted,#6b7280)">{Math.round(xMax)} MW</text>
            <path d={path} fill="none" stroke="var(--brand,#0f766e)" strokeWidth={1.6} />
            {sizes.map((s, i) => (
              <circle key={i} cx={px(s.sizeMW)} cy={py(s.npv)} r={s.sizeMW === bestSizeMW ? 4 : 2}
                fill={s.sizeMW === bestSizeMW ? 'var(--brand,#0f766e)' : 'var(--muted,#6b7280)'} />
            ))}
          </svg>
        </div>
      </div>

      <div className="econ-table-wrap">
        <table className="econ-table">
          <thead>
            <tr>
              <th className="num">Size (MW)</th>
              <th className="num">Arbitrage revenue</th>
              <th className="num">Capex (annualised)</th>
              <th className="num">NPV</th>
              <th className="num">IRR</th>
              <th className="num">Payback</th>
            </tr>
          </thead>
          <tbody>
            {sizes.map((s) => (
              <tr key={s.sizeMW}>
                <td className="num">{s.sizeMW === bestSizeMW ? <strong>{s.sizeMW}</strong> : s.sizeMW}</td>
                <td className="num">{money(s.arbitrageRevenue, currency)}</td>
                <td className="num">{money(s.annualisedCapex, currency)}</td>
                <td className={`num ${s.npv >= 0 ? 'econ-recovered' : 'econ-shortfall'}`}>{money(s.npv, currency)}</td>
                <td className="num">{pct(s.irr)}</td>
                <td className="num">{yrs(s.paybackYears)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="econ-note">
        Each size is optimised as a price-taker battery against the run's marginal price (charge cheap,
        discharge dear); revenue is that arbitrage, capex is size × the capital cost, and NPV/IRR/payback
        discount the annual margin over a {data.lifetimeYears}-year life. Price-taker screen — a large
        battery would move the price, and capacity/ancillary revenue is not included.
      </p>
    </div>
  );
}
