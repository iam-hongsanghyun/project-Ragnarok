/**
 * Convergence-controlled sampling + maintenance placement section — reliability run mode.
 */
import React, { useState } from 'react';
import { ConvergenceConfig } from 'lib/types';

export interface ConvergenceSectionProps {
  convergenceConfig: ConvergenceConfig;
  onConvergenceConfigChange: (config: ConvergenceConfig) => void;
}

export function ConvergenceSection(props: ConvergenceSectionProps) {
  const cfg = props.convergenceConfig;
  const set = (patch: Partial<ConvergenceConfig>) => props.onConvergenceConfigChange({ ...cfg, ...patch });
  const [carriersText, setCarriersText] = useState(() => cfg.maintenanceCarriers.join(', '));

  const commitMaintenanceCarriers = (text: string) => {
    const maintenanceCarriers = text.split(',').map((c) => c.trim()).filter((c) => c.length > 0);
    set({ maintenanceCarriers });
  };

  return (
    <section className="constraints-workspace-section">
      <header className="constraints-workspace-section-header">
        <h3>Convergence sampling</h3>
        <p>
          Draws the forced-outage Monte Carlo in batches until the target
          reliability metric's standard error converges — a defensible sample
          count instead of a fixed guess. Optional maintenance placement
          schedules planned outages into low-load windows and folds them into
          the risk.
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
            <label className="sg-setting-label">Target metric</label>
            <div className="sg-btn-row">
              <button
                className={`tb-btn sg-solver-btn${cfg.targetMetric === 'eue' ? '' : ' tb-btn--muted'}`}
                onClick={() => set({ targetMetric: 'eue' })}
              >
                EUE
              </button>
              <button
                className={`tb-btn sg-solver-btn${cfg.targetMetric === 'lole' ? '' : ' tb-btn--muted'}`}
                onClick={() => set({ targetMetric: 'lole' })}
              >
                LOLE
              </button>
            </div>
            <p className="sg-setting-hint">Reliability metric whose standard error drives the stopping rule.</p>
          </div>

          <div className="sg-setting-row">
            <label className="sg-setting-label">Tolerance (%)</label>
            <input
              type="number"
              className="sg-number-input"
              min={0.5}
              max={50}
              step={0.5}
              value={Math.round(cfg.tolerance * 1000) / 10}
              onChange={(e) => set({ tolerance: Math.min(1, Math.max(0.005, (Number(e.target.value) || 0) / 100)) })}
            />
            <p className="sg-setting-hint">Relative standard error at which sampling stops.</p>
          </div>

          <div className="sg-setting-row">
            <label className="sg-setting-label">Batch size</label>
            <input
              type="number"
              className="sg-number-input"
              min={10}
              max={1000}
              step={10}
              value={cfg.batchSize}
              onChange={(e) => set({ batchSize: Math.min(1000, Math.max(10, Number(e.target.value) || 0)) })}
            />
            <p className="sg-setting-hint">Samples drawn per batch before re-checking convergence.</p>
          </div>

          <div className="sg-setting-row">
            <label className="sg-setting-label">Max members</label>
            <input
              type="number"
              className="sg-number-input"
              min={50}
              max={20000}
              step={50}
              value={cfg.maxMembers}
              onChange={(e) => set({ maxMembers: Math.min(20000, Math.max(50, Number(e.target.value) || 0)) })}
            />
            <p className="sg-setting-hint">Hard cap on total samples even if the metric hasn't converged.</p>
          </div>

          <div className="sg-setting-row">
            <label className="sg-setting-label">Random seed</label>
            <input
              type="number"
              className="sg-number-input"
              step={1}
              value={cfg.seed}
              onChange={(e) => set({ seed: Number(e.target.value) || 0 })}
            />
            <p className="sg-setting-hint">Fixed seed makes the ensemble reproducible.</p>
          </div>

          <div className="sg-setting-divider" />
          <div className="sg-setting-row">
            <label className="sg-setting-label">Forced outage rate (%)</label>
            <input
              type="number"
              className="sg-number-input"
              min={0}
              max={100}
              step={0.5}
              value={Math.round(cfg.forcedOutageRate * 1000) / 10}
              onChange={(e) => set({ forcedOutageRate: Math.min(1, Math.max(0, (Number(e.target.value) || 0) / 100)) })}
            />
            <p className="sg-setting-hint">EFOR fallback applied to generators without an explicit forced-outage rate.</p>
          </div>

          <div className="sg-setting-row">
            <label className="sg-setting-label">Mean time to repair (h)</label>
            <input
              type="number"
              className="sg-number-input"
              min={0}
              step={1}
              value={cfg.mttrHours}
              onChange={(e) => set({ mttrHours: Math.max(0, Number(e.target.value) || 0) })}
            />
            <p className="sg-setting-hint">Average hours a unit stays down once it forces an outage.</p>
          </div>

          <div className="sg-setting-divider" />
          <div className="sg-setting-row">
            <label className="sg-setting-label">Maintenance placement</label>
            <div className="sg-btn-row">
              <button
                className={`tb-btn sg-solver-btn${!cfg.maintenanceEnabled ? '' : ' tb-btn--muted'}`}
                onClick={() => set({ maintenanceEnabled: false })}
              >
                Off
              </button>
              <button
                className={`tb-btn sg-solver-btn${cfg.maintenanceEnabled ? '' : ' tb-btn--muted'}`}
                onClick={() => set({ maintenanceEnabled: true })}
              >
                On
              </button>
            </div>
            <p className="sg-setting-hint">Schedules planned outages into low-load windows and folds them into the risk.</p>
          </div>

          {cfg.maintenanceEnabled && (
            <>
              <div className="sg-setting-row">
                <label className="sg-setting-label">Maintenance length (weeks)</label>
                <input
                  type="number"
                  className="sg-number-input"
                  min={1}
                  max={52}
                  step={1}
                  value={cfg.maintenanceWeeks}
                  onChange={(e) => set({ maintenanceWeeks: Math.min(52, Math.max(1, Number(e.target.value) || 0)) })}
                />
                <p className="sg-setting-hint">Duration of each planned maintenance outage.</p>
              </div>

              <div className="sg-setting-row">
                <label className="sg-setting-label">Maintenance carriers</label>
                <input
                  type="text"
                  className="sg-text-input"
                  value={carriersText}
                  placeholder="Auto"
                  onChange={(e) => setCarriersText(e.target.value)}
                  onBlur={(e) => commitMaintenanceCarriers(e.target.value)}
                />
                <p className="sg-setting-hint">
                  Comma-separated carrier names to schedule maintenance for. Empty = auto.
                </p>
              </div>
            </>
          )}
        </>
      )}
    </section>
  );
}
