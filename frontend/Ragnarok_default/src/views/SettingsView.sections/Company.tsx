/**
 * Company / ownership section (F1) — the owner dimension.
 *
 * Sets which model column tags an asset's owner/operator (e.g. `owner`,
 * `Company`). This single column drives both the per-company KPI breakdown in
 * Analytics (F1) and merchant price-taker analysis (B1). Lists the distinct
 * owners detected in the chosen column so the user can see the tagging worked.
 */
import React from 'react';
import { FinanceConfig } from 'lib/types';

export interface CompanySectionProps {
  ownerColumn: string;
  onOwnerColumnChange: (column: string) => void;
  merchantOwners: string[];
  financeConfig: FinanceConfig;
  onFinanceConfigChange: (config: FinanceConfig) => void;
}

export function CompanySection(props: CompanySectionProps) {
  const owners = props.merchantOwners;
  const fin = props.financeConfig;
  const setFin = (patch: Partial<FinanceConfig>) =>
    props.onFinanceConfigChange({ ...fin, ...patch });
  const gearingPct = Math.round((fin.gearing || 0) * 1000) / 10;
  const interestPct = Math.round((fin.interestRate || 0) * 1000) / 10;
  return (
    <section className="constraints-workspace-section">
      <header className="constraints-workspace-section-header">
        <h3>Company / ownership</h3>
        <p>
          Attribute assets to their owner / operator so Analytics can report
          per-company capacity, dispatch, revenue and emissions — instead of
          treating the whole system as one entity. Tag a column in the Model grid
          (generators / storage), then name that column here. The same column
          feeds merchant (price-taker) analysis.
        </p>
      </header>

      <div className="sg-setting-row">
        <label className="sg-setting-label" htmlFor="rs-owner-col">Owner column</label>
        <input
          id="rs-owner-col"
          type="text"
          className="sg-num-input"
          placeholder="owner"
          value={props.ownerColumn}
          onChange={(e) => props.onOwnerColumnChange(e.target.value)}
        />
        <p className="sg-setting-hint">
          Which grid column identifies the owner/operator. Defaults to <code>owner</code> (a
          column Ragnarok adds for you); point it at any column you have, e.g. <code>Company</code>.
        </p>
      </div>

      <div className="sg-setting-row">
        <label className="sg-setting-label">Detected companies</label>
        <div className="sg-setting-value">
          {owners.length > 0 ? `${owners.length}: ${owners.join(', ')}` : 'none yet'}
        </div>
        <p className="sg-setting-hint">
          {owners.length > 0
            ? `Distinct values found in “${props.ownerColumn || 'owner'}”. Per-company KPI (F1) and finance (F2) cards appear in Analytics after a run.`
            : `No values found in “${props.ownerColumn || 'owner'}” — fill that column on the generators / storage sheets in the Model grid.`}
        </p>
      </div>

      <div className="sg-setting-divider" />
      <header className="constraints-workspace-section-header">
        <h3 style={{ fontSize: '0.95rem' }}>Project finance (F2)</h3>
        <p>
          Per-company NPV, IRR and payback are computed from each owner's
          dispatch, revenue (system marginal price) and capex over the asset
          lifetime, discounted at the run's discount rate. Optionally add debt to
          also report DSCR (debt-service coverage). Leave gearing at 0 for an
          all-equity view.
        </p>
      </header>

      <div className="sg-setting-row">
        <label className="sg-setting-label" htmlFor="rs-fin-gearing">Debt gearing (%)</label>
        <input
          id="rs-fin-gearing"
          type="number"
          min={0}
          max={95}
          step={5}
          className="sg-num-input"
          value={gearingPct}
          onChange={(e) => {
            const v = parseFloat(e.target.value);
            if (Number.isFinite(v)) setFin({ gearing: Math.min(0.95, Math.max(0, v / 100)) });
          }}
        />
        <p className="sg-setting-hint">Share of overnight capex financed by debt. 0 = all-equity (no DSCR).</p>
      </div>

      {fin.gearing > 0 && (
        <>
          <div className="sg-setting-row">
            <label className="sg-setting-label" htmlFor="rs-fin-interest">Interest rate (%)</label>
            <input
              id="rs-fin-interest"
              type="number"
              min={0}
              max={30}
              step={0.25}
              className="sg-num-input"
              value={interestPct}
              onChange={(e) => {
                const v = parseFloat(e.target.value);
                if (Number.isFinite(v)) setFin({ interestRate: Math.max(0, v / 100) });
              }}
            />
          </div>
          <div className="sg-setting-row">
            <label className="sg-setting-label" htmlFor="rs-fin-tenor">Debt tenor (years)</label>
            <input
              id="rs-fin-tenor"
              type="number"
              min={1}
              max={40}
              step={1}
              className="sg-num-input"
              value={fin.tenorYears}
              onChange={(e) => {
                const v = parseFloat(e.target.value);
                if (Number.isFinite(v)) setFin({ tenorYears: Math.max(1, Math.round(v)) });
              }}
            />
          </div>
        </>
      )}
    </section>
  );
}
