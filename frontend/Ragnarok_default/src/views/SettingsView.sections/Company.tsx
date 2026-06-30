/**
 * Company / ownership section (F1) — the owner dimension.
 *
 * Sets which model column tags an asset's owner/operator (e.g. `owner`,
 * `Company`). This single column drives both the per-company KPI breakdown in
 * Analytics (F1) and merchant price-taker analysis (B1). Lists the distinct
 * owners detected in the chosen column so the user can see the tagging worked.
 */
import React from 'react';

export interface CompanySectionProps {
  ownerColumn: string;
  onOwnerColumnChange: (column: string) => void;
  merchantOwners: string[];
}

export function CompanySection(props: CompanySectionProps) {
  const owners = props.merchantOwners;
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
            ? `Distinct values found in “${props.ownerColumn || 'owner'}”. A per-company KPI card appears in Analytics after a run.`
            : `No values found in “${props.ownerColumn || 'owner'}” — fill that column on the generators / storage sheets in the Model grid.`}
        </p>
      </div>
    </section>
  );
}
