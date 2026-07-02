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
  StrategicBiddingConfig,
} from 'lib/types';

const DEFAULT_STRATEGIC: StrategicBiddingConfig = {
  enabled: false, owner: '', strategy: 'markup',
  maxAdder: 100, maxWithholdPct: 0.5, steps: 12, rivalOwner: '', rounds: 4,
};

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
  const strategic = cfg.strategic ?? DEFAULT_STRATEGIC;
  const setStrategic = (patch: Partial<StrategicBiddingConfig>) =>
    set({ strategic: { ...strategic, ...patch } });

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

          <div className="sg-setting-divider" />
          <div className="sg-setting-row">
            <label className="sg-setting-label">Strategic bidding (market power)</label>
            <div className="sg-btn-row">
              <button
                className={`tb-btn sg-solver-btn${!strategic.enabled ? '' : ' tb-btn--muted'}`}
                onClick={() => setStrategic({ enabled: false })}
              >
                Off
              </button>
              <button
                className={`tb-btn sg-solver-btn${strategic.enabled ? '' : ' tb-btn--muted'}`}
                onClick={() => setStrategic({ enabled: true })}
              >
                On
              </button>
            </div>
            <p className="sg-setting-hint">
              Sweep one owner's strategy against the simulated market and take the
              profit-maximising level (the best response) — showing what market power is
              worth and what it costs consumers. Uses the shared owner column.
            </p>
          </div>

          {strategic.enabled && (
            <>
              <div className="sg-setting-row">
                <label className="sg-setting-label">Strategic owner</label>
                <input
                  type="text" className="sg-text-input" value={strategic.owner}
                  placeholder="owner value, e.g. AlphaCo"
                  onChange={(e) => setStrategic({ owner: e.target.value })}
                />
              </div>
              <div className="sg-setting-row">
                <label className="sg-setting-label">Strategy</label>
                <div className="sg-btn-row">
                  <button
                    className={`tb-btn sg-solver-btn${strategic.strategy === 'markup' ? '' : ' tb-btn--muted'}`}
                    onClick={() => setStrategic({ strategy: 'markup' })}
                  >
                    Bid markup
                  </button>
                  <button
                    className={`tb-btn sg-solver-btn${strategic.strategy === 'withhold' ? '' : ' tb-btn--muted'}`}
                    onClick={() => setStrategic({ strategy: 'withhold' })}
                  >
                    Withhold capacity
                  </button>
                </div>
              </div>
              <div className="sg-setting-row">
                <label className="sg-setting-label">
                  {strategic.strategy === 'markup' ? 'Max bid adder (per MWh)' : 'Max withheld fraction'}
                </label>
                <div className="sg-btn-row" style={{ gap: 8 }}>
                  {strategic.strategy === 'markup' ? (
                    <input
                      type="number" className="sg-number-input" min={0} step={10}
                      value={strategic.maxAdder}
                      onChange={(e) => setStrategic({ maxAdder: Math.max(0, Number(e.target.value) || 0) })}
                    />
                  ) : (
                    <input
                      type="number" className="sg-number-input" min={0} max={1} step={0.05}
                      value={strategic.maxWithholdPct}
                      onChange={(e) => setStrategic({ maxWithholdPct: Math.min(1, Math.max(0, Number(e.target.value) || 0)) })}
                    />
                  )}
                  <input
                    type="number" className="sg-number-input" min={2} max={40} step={1}
                    value={strategic.steps}
                    onChange={(e) => setStrategic({ steps: Math.max(2, Math.trunc(Number(e.target.value) || 12)) })}
                  />
                </div>
                <p className="sg-setting-hint">Grid top and number of strategy levels swept.</p>
              </div>
              <div className="sg-setting-row">
                <label className="sg-setting-label">Rival owner (optional)</label>
                <input
                  type="text" className="sg-text-input" value={strategic.rivalOwner}
                  placeholder="empty = single strategic owner"
                  onChange={(e) => setStrategic({ rivalOwner: e.target.value })}
                />
                <p className="sg-setting-hint">
                  With a rival, both owners alternate best responses (≈ Nash equilibrium).
                </p>
              </div>
            </>
          )}
        </>
      )}
    </section>
  );
}
