/**
 * ELCC / capacity credit section — reliability run mode.
 */
import React, { useState } from 'react';
import { ElccConfig } from 'lib/types';

export interface ElccSectionProps {
  elccConfig: ElccConfig;
  onElccConfigChange: (config: ElccConfig) => void;
}

export function ElccSection(props: ElccSectionProps) {
  const cfg = props.elccConfig;
  const set = (patch: Partial<ElccConfig>) => props.onElccConfigChange({ ...cfg, ...patch });
  const [carriersText, setCarriersText] = useState(() => cfg.carriers.join(', '));

  const commitCarriers = (text: string) => {
    const carriers = text.split(',').map((c) => c.trim()).filter((c) => c.length > 0);
    set({ carriers });
  };

  return (
    <section className="constraints-workspace-section">
      <header className="constraints-workspace-section-header">
        <h3>ELCC / capacity credit</h3>
        <p>
          Effective Load-Carrying Capability: the perfectly-firm MW each
          resource (wind/solar/storage) can replace at equal reliability
          (LOLE) — the headline capacity-accreditation metric for IRPs and
          capacity markets. Computed by binary-searching firm capacity against
          the outage-inclusive LOLE.
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
            <label className="sg-setting-label">Monte-Carlo samples</label>
            <input
              type="number"
              className="sg-number-input"
              min={50}
              max={2000}
              step={50}
              value={cfg.nMembers}
              onChange={(e) => set({ nMembers: Math.min(2000, Math.max(50, Number(e.target.value) || 0)) })}
            />
            <p className="sg-setting-hint">Number of synthetic years drawn for the outage-inclusive LOLE.</p>
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
            <p className="sg-setting-hint">EFOR fallback applied to generators without an explicit forced-outage rate — the outage backdrop against which ELCC is measured.</p>
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
            <label className="sg-setting-label">Carriers</label>
            <input
              type="text"
              className="sg-text-input"
              value={carriersText}
              placeholder="Auto (variable renewables + storage)"
              onChange={(e) => setCarriersText(e.target.value)}
              onBlur={(e) => commitCarriers(e.target.value)}
            />
            <p className="sg-setting-hint">
              Comma-separated carrier names to evaluate. Empty = auto (variable
              renewables + storage).
            </p>
          </div>
        </>
      )}
    </section>
  );
}
