/**
 * Market-simulation section (B2) — rule-based merit-order market clearing
 * instead of an optimisation.
 *
 * Generators bid their marginal cost, each snapshot clears a single-zone merit
 * order, storage follows a price-threshold arbitrage rule. Answers "what
 * happens under these RULES" (e.g. uniform vs pay-as-bid settlement) rather
 * than "what is optimal". Mutually exclusive with the optimise-only modes,
 * like the power-flow study.
 */
import React from 'react';
import {
  MarketSimConfig,
  PathwayConfig,
  PowerFlowConfig,
  RollingHorizonConfig,
  SamplingConfig,
  SecurityConstrainedConfig,
  StochasticConfig,
} from 'lib/types';

export interface MarketSimulationSectionProps {
  marketSimConfig: MarketSimConfig;
  onMarketSimConfigChange: (config: MarketSimConfig) => void;
  powerFlowConfig: PowerFlowConfig;
  rollingConfig: RollingHorizonConfig;
  stochasticConfig: StochasticConfig;
  pathwayConfig: PathwayConfig;
  samplingConfig: SamplingConfig;
  sclopfConfig: SecurityConstrainedConfig;
}

export function MarketSimulationSection(props: MarketSimulationSectionProps) {
  const cfg = props.marketSimConfig;
  const blockReason =
    props.powerFlowConfig.enabled ? 'power flow' :
    props.rollingConfig.enabled ? 'rolling horizon' :
    props.stochasticConfig.enabled ? 'stochastic mode' :
    props.pathwayConfig.enabled ? 'pathway mode' :
    props.sclopfConfig.enabled ? 'security-constrained (SCLOPF)' :
    props.samplingConfig.enabled ? 'sampled snapshot blocks' : '';
  const blocked = blockReason !== '';

  const set = (patch: Partial<MarketSimConfig>) =>
    props.onMarketSimConfigChange({ ...cfg, ...patch });

  return (
    <section className="constraints-workspace-section">
      <header className="constraints-workspace-section-header">
        <h3>Market simulation</h3>
        <p>
          Step the market through the horizon under explicit rules — generators
          bid their marginal cost into a single-zone merit order, the marginal
          unit sets the price, storage arbitrages a price threshold. Not an
          optimisation: it shows what the <em>rules</em> produce, including who
          sets the price and what each unit earns.
        </p>
      </header>

      <div className="sg-setting-row">
        <label className="sg-setting-label">Mode</label>
        <div className="sg-btn-row">
          <button
            className={`tb-btn sg-solver-btn${!cfg.enabled ? '' : ' tb-btn--muted'}`}
            onClick={() => set({ enabled: false })}
          >
            Off (optimise)
          </button>
          <button
            className={`tb-btn sg-solver-btn${cfg.enabled ? '' : ' tb-btn--muted'}`}
            disabled={blocked}
            title={blocked ? `Disable ${blockReason} to enable the market simulation` : undefined}
            onClick={() => set({ enabled: true })}
          >
            On
          </button>
        </div>
        {blocked && (
          <p className="sg-setting-hint" style={{ color: 'var(--danger, #dc2626)' }}>
            <strong>Disable {blockReason} to enable the market simulation.</strong>
          </p>
        )}
      </div>

      {cfg.enabled && (
        <>
          <div className="sg-setting-divider" />
          <div className="sg-setting-row">
            <label className="sg-setting-label">Settlement</label>
            <div className="sg-btn-row">
              <button
                className={`tb-btn sg-solver-btn${cfg.pricing === 'uniform' ? '' : ' tb-btn--muted'}`}
                onClick={() => set({ pricing: 'uniform' })}
              >
                Uniform price
              </button>
              <button
                className={`tb-btn sg-solver-btn${cfg.pricing === 'payAsBid' ? '' : ' tb-btn--muted'}`}
                onClick={() => set({ pricing: 'payAsBid' })}
              >
                Pay as bid
              </button>
            </div>
            <p className="sg-setting-hint">
              {cfg.pricing === 'uniform'
                ? 'Every dispatched unit is paid the clearing price (the marginal bid).'
                : 'Every dispatched unit is paid its own bid — inframarginal rent disappears.'}
            </p>
          </div>
          <div className="sg-setting-row">
            <label className="sg-setting-label">Value of lost load (per MWh)</label>
            <input
              type="number"
              className="sg-number-input"
              min={0}
              step={100}
              value={cfg.voll}
              onChange={(e) => set({ voll: Math.max(0, Number(e.target.value) || 0) })}
            />
            <p className="sg-setting-hint">Price applied in hours where demand cannot be met.</p>
          </div>
          <div className="sg-setting-row">
            <label className="sg-setting-label">Storage rule (price quantiles)</label>
            <div className="sg-btn-row" style={{ gap: 8 }}>
              <input
                type="number" className="sg-number-input" min={0} max={1} step={0.05}
                value={cfg.chargeQuantile}
                onChange={(e) => set({ chargeQuantile: Math.min(1, Math.max(0, Number(e.target.value) || 0)) })}
              />
              <input
                type="number" className="sg-number-input" min={0} max={1} step={0.05}
                value={cfg.dischargeQuantile}
                onChange={(e) => set({ dischargeQuantile: Math.min(1, Math.max(0, Number(e.target.value) || 0)) })}
              />
            </div>
            <p className="sg-setting-hint">
              Charge in hours priced at/below the first quantile, discharge at/above the
              second. Storage stays idle when the spread cannot pay for round-trip losses.
            </p>
          </div>
        </>
      )}
    </section>
  );
}
