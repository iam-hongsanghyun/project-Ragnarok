/**
 * CompanyFinanceCard — company-level project finance (F2).
 *
 * Per-owner NPV, IRR, simple & discounted payback, and (when debt is set) DSCR,
 * built from each company's overnight capex and operating margin over the asset
 * lifetime, discounted at the run's discount rate. The investor-facing headline.
 */
import React from 'react';
import { CompanyFinanceResult } from 'lib/types';
import { hashColor } from 'lib/utils/helpers';

function compactMoney(v: number, currency: string): string {
  const abs = Math.abs(v);
  const sign = v < 0 ? '-' : '';
  if (abs >= 1e9) return `${sign}${currency}${(abs / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `${sign}${currency}${(abs / 1e6).toFixed(2)}M`;
  if (abs >= 1e3) return `${sign}${currency}${(abs / 1e3).toFixed(1)}k`;
  return `${sign}${currency}${abs.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}

function pct(v: number | null): string {
  return v == null ? '—' : `${(v * 100).toLocaleString(undefined, { maximumFractionDigits: 1 })}%`;
}

function years(v: number | null): string {
  return v == null ? 'never' : `${v.toLocaleString(undefined, { maximumFractionDigits: 1 })} yr`;
}

interface Props {
  data: CompanyFinanceResult;
}

export function CompanyFinanceCard({ data }: Props) {
  const { currency, companies } = data;
  if (!companies.length) {
    return <p className="dashboard-cell-missing">No financeable companies in this run.</p>;
  }
  const hasDebt = companies.some((c) => c.dscr != null);
  const totalNpv = companies.reduce((s, c) => s + c.npv, 0);

  return (
    <div className="econ-card">
      <div className="econ-kpi-row">
        <div className="econ-kpi">
          <div className="econ-kpi-label">Total NPV</div>
          <div className={`econ-kpi-value ${totalNpv >= 0 ? 'econ-recovered' : 'econ-shortfall'}`}>
            {compactMoney(totalNpv, currency)}
          </div>
          <div className="econ-kpi-unit">across {companies.length} compan{companies.length === 1 ? 'y' : 'ies'}</div>
        </div>
        <div className="econ-kpi">
          <div className="econ-kpi-label">Discount rate</div>
          <div className="econ-kpi-value">{pct(data.discountRate)}</div>
          <div className="econ-kpi-unit">NPV basis</div>
        </div>
      </div>

      <div className="econ-body">
        <div className="econ-table-col">
          <p className="econ-section-label">Project finance by company</p>
          <div className="econ-table-wrap">
            <table className="econ-table">
              <thead>
                <tr>
                  <th>Company</th>
                  <th className="num">Overnight capex</th>
                  <th className="num">Annual margin</th>
                  <th className="num">NPV</th>
                  <th className="num">IRR</th>
                  <th className="num">Payback</th>
                  <th className="num">Disc. payback</th>
                  {hasDebt && <th className="num">DSCR</th>}
                </tr>
              </thead>
              <tbody>
                {companies.map((c) => (
                  <tr key={c.company}>
                    <td>
                      <span className="carrier-dot" style={{ backgroundColor: hashColor(c.company) }} />
                      {c.company}
                    </td>
                    <td className="num">{compactMoney(c.overnightCapex, currency)}</td>
                    <td className="num">{compactMoney(c.annualMargin, currency)}</td>
                    <td className={`num ${c.npv >= 0 ? 'econ-recovered' : 'econ-shortfall'}`}>{compactMoney(c.npv, currency)}</td>
                    <td className="num">{pct(c.irr)}</td>
                    <td className="num">{years(c.paybackYears)}</td>
                    <td className="num">{years(c.discountedPaybackYears)}</td>
                    {hasDebt && <td className="num">{c.dscr == null ? '—' : `${c.dscr.toFixed(2)}×`}</td>}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <p className="econ-note">
        Project finance (F2): NPV discounts each company's annual margin (revenue − opex) less its
        overnight capex over the asset lifetime ({pct(data.discountRate)} discount rate); IRR is the
        rate at which NPV = 0. Overnight capex is reconstructed from the optimiser's annualised
        capital cost. Revenue is the competitive benchmark (system price × dispatch).
        {hasDebt
          ? ' DSCR = annual margin ÷ level debt service.'
          : ' Add debt gearing in Company settings to also see DSCR.'}
      </p>
    </div>
  );
}
