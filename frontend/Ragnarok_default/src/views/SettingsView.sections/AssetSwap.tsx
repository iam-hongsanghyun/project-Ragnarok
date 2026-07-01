/**
 * Asset-swap section (DW2) — repowering what-if.
 *
 * Choose which generators to retire with one or more attribute filters (carrier,
 * company/owner, bus, …) — matched on ALL filters — and a replacement carrier;
 * the run solves before vs after and reports the emissions / cost / payback
 * delta. Mutually exclusive with the LP-reshaping modes.
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
  WorkbookModel,
} from 'lib/types';
import { stringValue } from 'lib/utils/helpers';
import { SearchableSelect } from '../../shared/components/SearchableSelect';
import { SearchableMultiSelect } from '../../shared/components/SearchableMultiSelect';

export interface AssetSwapSectionProps {
  assetSwapConfig: AssetSwapConfig;
  onAssetSwapConfigChange: (config: AssetSwapConfig) => void;
  modelCarriers: string[];
  model: WorkbookModel;
  rollingConfig: RollingHorizonConfig;
  stochasticConfig: StochasticConfig;
  samplingConfig: SamplingConfig;
  sclopfConfig: SecurityConstrainedConfig;
  powerFlowConfig: PowerFlowConfig;
  contingencyConfig: ContingencyConfig;
}

const PREFERRED_FIELDS = ['carrier', 'owner', 'bus', 'type'];

export function AssetSwapSection(props: AssetSwapSectionProps) {
  const cfg = props.assetSwapConfig;
  const carriers = props.modelCarriers;
  const gens = props.model.generators ?? [];

  // Filterable generator columns (preferred first, then the rest alphabetically).
  const fieldSet = new Set<string>();
  for (const row of gens) for (const k of Object.keys(row)) if (k !== 'name') fieldSet.add(k);
  const fields = [
    ...PREFERRED_FIELDS.filter((f) => fieldSet.has(f)),
    ...Array.from(fieldSet).filter((f) => !PREFERRED_FIELDS.includes(f)).sort(),
  ];
  const valuesOf = (field: string): string[] => {
    const seen: string[] = [];
    for (const row of gens) {
      const v = stringValue(row[field]).trim();
      if (v && !seen.includes(v)) seen.push(v);
    }
    return seen;
  };

  const blockReason =
    props.rollingConfig.enabled ? 'rolling horizon' :
    props.stochasticConfig.enabled ? 'stochastic mode' :
    props.sclopfConfig.enabled ? 'security-constrained (SCLOPF)' :
    props.samplingConfig.enabled ? 'sampled snapshot blocks' :
    props.powerFlowConfig.enabled ? 'power flow' :
    props.contingencyConfig.enabled ? 'N-1 contingency' : '';
  const blocked = blockReason !== '';
  const set = (patch: Partial<AssetSwapConfig>) => props.onAssetSwapConfigChange({ ...cfg, ...patch });
  const filters = cfg.removeFilters ?? [];
  const updateFilter = (i: number, next: { field: string; values: string[] }) =>
    set({ removeFilters: filters.map((f, idx) => (idx === i ? next : f)) });
  const addFilter = () => set({ removeFilters: [...filters, { field: fields[0] ?? 'carrier', values: [] }] });
  const removeFilter = (i: number) => set({ removeFilters: filters.filter((_, idx) => idx !== i) });
  const addExists = carriers.includes(cfg.addCarrier);

  return (
    <section className="constraints-workspace-section">
      <header className="constraints-workspace-section-header">
        <h3>Asset swap (repowering)</h3>
        <p>
          Retire the generators matching your filters and replace them,
          capacity-for-capacity, with another carrier — e.g. gas → solar, or just
          one company’s coal. The run solves before vs after and reports the delta:
          emissions, operating cost, total system cost, replacement capex, payback.
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
          <div className="sg-setting-row chart-control-row--stack">
            <span className="sg-setting-label">Retire generators matching</span>
            <div className="pivot-filters">
              {filters.map((f, i) => (
                <div className="pivot-filter-row" key={i}>
                  <SearchableSelect
                    className="pivot-filter-field"
                    value={f.field}
                    options={fields}
                    onChange={(v) => updateFilter(i, { field: v, values: [] })}
                  />
                  <SearchableMultiSelect
                    className="pivot-filter-val"
                    values={f.values}
                    options={valuesOf(f.field)}
                    placeholder="any value"
                    onChange={(vals) => updateFilter(i, { ...f, values: vals })}
                  />
                  <button type="button" className="pivot-filter-x" onClick={() => removeFilter(i)} aria-label="Remove filter">×</button>
                </div>
              ))}
              <button type="button" className="tb-btn pivot-filter-add" onClick={addFilter}>+ Add filter</button>
            </div>
            <p className="sg-setting-hint">
              Generators matching <strong>all</strong> filters are retired (a value list matches any of them).
              No filters = nothing retired.
            </p>
          </div>

          <div className="sg-setting-row">
            <label className="sg-setting-label" htmlFor="rs-swap-add">Replace with</label>
            {carriers.length > 0 ? (
              <select id="rs-swap-add" className="sg-num-input" value={cfg.addCarrier} onChange={(e) => set({ addCarrier: e.target.value })}>
                <option value="">Select replacement carrier…</option>
                {carriers.map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
            ) : (
              <input id="rs-swap-add" type="text" className="sg-num-input" placeholder="carrier" value={cfg.addCarrier} onChange={(e) => set({ addCarrier: e.target.value })} />
            )}
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
