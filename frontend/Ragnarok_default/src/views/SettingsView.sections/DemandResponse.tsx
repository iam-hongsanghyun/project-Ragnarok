/**
 * Demand response section (M2) — shiftable load.
 *
 * Unlike load shedding (which drops demand at a penalty), this moves demand in
 * time while conserving total energy: each shiftable load gets an energy buffer
 * so consumption fills cheap hours and empties expensive ones. Sizing is a buffer
 * power (fraction of the load's peak) × a buffer duration.
 */
import React from 'react';
import { DemandResponseConfig, WorkbookModel } from 'lib/types';
import { SearchableMultiSelect } from '../../shared/components/SearchableMultiSelect';

export interface DemandResponseSectionProps {
  demandResponseConfig: DemandResponseConfig;
  onDemandResponseConfigChange: (config: DemandResponseConfig) => void;
  model: WorkbookModel;
}

export function DemandResponseSection(props: DemandResponseSectionProps) {
  const cfg = props.demandResponseConfig;
  const set = (patch: Partial<DemandResponseConfig>) => props.onDemandResponseConfigChange({ ...cfg, ...patch });
  const num = (v: string, f: (n: number) => void) => { const n = parseFloat(v); if (Number.isFinite(n)) f(n); };
  const pct = Math.round((cfg.shiftFraction || 0) * 100);
  const loadNames = ((props.model.loads ?? []) as Array<{ name?: unknown }>)
    .map((r) => String(r.name ?? '')).filter(Boolean);

  return (
    <section className="constraints-workspace-section">
      <header className="constraints-workspace-section-header">
        <h3>Demand response</h3>
        <p>
          Make demand <strong>shiftable</strong> in time instead of fixed. Each load gets an
          energy buffer, so the system can pre-consume in cheap hours and defer in expensive ones —
          total energy is conserved (nothing is curtailed). This is distinct from load shedding,
          which drops demand at a penalty. Modelled as a per-load buffer (an energy store on a
          demand-response bus fed by a lossless link).
        </p>
      </header>

      <div className="sg-setting-row">
        <label className="sg-setting-label">Mode</label>
        <div className="sg-btn-row">
          <button className={`tb-btn sg-solver-btn${!cfg.enabled ? '' : ' tb-btn--muted'}`} onClick={() => set({ enabled: false })}>Fixed demand</button>
          <button className={`tb-btn sg-solver-btn${cfg.enabled ? '' : ' tb-btn--muted'}`} onClick={() => set({ enabled: true })}>Shiftable</button>
        </div>
        <p className="sg-setting-hint">Move demand in time without dropping it.</p>
      </div>

      {cfg.enabled && (
        <>
          <div className="sg-setting-divider" />
          {loadNames.length > 0 && (
            <div className="sg-setting-row">
              <label className="sg-setting-label">Shiftable loads</label>
              <SearchableMultiSelect
                values={cfg.loads}
                options={loadNames}
                placeholder="All loads"
                onChange={(vals) => set({ loads: vals })}
              />
              <p className="sg-setting-hint">
                {cfg.loads.length === 0
                  ? `All ${loadNames.length} load(s) are shiftable. Pick a subset to restrict.`
                  : `${cfg.loads.length} of ${loadNames.length} load(s) shiftable.`}
              </p>
            </div>
          )}
          <div className="sg-setting-row">
            <label className="sg-setting-label" htmlFor="rs-dr-frac">Shiftable power (% of peak)</label>
            <input
              id="rs-dr-frac" type="number" min={0} max={100} step={5} className="sg-num-input"
              value={pct}
              onChange={(e) => num(e.target.value, (n) => set({ shiftFraction: Math.min(1, Math.max(0, n / 100)) }))}
            />
            <p className="sg-setting-hint">How much of each load's peak can be pre-consumed or deferred at once.</p>
          </div>

          <div className="sg-setting-row">
            <label className="sg-setting-label" htmlFor="rs-dr-hours">Buffer duration (hours)</label>
            <input
              id="rs-dr-hours" type="number" min={0.5} step={0.5} className="sg-num-input"
              value={cfg.maxShiftHours}
              onChange={(e) => num(e.target.value, (n) => set({ maxShiftHours: Math.max(0.5, n) }))}
            />
            <p className="sg-setting-hint">
              How far demand can move in time. Shiftable energy = shiftable power × duration.
            </p>
          </div>
        </>
      )}
    </section>
  );
}
