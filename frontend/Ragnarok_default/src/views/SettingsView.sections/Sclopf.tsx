/**
 * Security-constrained section — N-1 contingency dispatch.
 */
import React from 'react';
import {
  PathwayConfig,
  RollingHorizonConfig,
  SecurityConstrainedConfig,
  StochasticConfig,
  WorkbookModel,
} from 'lib/types';
import { SearchableMultiSelect } from '../../shared/components/SearchableMultiSelect';
import { useOptionFields } from './OptionRow';

export interface SclopfSectionProps {
  sclopfConfig: SecurityConstrainedConfig;
  onSclopfConfigChange: (config: SecurityConstrainedConfig) => void;
  rollingConfig: RollingHorizonConfig;
  stochasticConfig: StochasticConfig;
  pathwayConfig: PathwayConfig;
  lineCount: number;
  transformerCount: number;
  model: WorkbookModel;
}

/** `branchOutages` entry of a transformer; a bare name means a line (backend `parse_branch_outages`). */
export const TRANSFORMER_PREFIX = 'Transformer:';

const namesOf = (rows: unknown): string[] =>
  ((rows ?? []) as Array<{ name?: unknown }>).map((r) => String(r.name ?? '')).filter(Boolean);

export function SclopfSection(props: SclopfSectionProps) {
  const fields = useOptionFields('options.securityConstrainedConfig.branchOutages');
  const branchOptions = [
    ...namesOf(props.model.lines).map((n) => ({ value: n, label: `Line ${n}` })),
    ...namesOf(props.model.transformers).map((n) => ({ value: `${TRANSFORMER_PREFIX}${n}`, label: `Transformer ${n}` })),
  ];
  const outages = props.sclopfConfig.branchOutages ?? [];
  const blocked = props.rollingConfig.enabled || props.stochasticConfig.enabled || props.pathwayConfig.enabled;
  const blockReason =
    props.rollingConfig.enabled ? 'rolling horizon' :
    props.stochasticConfig.enabled ? 'stochastic mode' :
    props.pathwayConfig.enabled ? 'pathway mode' : '';

  return (
    <section className="constraints-workspace-section">
      <header className="constraints-workspace-section-header">
        <h3>Security-constrained (SCLOPF)</h3>
        <p>Dispatch must remain feasible under the outage of any single passive branch. Defaults to N-1 against every line and transformer in the network.</p>
      </header>
      <div className="sg-setting-row">
        <label className="sg-setting-label">Mode</label>
        <div className="sg-btn-row">
          <button
            className={`tb-btn sg-solver-btn${!props.sclopfConfig.enabled ? '' : ' tb-btn--muted'}`}
            onClick={() => props.onSclopfConfigChange({ ...props.sclopfConfig, enabled: false })}
          >
            Off
          </button>
          <button
            className={`tb-btn sg-solver-btn${props.sclopfConfig.enabled ? '' : ' tb-btn--muted'}`}
            disabled={blocked}
            title={blocked ? `Disable ${blockReason} to enable SCLOPF` : undefined}
            onClick={() => props.onSclopfConfigChange({ ...props.sclopfConfig, enabled: true })}
          >
            On
          </button>
        </div>
        {blocked && (
          <p className="sg-setting-hint" style={{ color: 'var(--danger, #dc2626)' }}>
            <strong>Disable {blockReason} to enable SCLOPF.</strong>
          </p>
        )}
      </div>
      {props.sclopfConfig.enabled && (
        <>
          <div className="sg-setting-divider" />
          <div className="sg-setting-row">
            <label className="sg-setting-label">N-1 coverage</label>
            <div className="sg-setting-value">
              {props.lineCount + props.transformerCount} branches
              {props.transformerCount > 0 && (
                <span style={{ color: 'var(--muted)', fontSize: '0.78rem', marginLeft: 4 }}>
                  ({props.lineCount} line{props.lineCount === 1 ? '' : 's'} + {props.transformerCount} transformer{props.transformerCount === 1 ? '' : 's'})
                </span>
              )}
            </div>
          </div>
          <div className="sg-setting-row">
            <label className="sg-setting-label">Secured branches</label>
            <SearchableMultiSelect
              values={outages}
              options={branchOptions}
              placeholder="All lines and transformers"
              onChange={(vals) => {
                const { branchOutages: _previous, ...rest } = props.sclopfConfig;
                props.onSclopfConfigChange(vals.length > 0 ? { ...rest, branchOutages: vals } : rest);
              }}
            />
            <p className="sg-setting-hint">
              {outages.length === 0
                ? `Every one of the ${branchOptions.length} passive branch(es) is secured. Pick a subset to restrict N-1 to those.`
                : `${outages.length} of ${branchOptions.length} branch(es) secured.`}
              {' '}{fields['options.securityConstrainedConfig.branchOutages']?.meaning}
            </p>
          </div>
        </>
      )}
    </section>
  );
}
