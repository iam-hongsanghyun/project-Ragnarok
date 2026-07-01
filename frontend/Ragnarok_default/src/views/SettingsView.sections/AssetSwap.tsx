/**
 * Asset-swap section (DW2) — repowering what-if.
 *
 * Retire one carrier and replace it, capacity-for-capacity, with another; the
 * run solves before vs after and reports the emissions / cost / payback delta.
 * The replacement inherits the target carrier's cost and availability if that
 * carrier already exists; otherwise the costs below are used. Mutually exclusive
 * with the LP-reshaping modes.
 */
import React from 'react';
import {
  AssetSwapConfig,
  ContingencyConfig,
  PowerFlowConfig,
  RollingHorizonConfig,
  SamplingConfig,
  SecurityConstrainedConfig,
  StochasticConfig,
} from 'lib/types';

export interface AssetSwapSectionProps {
  assetSwapConfig: AssetSwapConfig;
  onAssetSwapConfigChange: (config: AssetSwapConfig) => void;
  modelCarriers: string[];
  rollingConfig: RollingHorizonConfig;
  stochasticConfig: StochasticConfig;
  samplingConfig: SamplingConfig;
  sclopfConfig: SecurityConstrainedConfig;
  powerFlowConfig: PowerFlowConfig;
  contingencyConfig: ContingencyConfig;
}

export function AssetSwapSection(props: AssetSwapSectionProps) {
  const cfg = props.assetSwapConfig;
  const carriers = props.modelCarriers;
  const blockReason =
    props.rollingConfig.enabled ? 'rolling horizon' :
    props.stochasticConfig.enabled ? 'stochastic mode' :
    props.sclopfConfig.enabled ? 'security-constrained (SCLOPF)' :
    props.samplingConfig.enabled ? 'sampled snapshot blocks' :
    props.powerFlowConfig.enabled ? 'power flow' :
    props.contingencyConfig.enabled ? 'N-1 contingency' : '';
  const blocked = blockReason !== '';
  const set = (patch: Partial<AssetSwapConfig>) => props.onAssetSwapConfigChange({ ...cfg, ...patch });
  const addExists = carriers.includes(cfg.addCarrier);

  const carrierSelect = (value: string, onChange: (v: string) => void, id: string, placeholder: string) => (
    carriers.length > 0 ? (
      <select id={id} className="sg-num-input" value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">{placeholder}</option>
        {carriers.map((c) => <option key={c} value={c}>{c}</option>)}
      </select>
    ) : (
      <input id={id} type="text" className="sg-num-input" placeholder="carrier" value={value} onChange={(e) => onChange(e.target.value)} />
    )
  );

  return (
    <section className="constraints-workspace-section">
      <header className="constraints-workspace-section-header">
        <h3>Asset swap (repowering)</h3>
        <p>
          Retire a carrier and replace it, capacity-for-capacity, with another —
          e.g. gas → solar. The run solves the system before and after and reports
          the delta: emissions, operating cost, total system cost, the
          replacement's capex, and a simple payback. The decision as a number.
        </p>
      </header>

      <div className="sg-setting-row">
        <label className="sg-setting-label">Mode</label>
        <div className="sg-btn-row">
          <button className={`tb-btn sg-solver-btn${!cfg.enabled ? '' : ' tb-btn--muted'}`} onClick={() => set({ enabled: false })}>Off</button>
          <button
            className={`tb-btn sg-solver-btn${cfg.enabled ? '' : ' tb-btn--muted'}`}
            disabled={blocked}
            title={blocked ? `Disable ${blockReason} to enable asset swap` : undefined}
            onClick={() => set({ enabled: true })}
          >
            Run what-if
          </button>
        </div>
        {blocked && (
          <p className="sg-setting-hint" style={{ color: 'var(--danger, #dc2626)' }}>
            <strong>Disable {blockReason} to enable the asset-swap what-if.</strong>
          </p>
        )}
      </div>

      {cfg.enabled && (
        <>
          <div className="sg-setting-divider" />
          <div className="sg-setting-row">
            <label className="sg-setting-label" htmlFor="rs-swap-remove">Retire carrier</label>
            {carrierSelect(cfg.removeCarrier, (v) => set({ removeCarrier: v }), 'rs-swap-remove', 'Select carrier to retire…')}
            <p className="sg-setting-hint">All generators of this carrier are removed.</p>
          </div>
          <div className="sg-setting-row">
            <label className="sg-setting-label" htmlFor="rs-swap-add">Replace with</label>
            {carrierSelect(cfg.addCarrier, (v) => set({ addCarrier: v }), 'rs-swap-add', 'Select replacement carrier…')}
            <p className="sg-setting-hint">
              {addExists
                ? 'Replacement inherits this carrier’s cost and availability from an existing unit.'
                : 'New carrier — set its costs below (units will be firm without an availability profile).'}
            </p>
          </div>

          {!addExists && cfg.addCarrier && (
            <>
              <div className="sg-setting-row">
                <label className="sg-setting-label" htmlFor="rs-swap-capex">Replacement capital cost (/MW/yr)</label>
                <input id="rs-swap-capex" type="number" min={0} step={1000} className="sg-num-input"
                  value={cfg.addCapitalCost}
                  onChange={(e) => { const v = parseFloat(e.target.value); if (Number.isFinite(v)) set({ addCapitalCost: Math.max(0, v) }); }} />
              </div>
              <div className="sg-setting-row">
                <label className="sg-setting-label" htmlFor="rs-swap-mc">Replacement marginal cost (/MWh)</label>
                <input id="rs-swap-mc" type="number" min={0} step={1} className="sg-num-input"
                  value={cfg.addMarginalCost}
                  onChange={(e) => { const v = parseFloat(e.target.value); if (Number.isFinite(v)) set({ addMarginalCost: Math.max(0, v) }); }} />
              </div>
            </>
          )}
        </>
      )}
    </section>
  );
}
