/**
 * Stochastic section — two-stage planning with scenario weights.
 *
 * Each scenario is rendered by {@link ./ScenarioRow}.
 */
import React from 'react';
import {
  RollingHorizonConfig,
  StochasticConfig,
  StochasticScenarioConfig,
  WorkbookModel,
} from '../../../shared/types';
import { StochasticScenarioRow } from './ScenarioRow';

export interface StochasticSectionProps {
  stochasticConfig: StochasticConfig;
  onStochasticConfigChange: (config: StochasticConfig) => void;
  rollingConfig: RollingHorizonConfig;
  model: WorkbookModel;
}

export function StochasticSection({
  stochasticConfig: config,
  onStochasticConfigChange: onChange,
  rollingConfig,
  model,
}: StochasticSectionProps) {
  const rollingEnabled = rollingConfig.enabled;

  const update = (patch: Partial<StochasticConfig>) => onChange({ ...config, ...patch });
  const setScenarios = (scenarios: StochasticScenarioConfig[]) => update({ scenarios });

  const addScenario = () => {
    const id = `sc_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`;
    const n = config.scenarios.length + 1;
    setScenarios([
      ...config.scenarios,
      { id, name: `scenario_${n}`, weight: 0.5, overrides: [] },
    ]);
  };
  const updateScenario = (id: string, patch: Partial<StochasticScenarioConfig>) =>
    setScenarios(config.scenarios.map((s) => (s.id === id ? { ...s, ...patch } : s)));
  const removeScenario = (id: string) =>
    setScenarios(config.scenarios.filter((s) => s.id !== id));

  const totalWeight = config.scenarios.reduce((sum, s) => sum + (Number(s.weight) || 0), 0);

  return (
    <section className="constraints-workspace-section">
      <header className="constraints-workspace-section-header">
        <h3>Stochastic uncertainty</h3>
        <p>
          Two-stage stochastic planning: shared capacity decisions,
          scenario-specific dispatch. Each row gets four quick knobs;
          per-cell uncertainty drops into "Advanced overrides". Weights
          normalise to sum=1 at solve time; minimum 2 scenarios.
        </p>
      </header>
      <div className="sg-setting-row">
        <label className="sg-setting-label">Mode</label>
        <div className="sg-btn-row">
          <button
            className={`tb-btn sg-solver-btn${!config.enabled ? '' : ' tb-btn--muted'}`}
            onClick={() => update({ enabled: false })}
          >
            Off
          </button>
          <button
            className={`tb-btn sg-solver-btn${config.enabled ? '' : ' tb-btn--muted'}`}
            disabled={rollingEnabled}
            title={rollingEnabled ? 'Disable rolling horizon to enable stochastic' : undefined}
            onClick={() => update({ enabled: true })}
          >
            On
          </button>
        </div>
        {rollingEnabled && (
          <p className="sg-setting-hint" style={{ color: 'var(--danger, #dc2626)' }}>
            <strong>Rolling horizon must be off to use stochastic mode.</strong>
          </p>
        )}
      </div>
      {config.enabled && (
        <>
          <div className="sg-setting-divider" />
          {config.scenarios.map((s) => (
            <StochasticScenarioRow
              key={s.id}
              scenario={s}
              model={model}
              onUpdate={(patch) => updateScenario(s.id, patch)}
              onRemove={() => removeScenario(s.id)}
            />
          ))}
          <button className="tb-btn" onClick={addScenario}>+ Add scenario</button>
          {config.scenarios.length > 0 && (
            <p className="sg-setting-hint">
              {config.scenarios.length >= 2 ? 'Total weight ' : 'Need ≥ 2 scenarios. Total weight '}
              <strong>{totalWeight.toFixed(2)}</strong> (normalised to 1.00 on solve).
            </p>
          )}
        </>
      )}
    </section>
  );
}
