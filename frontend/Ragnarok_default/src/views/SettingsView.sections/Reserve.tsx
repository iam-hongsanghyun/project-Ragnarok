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
  const isFixed = cfg.requirementType === 'fixed';
  const spinning = Boolean(cfg.spinning);
  const storage = Boolean(cfg.includeStorageUnits);

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
              <button
                className={`tb-btn sg-solver-btn${isFixed ? '' : ' tb-btn--muted'}`}
                onClick={() => set({ requirementType: 'fixed' })}
              >
                Fixed MW
              </button>
            </div>
            <p className="sg-setting-hint">
              {cfg.requirementType === 'largestUnit'
                ? 'Reserve must cover the largest installed unit — the classic N-1 spinning-reserve rule.'
                : cfg.requirementType === 'both'
                  ? 'Reserve is the demand fraction plus the largest installed unit.'
                  : isFixed
                    ? 'Reserve held is the MW below at every snapshot (a grid code figure).'
                    : 'Reserve held is a fixed share of system demand at every snapshot.'}
            </p>
          </div>

          <div className="sg-setting-row">
            <label className="sg-setting-label">{isFixed ? 'Requirement (MW)' : 'Added fixed requirement (MW)'}</label>
            <input
              type="number"
              className="sg-number-input"
              min={0}
              step={100}
              value={cfg.requirementMw ?? 0}
              onChange={(e) => set({ requirementMw: Math.max(0, Number(e.target.value) || 0) })}
            />
            <p className="sg-setting-hint">
              {isFixed
                ? 'The whole requirement. Must be above 0.'
                : 'Added to the requirement above at every snapshot. 0 = none.'}
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
            <label className="sg-setting-label">Provider selector</label>
            <input
              type="text"
              className="sg-number-input"
              style={{ width: '18rem' }}
              placeholder="fuel=coal|lng"
              value={cfg.providerSelector ?? ''}
              onChange={(e) => set({ providerSelector: e.target.value })}
            />
            <p className="sg-setting-hint">
              Optional. Only generators it names hold reserve: column=value|value, joined by &amp;, read on the
              generators sheet (else on the generator's bus).
            </p>
          </div>

          <div className="sg-setting-row">
            <label className="sg-setting-label">Spinning rule</label>
            <div className="sg-btn-row">
              <button
                className={`tb-btn sg-solver-btn${!spinning ? '' : ' tb-btn--muted'}`}
                onClick={() => set({ spinning: false })}
              >
                Off
              </button>
              <button
                className={`tb-btn sg-solver-btn${spinning ? '' : ' tb-btn--muted'}`}
                onClick={() => set({ spinning: true, minStableLoad: cfg.minStableLoad ?? 0.4 })}
              >
                On
              </button>
            </div>
            <p className="sg-setting-hint">
              {spinning
                ? 'Only a generating unit holds reserve: at most (1 − m) / m times its output, where m is the minimum stable load. A committable unit uses its on/off status instead.'
                : 'Off: an idle unit can hold its whole rating as reserve.'}
            </p>
          </div>

          {spinning && (
            <div className="sg-setting-row">
              <label className="sg-setting-label">Minimum stable load (%)</label>
              <input
                type="number"
                className="sg-number-input"
                min={1}
                max={99}
                step={1}
                value={Math.round((cfg.minStableLoad ?? 0.4) * 100)}
                onChange={(e) => set({ minStableLoad: Math.min(0.99, Math.max(0.01, (Number(e.target.value) || 0) / 100)) })}
              />
              <p className="sg-setting-hint">
                Share of a unit's available output below which it cannot run. The generators column
                reserve_min_load_pu overrides it per unit; reserve_max_pu caps what one unit holds.
              </p>
            </div>
          )}

          <div className="sg-setting-row">
            <label className="sg-setting-label">Storage units</label>
            <div className="sg-btn-row">
              <button
                className={`tb-btn sg-solver-btn${!storage ? '' : ' tb-btn--muted'}`}
                onClick={() => set({ includeStorageUnits: false })}
              >
                Excluded
              </button>
              <button
                className={`tb-btn sg-solver-btn${storage ? '' : ' tb-btn--muted'}`}
                onClick={() => set({ includeStorageUnits: true, reserveDurationHours: cfg.reserveDurationHours ?? 1 })}
              >
                Hold reserve
              </button>
            </div>
            <p className="sg-setting-hint">
              {storage
                ? 'Fixed-size storage units hold reserve from standstill, within their discharge headroom and stored energy.'
                : 'Only generators hold reserve.'}
            </p>
          </div>

          {storage && (
            <div className="sg-setting-row">
              <label className="sg-setting-label">Reserve duration (h)</label>
              <input
                type="number"
                className="sg-number-input"
                min={0.25}
                step={0.25}
                value={cfg.reserveDurationHours ?? 1}
                onChange={(e) => set({ reserveDurationHours: Math.max(0.25, Number(e.target.value) || 1) })}
              />
              <p className="sg-setting-hint">Hours a storage unit must be able to sustain the reserve it holds.</p>
            </div>
          )}

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
