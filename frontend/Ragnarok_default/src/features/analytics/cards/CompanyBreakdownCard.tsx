/**
 * CompanyBreakdownCard — per-company KPIs (F1).
 *
 * Groups the solved system by owner tag and shows each company's capacity,
 * energy, competitive-benchmark revenue (LMP × dispatch) and emissions, with a
 * capacity-share bar. The owner dimension that bridges dispatch to F2 finance.
 */
import React from 'react';
import { CompanyBreakdownResult } from 'lib/types';
import { hashColor } from 'lib/utils/helpers';

function fmtMw(v: number): string {
  if (Math.abs(v) >= 1000) return `${Math.round(v).toLocaleString()} MW`;
  return `${v.toLocaleString(undefined, { maximumFractionDigits: 1 })} MW`;
}

function fullMoney(v: number, currency: string): string {
  const sign = v < 0 ? '-' : '';
  return `${sign}${currency}${Math.abs(v).toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}

interface Props {
  data: CompanyBreakdownResult;
}

export function CompanyBreakdownCard({ data }: Props) {
  const { currency, companies } = data;
  if (!companies.length) {
    return <p className="dashboard-cell-missing">No owner-tagged assets in this run.</p>;
  }
  const maxCap = Math.max(1, ...companies.map((c) => c.capacityMW));
  const hasRevenue = companies.some((c) => c.revenue != null);

  return (
    <div className="econ-card">
      <div className="econ-body">
        <div className="econ-table-col">
          <p className="econ-section-label">
            By company — grouped on “{data.ownerColumn}”
            {data.untaggedCount > 0 && (
              <span className="econ-muted"> · {data.untaggedCount} untagged asset{data.untaggedCount === 1 ? '' : 's'} excluded</span>
            )}
          </p>
          <div className="econ-table-wrap">
            <table className="econ-table">
              <thead>
                <tr>
                  <th>Company</th>
                  <th>Capacity share</th>
                  <th className="num">Capacity (MW)</th>
                  <th className="num">Energy (GWh)</th>
                  {hasRevenue && <th className="num">Revenue</th>}
                  <th className="num">Emissions (ktCO₂)</th>
                  <th className="num">Assets</th>
                </tr>
              </thead>
              <tbody>
                {companies.map((c) => {
                  const color = hashColor(c.company);
                  const pct = (c.capacityMW / maxCap) * 100;
                  return (
                    <tr key={c.company}>
                      <td>
                        <span className="carrier-dot" style={{ backgroundColor: color }} />
                        {c.company}
                      </td>
                      <td>
                        <div style={{ background: 'var(--border, #e5e7eb)', borderRadius: 3, height: 10, width: 120, overflow: 'hidden' }}>
                          <div style={{ width: `${pct}%`, background: color, height: '100%' }} />
                        </div>
                      </td>
                      <td className="num">{fmtMw(c.capacityMW)}</td>
                      <td className="num">{(c.energyMWh / 1000).toLocaleString(undefined, { maximumFractionDigits: 1 })}</td>
                      {hasRevenue && <td className="num">{c.revenue == null ? '—' : fullMoney(c.revenue, currency)}</td>}
                      <td className="num">{(c.emissionsTonnes / 1000).toLocaleString(undefined, { maximumFractionDigits: 1 })}</td>
                      <td className="num">
                        {c.generatorCount + c.storageCount}
                        <span className="econ-muted"> ({c.generatorCount}g{c.storageCount > 0 ? `/${c.storageCount}s` : ''})</span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      </div>
      <p className="econ-note">
        Per-company KPIs (F1) grouped by the “{data.ownerColumn}” tag.
        {hasRevenue
          ? ' Revenue is the competitive benchmark (system marginal price × dispatch); for an owner-optimal merchant view use Merchant analysis.'
          : ' Revenue needs marginal prices (an LP run) — not available for this run.'}
      </p>
    </div>
  );
}
