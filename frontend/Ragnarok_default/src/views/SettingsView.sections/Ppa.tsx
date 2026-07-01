/**
 * PPA contract section (PP1) — value a fixed-price PPA against the run.
 *
 * Attach a strike price to an owner's generation (or a flat MW block) and settle
 * it against the run's spot price as a Contract-for-Difference. Pure read on the
 * solved network's LMP — no re-solve, so it composes with any run mode.
 */
import React from 'react';
import { PpaConfig } from 'lib/types';

export interface PpaSectionProps {
  ppaConfig: PpaConfig;
  onPpaConfigChange: (config: PpaConfig) => void;
  merchantOwners: string[];
  ownerColumn: string;
}

export function PpaSection(props: PpaSectionProps) {
  const cfg = props.ppaConfig;
  const owners = props.merchantOwners;
  const set = (patch: Partial<PpaConfig>) => props.onPpaConfigChange({ ...cfg, ...patch });
  const num = (v: string, f: (n: number) => void) => { const n = parseFloat(v); if (Number.isFinite(n)) f(n); };

  return (
    <section className="constraints-workspace-section">
      <header className="constraints-workspace-section-header">
        <h3>PPA contract</h3>
        <p>
          Value a fixed-price power purchase agreement against the run's spot
          price (LMP). The physical energy still clears at spot; the PPA is a
          Contract-for-Difference on top, settling <code>(strike − spot) × volume</code>{' '}
          to the seller. The seller gains when the strike beats spot (a price
          floor); the buyer gains when spot beats the strike (a price cap).
        </p>
      </header>

      <div className="sg-setting-row">
        <label className="sg-setting-label">Mode</label>
        <div className="sg-btn-row">
          <button className={`tb-btn sg-solver-btn${!cfg.enabled ? '' : ' tb-btn--muted'}`} onClick={() => set({ enabled: false })}>Off</button>
          <button className={`tb-btn sg-solver-btn${cfg.enabled ? '' : ' tb-btn--muted'}`} onClick={() => set({ enabled: true })}>Value PPA</button>
        </div>
        <p className="sg-setting-hint">A read on the solved network's prices — composes with any run mode.</p>
      </div>

      {cfg.enabled && (
        <>
          <div className="sg-setting-divider" />
          <div className="sg-setting-row">
            <label className="sg-setting-label">Volume</label>
            <div className="sg-btn-row">
              <button
                className={`tb-btn sg-solver-btn${cfg.volumeType === 'generation' ? '' : ' tb-btn--muted'}`}
                onClick={() => set({ volumeType: 'generation' })}
              >
                Owner generation
              </button>
              <button
                className={`tb-btn sg-solver-btn${cfg.volumeType === 'flat' ? '' : ' tb-btn--muted'}`}
                onClick={() => set({ volumeType: 'flat' })}
              >
                Flat block
              </button>
            </div>
            <p className="sg-setting-hint">
              {cfg.volumeType === 'generation'
                ? "The owner's hourly output, each unit priced at its own bus LMP (a generation PPA)."
                : 'A constant MW block priced at the mean nodal price (a baseload block PPA).'}
            </p>
          </div>

          {cfg.volumeType === 'generation' ? (
            <div className="sg-setting-row">
              <label className="sg-setting-label" htmlFor="rs-ppa-owner">Owner</label>
              {owners.length > 0 ? (
                <select id="rs-ppa-owner" className="sg-num-input" value={cfg.owner} onChange={(e) => set({ owner: e.target.value })}>
                  <option value="">Select an owner…</option>
                  {owners.map((o) => <option key={o} value={o}>{o}</option>)}
                </select>
              ) : (
                <input id="rs-ppa-owner" type="text" className="sg-num-input" placeholder="Owner tag" value={cfg.owner} onChange={(e) => set({ owner: e.target.value })} />
              )}
              <p className="sg-setting-hint">
                {owners.length > 0
                  ? `${owners.length} distinct value${owners.length === 1 ? '' : 's'} in “${props.ownerColumn || 'owner'}” (set in Company settings).`
                  : `No values found in “${props.ownerColumn || 'owner'}” — set the owner column in Company settings and tag assets in the Model grid.`}
              </p>
            </div>
          ) : (
            <div className="sg-setting-row">
              <label className="sg-setting-label" htmlFor="rs-ppa-mw">Block size (MW)</label>
              <input id="rs-ppa-mw" type="number" min={0} step={1} className="sg-num-input" value={cfg.flatMW} onChange={(e) => num(e.target.value, (n) => set({ flatMW: Math.max(0, n) }))} />
              <p className="sg-setting-hint">A constant round-the-clock block over every snapshot.</p>
            </div>
          )}

          <div className="sg-setting-row">
            <label className="sg-setting-label" htmlFor="rs-ppa-strike">Strike price (/MWh)</label>
            <input id="rs-ppa-strike" type="number" min={0} step={1} className="sg-num-input" value={cfg.strikePrice} onChange={(e) => num(e.target.value, (n) => set({ strikePrice: Math.max(0, n) }))} />
            <p className="sg-setting-hint">The contract price. Compared against the volume-weighted average spot price.</p>
          </div>
        </>
      )}
    </section>
  );
}
