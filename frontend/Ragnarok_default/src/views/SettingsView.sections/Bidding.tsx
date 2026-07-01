/**
 * Bid-strategy section (Tier 2) — does bidding above cost pay off?
 *
 * Pick an owner and a markup; the run re-clears the market with that owner's
 * offers raised and reports its profit vs the price-taker baseline. A pivotal
 * owner gains (market power); a competitive one loses dispatch. Extends the
 * optimise run; mutually exclusive with the LP-reshaping modes.
 */
import React from 'react';
import {
  BidStrategyConfig,
  ContingencyConfig,
  PowerFlowConfig,
  RollingHorizonConfig,
  SamplingConfig,
  SecurityConstrainedConfig,
  StochasticConfig,
} from 'lib/types';

export interface BiddingSectionProps {
  bidStrategyConfig: BidStrategyConfig;
  onBidStrategyConfigChange: (config: BidStrategyConfig) => void;
  merchantOwners: string[];
  ownerColumn: string;
  rollingConfig: RollingHorizonConfig;
  stochasticConfig: StochasticConfig;
  samplingConfig: SamplingConfig;
  sclopfConfig: SecurityConstrainedConfig;
  powerFlowConfig: PowerFlowConfig;
  contingencyConfig: ContingencyConfig;
}

export function BiddingSection(props: BiddingSectionProps) {
  const cfg = props.bidStrategyConfig;
  const owners = props.merchantOwners;
  const blockReason =
    props.rollingConfig.enabled ? 'rolling horizon' :
    props.stochasticConfig.enabled ? 'stochastic mode' :
    props.sclopfConfig.enabled ? 'security-constrained (SCLOPF)' :
    props.samplingConfig.enabled ? 'sampled snapshot blocks' :
    props.powerFlowConfig.enabled ? 'power flow' :
    props.contingencyConfig.enabled ? 'N-1 contingency' : '';
  const blocked = blockReason !== '';
  const set = (patch: Partial<BidStrategyConfig>) => props.onBidStrategyConfigChange({ ...cfg, ...patch });
  const markupPct = Math.round((cfg.markup || 0) * 1000) / 10;

  return (
    <section className="constraints-workspace-section">
      <header className="constraints-workspace-section-header">
        <h3>Bid strategy (market power)</h3>
        <p>
          Simulate an owner bidding <em>above</em> marginal cost. The market is
          re-cleared with the owner's offers marked up, and its profit is
          compared to the price-taker baseline. If the owner is pivotal, the
          markup lifts the clearing price and profit rises (market power); if
          not, it just loses dispatch. Profit is always evaluated at the owner's
          true cost — the markup is only the offer.
        </p>
      </header>

      <div className="sg-setting-row">
        <label className="sg-setting-label">Mode</label>
        <div className="sg-btn-row">
          <button
            className={`tb-btn sg-solver-btn${!cfg.enabled ? '' : ' tb-btn--muted'}`}
            onClick={() => set({ enabled: false })}
          >
            Off
          </button>
          <button
            className={`tb-btn sg-solver-btn${cfg.enabled ? '' : ' tb-btn--muted'}`}
            disabled={blocked}
            title={blocked ? `Disable ${blockReason} to enable bid-strategy` : undefined}
            onClick={() => set({ enabled: true })}
          >
            Simulate markup
          </button>
        </div>
        {blocked && (
          <p className="sg-setting-hint" style={{ color: 'var(--danger, #dc2626)' }}>
            <strong>Disable {blockReason} to enable bid-strategy simulation.</strong>
          </p>
        )}
      </div>

      {cfg.enabled && (
        <>
          <div className="sg-setting-divider" />
          <div className="sg-setting-row">
            <label className="sg-setting-label" htmlFor="rs-bid-owner">Owner</label>
            {owners.length > 0 ? (
              <select id="rs-bid-owner" className="sg-num-input" value={cfg.owner} onChange={(e) => set({ owner: e.target.value })}>
                <option value="">Select an owner…</option>
                {owners.map((o) => <option key={o} value={o}>{o}</option>)}
              </select>
            ) : (
              <input id="rs-bid-owner" type="text" className="sg-num-input" placeholder="Owner tag" value={cfg.owner} onChange={(e) => set({ owner: e.target.value })} />
            )}
            <p className="sg-setting-hint">
              {owners.length > 0
                ? `${owners.length} owner${owners.length === 1 ? '' : 's'} in “${props.ownerColumn || 'owner'}” (set in Company settings).`
                : `No values in “${props.ownerColumn || 'owner'}” — set the owner column in Company settings and tag assets in the Model grid.`}
            </p>
          </div>

          <div className="sg-setting-row">
            <label className="sg-setting-label">Strategy</label>
            <div className="sg-btn-row">
              <button className={`tb-btn sg-solver-btn${cfg.mode === 'fixed' ? '' : ' tb-btn--muted'}`} onClick={() => set({ mode: 'fixed' })}>Fixed markup</button>
              <button className={`tb-btn sg-solver-btn${cfg.mode === 'optimal' ? '' : ' tb-btn--muted'}`} onClick={() => set({ mode: 'optimal' })}>Find optimal</button>
            </div>
            <p className="sg-setting-hint">
              {cfg.mode === 'optimal'
                ? 'Ragnarok sweeps the markup and reports the profit-maximising bid (one re-solve per step).'
                : 'Simulate a single markup you choose.'}
            </p>
          </div>

          <div className="sg-setting-row">
            <label className="sg-setting-label">Markup type</label>
            <div className="sg-btn-row">
              <button className={`tb-btn sg-solver-btn${cfg.markupType === 'percent' ? '' : ' tb-btn--muted'}`} onClick={() => set({ markupType: 'percent' })}>Percent</button>
              <button className={`tb-btn sg-solver-btn${cfg.markupType === 'absolute' ? '' : ' tb-btn--muted'}`} onClick={() => set({ markupType: 'absolute' })}>Fixed adder</button>
            </div>
          </div>

          {cfg.mode === 'fixed' ? (
            <div className="sg-setting-row">
              <label className="sg-setting-label" htmlFor="rs-bid-markup">
                {cfg.markupType === 'percent' ? 'Markup (%)' : 'Markup (/MWh)'}
              </label>
              <input
                id="rs-bid-markup"
                type="number"
                min={0}
                step={cfg.markupType === 'percent' ? 5 : 1}
                className="sg-num-input"
                value={cfg.markupType === 'percent' ? markupPct : cfg.markup}
                onChange={(e) => {
                  const v = parseFloat(e.target.value);
                  if (Number.isFinite(v)) set({ markup: cfg.markupType === 'percent' ? Math.max(0, v / 100) : Math.max(0, v) });
                }}
              />
              <p className="sg-setting-hint">
                {cfg.markupType === 'percent'
                  ? 'Offer = marginal cost × (1 + markup). e.g. 50% bids at 1.5× cost.'
                  : 'Offer = marginal cost + this fixed amount per MWh.'}
              </p>
            </div>
          ) : (
            <>
              <div className="sg-setting-row">
                <label className="sg-setting-label" htmlFor="rs-bid-maxmarkup">
                  {cfg.markupType === 'percent' ? 'Max markup (%)' : 'Max markup (/MWh)'}
                </label>
                <input
                  id="rs-bid-maxmarkup"
                  type="number"
                  min={0}
                  step={cfg.markupType === 'percent' ? 10 : 5}
                  className="sg-num-input"
                  value={cfg.markupType === 'percent' ? Math.round((cfg.maxMarkup || 0) * 1000) / 10 : cfg.maxMarkup}
                  onChange={(e) => {
                    const v = parseFloat(e.target.value);
                    if (Number.isFinite(v)) set({ maxMarkup: cfg.markupType === 'percent' ? Math.max(0, v / 100) : Math.max(0, v) });
                  }}
                />
                <p className="sg-setting-hint">Upper bound of the markup sweep.</p>
              </div>
              <div className="sg-setting-row">
                <label className="sg-setting-label" htmlFor="rs-bid-steps">Sweep steps</label>
                <input
                  id="rs-bid-steps"
                  type="number"
                  min={2}
                  max={20}
                  step={1}
                  className="sg-num-input"
                  value={cfg.steps}
                  onChange={(e) => {
                    const v = parseInt(e.target.value, 10);
                    if (Number.isFinite(v)) set({ steps: Math.max(2, Math.min(20, v)) });
                  }}
                />
                <p className="sg-setting-hint">More steps = finer curve, but one extra solve each.</p>
              </div>
            </>
          )}
        </>
      )}
    </section>
  );
}
