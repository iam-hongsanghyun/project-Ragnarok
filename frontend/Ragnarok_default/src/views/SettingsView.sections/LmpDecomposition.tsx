/**
 * LMP decomposition section — post-process that splits each bus's locational
 * marginal price into an energy component and a congestion premium.
 */
import React from 'react';
import { LmpDecompositionConfig } from 'lib/types';

export interface LmpDecompositionSectionProps {
  lmpDecompositionConfig: LmpDecompositionConfig;
  onLmpDecompositionConfigChange: (config: LmpDecompositionConfig) => void;
}

export function LmpDecompositionSection(props: LmpDecompositionSectionProps) {
  const cfg = props.lmpDecompositionConfig;
  const set = (patch: Partial<LmpDecompositionConfig>) => props.onLmpDecompositionConfigChange({ ...cfg, ...patch });

  return (
    <section className="constraints-workspace-section">
      <header className="constraints-workspace-section-header">
        <h3>LMP decomposition</h3>
        <p>
          Splits each bus's locational marginal price into an energy component
          (uniform) and a congestion premium, and reports congestion rent per
          line.
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
            onClick={() => set({ enabled: true })}
          >
            On
          </button>
        </div>
      </div>

      {cfg.enabled && (
        <>
          <div className="sg-setting-divider" />
          <div className="sg-setting-row">
            <label className="sg-setting-label">Reference mode</label>
            <div className="sg-btn-row">
              <button
                className={`tb-btn sg-solver-btn${cfg.referenceMode === 'load-weighted' ? '' : ' tb-btn--muted'}`}
                onClick={() => set({ referenceMode: 'load-weighted' })}
              >
                Load-weighted
              </button>
              <button
                className={`tb-btn sg-solver-btn${cfg.referenceMode === 'min' ? '' : ' tb-btn--muted'}`}
                onClick={() => set({ referenceMode: 'min' })}
              >
                Minimum LMP
              </button>
              <button
                className={`tb-btn sg-solver-btn${cfg.referenceMode === 'bus' ? '' : ' tb-btn--muted'}`}
                onClick={() => set({ referenceMode: 'bus' })}
              >
                Reference bus
              </button>
            </div>
            <p className="sg-setting-hint">
              {cfg.referenceMode === 'load-weighted' && 'Load-weighted (system energy price).'}
              {cfg.referenceMode === 'min' && 'Minimum LMP (cheapest bus = energy).'}
              {cfg.referenceMode === 'bus' && 'Reference bus.'}
            </p>
          </div>

          {cfg.referenceMode === 'bus' && (
            <div className="sg-setting-row">
              <label className="sg-setting-label">Reference bus</label>
              <input
                type="text"
                className="sg-text-input"
                value={cfg.referenceBus}
                placeholder="Bus name"
                onChange={(e) => set({ referenceBus: e.target.value })}
                onBlur={(e) => set({ referenceBus: e.target.value.trim() })}
              />
              <p className="sg-setting-hint">Bus whose LMP is used as the energy-price reference.</p>
            </div>
          )}
        </>
      )}
    </section>
  );
}
