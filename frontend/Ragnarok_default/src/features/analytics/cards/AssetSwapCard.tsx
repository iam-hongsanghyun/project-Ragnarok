/**
 * AssetSwapCard (DW2) — repowering what-if, before vs after.
 *
 * Headline: the emissions and system-cost change from retiring one carrier and
 * replacing it with another, plus the replacement capex and a simple payback.
 * The repowering decision as a number.
 */
import React from 'react';
import { AssetSwapResult } from 'lib/types';
import { carrierColor } from 'lib/utils/helpers';

function money(v: number, currency: string): string {
  const abs = Math.abs(v), sign = v < 0 ? '-' : '';
  if (abs >= 1e9) return `${sign}${currency}${(abs / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `${sign}${currency}${(abs / 1e6).toFixed(2)}M`;
  if (abs >= 1e3) return `${sign}${currency}${(abs / 1e3).toFixed(1)}k`;
  return `${sign}${currency}${Math.round(abs).toLocaleString()}`;
}
const kt = (t: number) => (t / 1000).toLocaleString(undefined, { maximumFractionDigits: 1 });

interface Props {
  data: AssetSwapResult;
}

export function AssetSwapCard({ data }: Props) {
  const { currency, removeSummary, addCarrier, before, after, delta } = data;
  const emGain = delta.emissionsTonnes <= 0; // negative delta = emissions cut = good
  const costGain = delta.systemCost <= 0;

  return (
    <div className="econ-card">
      <div className="econ-kpi-row">
        <div className="econ-kpi">
          <div className="econ-kpi-label">Swap</div>
          <div className="econ-kpi-value" style={{ fontSize: '0.9rem' }}>
            {removeSummary}
            {' → '}
            <span className="carrier-dot" style={{ backgroundColor: carrierColor(addCarrier) }} />{addCarrier}
          </div>
          <div className="econ-kpi-unit">
            {data.removedCount} unit{data.removedCount === 1 ? '' : 's'}, {Math.round(data.removedCapacityMW).toLocaleString()} → {Math.round(data.addedCapacityMW).toLocaleString()} MW ({data.replaceRatio}×)
            {data.addedStorageMW > 0 ? ` + ${Math.round(data.addedStorageMW).toLocaleString()} MW storage` : ''}
            {data.replacementFirm ? ' · firm (no profile)' : ''}
          </div>
        </div>
        <div className="econ-kpi">
          <div className="econ-kpi-label">Δ Emissions</div>
          <div className={`econ-kpi-value ${emGain ? 'econ-recovered' : 'econ-shortfall'}`}>
            {delta.emissionsTonnes <= 0 ? '' : '+'}{kt(delta.emissionsTonnes)} kt
          </div>
          <div className="econ-kpi-unit">{emGain ? 'CO₂ avoided' : 'CO₂ added'}</div>
        </div>
        <div className="econ-kpi">
          <div className="econ-kpi-label">Δ System cost</div>
          <div className={`econ-kpi-value ${costGain ? 'econ-recovered' : 'econ-shortfall'}`}>
            {delta.systemCost <= 0 ? '' : '+'}{money(delta.systemCost, currency)}
          </div>
          <div className="econ-kpi-unit">annual, {costGain ? 'cheaper' : 'costlier'}</div>
        </div>
        <div className="econ-kpi">
          <div className="econ-kpi-label">Payback</div>
          <div className="econ-kpi-value">{data.paybackYears == null ? '—' : `${data.paybackYears} yr`}</div>
          <div className="econ-kpi-unit">capex ÷ opex saving</div>
        </div>
      </div>

      <div className="econ-body">
        <div className="econ-table-col">
          <p className="econ-section-label">Before vs after</p>
          <div className="econ-table-wrap">
            <table className="econ-table">
              <thead>
                <tr>
                  <th>Metric</th>
                  <th className="num">Before</th>
                  <th className="num">After</th>
                  <th className="num">Δ</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td>Emissions (ktCO₂)</td>
                  <td className="num">{kt(before.emissionsTonnes)}</td>
                  <td className="num">{kt(after.emissionsTonnes)}</td>
                  <td className={`num ${emGain ? 'econ-recovered' : 'econ-shortfall'}`}>{kt(delta.emissionsTonnes)}</td>
                </tr>
                <tr>
                  <td>Operating cost</td>
                  <td className="num">{money(before.operatingCost, currency)}</td>
                  <td className="num">{money(after.operatingCost, currency)}</td>
                  <td className={`num ${delta.operatingCost <= 0 ? 'econ-recovered' : 'econ-shortfall'}`}>{money(delta.operatingCost, currency)}</td>
                </tr>
                <tr>
                  <td>System cost (capex + opex)</td>
                  <td className="num">{money(before.systemCost, currency)}</td>
                  <td className="num">{money(after.systemCost, currency)}</td>
                  <td className={`num ${costGain ? 'econ-recovered' : 'econ-shortfall'}`}>{money(delta.systemCost, currency)}</td>
                </tr>
                <tr>
                  <td>Replacement capex (annualised)</td>
                  <td className="num">—</td>
                  <td className="num">{money(data.replacementCapex, currency)}</td>
                  <td className="num">—</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <p className="econ-note">
        Retire generators matching [{removeSummary}] and replace them 1:1 with “{addCarrier}”, then re-solve.
        {data.replacementFirm && ' The replacement carrier has no availability profile in the model, so it is treated as firm — its output may be overstated.'}
        {' '}Payback = the replacement's overnight capex ÷ annual operating (fuel + carbon) saving; it ignores the
        retired asset's avoided capex. A repowering screen, not a full project appraisal.
      </p>
    </div>
  );
}
