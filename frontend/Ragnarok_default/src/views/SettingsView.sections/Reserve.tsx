/**
 * Operating-reserve section — spinning-reserve co-optimization.
 */
import React from 'react';
import {
  PathwayConfig,
  ReserveConfig,
  RollingHorizonConfig,
  StochasticConfig,
} from 'lib/types';

export interface ReserveSectionProps {
  reserveConfig: ReserveConfig;
  onReserveConfigChange: (config: ReserveConfig) => void;
  rollingConfig: RollingHorizonConfig;
  stochasticConfig: StochasticConfig;
  pathwayConfig: PathwayConfig;
}

export function ReserveSection(props: ReserveSectionProps) {
  const cfg = props.reserveConfig;
  const set = (patch: Partial<ReserveConfig>) => props.onReserveConfigChange({ ...cfg, ...patch });

  const blocked = props.rollingConfig.enabled || props.stochasticConfig.enabled || props.pathwayConfig.enabled;
  const blockReason =
    props.rollingConfig.enabled ? 'rolling horizon' :
    props.stochasticConfig.enabled ? 'stochastic mode' :
    props.pathwayConfig.enabled ? 'pathway mode' : '';

  const showFraction = cfg.requirementType === 'fraction' || cfg.requirementType === 'both';

  return (
    <section className="constraints-workspace-section">
      <header className="constraints-workspace-section-header">
        <h3>Operating reserve</h3>
        <p>
          Co-optimizes energy and spinning reserve: units keep headroom so the
          system can cover a contingency. Surfaces a reserve price ($/MW).
          Copper-plate reserve requirement (single zone).
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
            title={blocked ? `Disable ${blockReason} to enable operating reserve` : undefined}
            onClick={() => set({ enabled: true })}
          >
            On
          </button>
        </div>
        {blocked && (
          <p className="sg-setting-hint" style={{ color: 'var(--danger, #dc2626)' }}>
            <strong>Disable {blockReason} to enable operating reserve.</strong>
          </p>
        )}
      </div>

      {cfg.enabled && (
        <>
          <div className="sg-setting-divider" />
          <div className="sg-setting-row">
            <label className="sg-setting-label">Requirement</label>
            <div className="sg-btn-row">
              <button
                className={`tb-btn sg-solver-btn${cfg.requirementType === 'fraction' ? '' : ' tb-btn--muted'}`}
                onClick={() => set({ requirementType: 'fraction' })}
              >
                Fraction of demand
              </button>
              <button
                className={`tb-btn sg-solver-btn${cfg.requirementType === 'largestUnit' ? '' : ' tb-btn--muted'}`}
                onClick={() => set({ requirementType: 'largestUnit' })}
              >
                Largest unit (N-1)
              </button>
              <button
                className={`tb-btn sg-solver-btn${cfg.requirementType === 'both' ? '' : ' tb-btn--muted'}`}
                onClick={() => set({ requirementType: 'both' })}
              >
                Both
              </button>
            </div>
            <p className="sg-setting-hint">
              {cfg.requirementType === 'largestUnit'
                ? 'Reserve must cover the single largest committed unit — the classic N-1 spinning-reserve rule.'
                : cfg.requirementType === 'both'
                  ? 'Reserve must cover both the demand fraction and the largest committed unit (the binding one at each snapshot).'
                  : 'Reserve held is a fixed share of system demand at every snapshot.'}
            </p>
          </div>

          {showFraction && (
            <div className="sg-setting-row">
              <label className="sg-setting-label">Fraction of demand (%)</label>
              <input
                type="number"
                className="sg-number-input"
                min={0}
                max={100}
                step={1}
                value={Math.round(cfg.fraction * 100)}
                onChange={(e) => set({ fraction: Math.min(1, Math.max(0, (Number(e.target.value) || 0) / 100)) })}
              />
              <p className="sg-setting-hint">Share of demand held as spinning reserve.</p>
            </div>
          )}

          <div className="sg-setting-row">
            <label className="sg-setting-label">Providers</label>
            <div className="sg-btn-row">
              <button
                className={`tb-btn sg-solver-btn${cfg.providers === 'all' ? '' : ' tb-btn--muted'}`}
                onClick={() => set({ providers: 'all' })}
              >
                All units
              </button>
              <button
                className={`tb-btn sg-solver-btn${cfg.providers === 'thermal' ? '' : ' tb-btn--muted'}`}
                onClick={() => set({ providers: 'thermal' })}
              >
                Thermal only
              </button>
            </div>
            <p className="sg-setting-hint">
              {cfg.providers === 'thermal'
                ? 'Variable renewables are excluded from eligible reserve providers.'
                : 'Any generator with spare headroom can hold reserve.'}
            </p>
          </div>

          <div className="sg-setting-row">
            <label className="sg-setting-label">Reserve cost ({'$'}/MW)</label>
            <input
              type="number"
              className="sg-number-input"
              min={0}
              step={1}
              value={cfg.reserveCost}
              onChange={(e) => set({ reserveCost: Math.max(0, Number(e.target.value) || 0) })}
            />
            <p className="sg-setting-hint">Advanced: added to the objective per MW of reserve held. Usually 0.</p>
          </div>
        </>
      )}
    </section>
  );
}
