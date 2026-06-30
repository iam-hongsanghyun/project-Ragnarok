/**
 * Merchant (price-taker) section — most-profitable for ONE owner.
 *
 * After the system cost-min, re-optimise just the selected owner's assets
 * against a price signal (system marginal price, or a user-fixed price) to find
 * their profit-maximising dispatch and build. Extends the optimise run; mutually
 * exclusive with the modes that skip or reshape that solve.
 */
import React from 'react';
import {
  ContingencyConfig,
  MerchantConfig,
  PowerFlowConfig,
  RollingHorizonConfig,
  SamplingConfig,
  SecurityConstrainedConfig,
  StochasticConfig,
} from 'lib/types';

export interface MerchantSectionProps {
  merchantConfig: MerchantConfig;
  onMerchantConfigChange: (config: MerchantConfig) => void;
  merchantOwners: string[];
  ownerColumn: string;
  rollingConfig: RollingHorizonConfig;
  stochasticConfig: StochasticConfig;
  samplingConfig: SamplingConfig;
  sclopfConfig: SecurityConstrainedConfig;
  powerFlowConfig: PowerFlowConfig;
  contingencyConfig: ContingencyConfig;
}

export function MerchantSection(props: MerchantSectionProps) {
  const cfg = props.merchantConfig;
  const owners = props.merchantOwners;
  const blockReason =
    props.rollingConfig.enabled ? 'rolling horizon' :
    props.stochasticConfig.enabled ? 'stochastic mode' :
    props.sclopfConfig.enabled ? 'security-constrained (SCLOPF)' :
    props.samplingConfig.enabled ? 'sampled snapshot blocks' :
    props.powerFlowConfig.enabled ? 'power flow' :
    props.contingencyConfig.enabled ? 'N-1 contingency' : '';
  const blocked = blockReason !== '';

  const set = (patch: Partial<MerchantConfig>) =>
    props.onMerchantConfigChange({ ...cfg, ...patch });

  return (
    <section className="constraints-workspace-section">
      <header className="constraints-workspace-section-header">
        <h3>Merchant (price-taker)</h3>
        <p>
          The optimiser answers "least-cost for the whole system". This answers
          "most-profitable for one owner": against a price signal, the owner's
          assets dispatch (and build) to maximise their own profit — generators
          run when the price beats their cost, storage arbitrages. Tag assets
          with an <code>owner</code> in the Model grid, then pick that owner here.
        </p>
      </header>

      <div className="sg-setting-row">
        <label className="sg-setting-label">Mode</label>
        <div className="sg-btn-row">
          <button
            className={`tb-btn sg-solver-btn${!cfg.enabled ? '' : ' tb-btn--muted'}`}
            onClick={() => set({ enabled: false })}
          >
            Optimise only
          </button>
          <button
            className={`tb-btn sg-solver-btn${cfg.enabled ? '' : ' tb-btn--muted'}`}
            disabled={blocked}
            title={blocked ? `Disable ${blockReason} to enable merchant analysis` : undefined}
            onClick={() => set({ enabled: true })}
          >
            Merchant analysis
          </button>
        </div>
        {blocked && (
          <p className="sg-setting-hint" style={{ color: 'var(--danger, #dc2626)' }}>
            <strong>Disable {blockReason} to enable merchant analysis.</strong>
          </p>
        )}
      </div>

      {cfg.enabled && (
        <>
          <div className="sg-setting-divider" />
          <div className="sg-setting-row">
            <label className="sg-setting-label" htmlFor="rs-merchant-owner">Owner</label>
            {owners.length > 0 ? (
              <select
                id="rs-merchant-owner"
                className="sg-num-input"
                value={cfg.owner}
                onChange={(e) => set({ owner: e.target.value })}
              >
                <option value="">Select an owner…</option>
                {owners.map((o) => <option key={o} value={o}>{o}</option>)}
              </select>
            ) : (
              <input
                id="rs-merchant-owner"
                type="text"
                className="sg-num-input"
                placeholder="Owner tag"
                value={cfg.owner}
                onChange={(e) => set({ owner: e.target.value })}
              />
            )}
            <p className="sg-setting-hint">
              {owners.length > 0
                ? `${owners.length} distinct value${owners.length === 1 ? '' : 's'} in “${props.ownerColumn || 'owner'}” (set in Company settings).`
                : `No values found in “${props.ownerColumn || 'owner'}” — set the owner column in Company settings and tag assets in the Model grid.`}
            </p>
          </div>

          <div className="sg-setting-row">
            <label className="sg-setting-label">Price signal</label>
            <div className="sg-btn-row">
              <button
                className={`tb-btn sg-solver-btn${cfg.priceSource === 'lmp' ? '' : ' tb-btn--muted'}`}
                onClick={() => set({ priceSource: 'lmp' })}
              >
                System price (LMP)
              </button>
              <button
                className={`tb-btn sg-solver-btn${cfg.priceSource === 'series' ? '' : ' tb-btn--muted'}`}
                onClick={() => set({ priceSource: 'series' })}
              >
                Fixed price
              </button>
            </div>
            <p className="sg-setting-hint">
              {cfg.priceSource === 'lmp'
                ? 'Two-stage: the owner sees the system marginal price from the cost-min run — the standard merchant-investor model.'
                : 'The owner optimises against a flat exogenous price you set (not tied to the modelled system).'}
            </p>
          </div>

          {cfg.priceSource === 'series' && (
            <div className="sg-setting-row">
              <label className="sg-setting-label" htmlFor="rs-merchant-price">Fixed price (/MWh)</label>
              <input
                id="rs-merchant-price"
                type="number"
                min={0}
                step={1}
                className="sg-num-input"
                value={cfg.flatPrice}
                onChange={(e) => {
                  const v = parseFloat(e.target.value);
                  if (Number.isFinite(v)) set({ flatPrice: v });
                }}
              />
            </div>
          )}
        </>
      )}
    </section>
  );
}
