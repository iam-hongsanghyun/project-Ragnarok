/**
 * Run setup — full-width overlay that hosts every "how do I want to
 * solve this case?" knob.
 *
 * Six tabs, ordered from most-common to most-specialised:
 *   Window & weights · Multi-year planning · Rolling horizon ·
 *   Carbon price · Stochastic · SCLOPF
 *
 * Previously these were six separate sidebar groups. Concentrating them
 * here frees the sidebar for navigation and lets each editor render with
 * the horizontal space it needs (pathway period table, stochastic
 * scenario rows, etc.).
 */
import React, { useEffect, useState } from 'react';
import {
  CarbonPriceScheduleEntry,
  PathwayConfig,
  RollingHorizonConfig,
  SecurityConstrainedConfig,
  StochasticConfig,
  StochasticScenarioConfig,
  StochasticScenarioOverride,
  WorkbookModel,
} from '../../shared/types';
import { PYPSA_COMPONENTS } from '../../constants/pypsa_schema';
import { stringValue } from '../../shared/utils/helpers';
import { DualRangeSlider } from '../../shared/components/DualRangeSlider';
import { normalizeRollingConfig } from '../../shared/utils/rolling';
import { RUN_WINDOW, SETTINGS_CONFIG } from '../../constants';

type Tab = 'window' | 'planning' | 'rolling' | 'carbon' | 'stochastic' | 'sclopf';

interface Props {
  pathwayConfig: PathwayConfig;
  onPathwayConfigChange: (config: PathwayConfig) => void;
  rollingConfig: RollingHorizonConfig;
  onRollingConfigChange: (config: RollingHorizonConfig) => void;
  stochasticConfig: StochasticConfig;
  onStochasticConfigChange: (config: StochasticConfig) => void;
  sclopfConfig: SecurityConstrainedConfig;
  onSclopfConfigChange: (config: SecurityConstrainedConfig) => void;
  maxSnapshots: number;
  snapshotStart: number;
  snapshotEnd: number;
  snapshotWeight: number;
  onSnapshotStartChange: (v: number) => void;
  onSnapshotEndChange: (v: number) => void;
  onSnapshotWeightChange: (v: number) => void;
  carbonPrice: number;
  onCarbonPriceChange: (v: number) => void;
  carbonPriceSchedule: CarbonPriceScheduleEntry[];
  onCarbonPriceScheduleChange: (next: CarbonPriceScheduleEntry[]) => void;
  currencySymbol: string;
  model: WorkbookModel;
  lineCount: number;
  transformerCount: number;
  onClose: () => void;
}

export function RunSetupWorkspaceView(props: Props) {
  const [tab, setTab] = useState<Tab>('window');

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') props.onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [props]);

  const tabBadge = (key: Tab): string | null => {
    switch (key) {
      case 'window':
        return props.pathwayConfig.enabled
          ? `${props.maxSnapshots} (pathway)`
          : `${props.snapshotEnd - props.snapshotStart} / ${props.maxSnapshots}`;
      case 'planning':
        return props.pathwayConfig.enabled ? `${props.pathwayConfig.periods.length} periods` : 'single';
      case 'rolling':
        return props.rollingConfig.enabled ? `${props.rollingConfig.stepSnapshots}h step` : null;
      case 'carbon':
        if (props.carbonPriceSchedule.length >= 2) {
          const minP = Math.min(...props.carbonPriceSchedule.map((r) => r.price));
          const maxP = Math.max(...props.carbonPriceSchedule.map((r) => r.price));
          return minP === maxP ? `${props.currencySymbol}${minP}/t` : `${props.currencySymbol}${minP}→${maxP}/t`;
        }
        return props.carbonPrice > 0 ? `${props.currencySymbol}${props.carbonPrice}/t` : null;
      case 'stochastic':
        return props.stochasticConfig.enabled && props.stochasticConfig.scenarios.length >= 2
          ? `${props.stochasticConfig.scenarios.length} scenarios`
          : null;
      case 'sclopf':
        return props.sclopfConfig.enabled ? 'N-1' : null;
    }
  };

  const tabs: Array<{ key: Tab; label: string }> = [
    { key: 'window',     label: 'Window & weights' },
    { key: 'planning',   label: 'Multi-year planning' },
    { key: 'rolling',    label: 'Rolling horizon' },
    { key: 'carbon',     label: 'Carbon price' },
    { key: 'stochastic', label: 'Stochastic' },
    { key: 'sclopf',     label: 'SCLOPF' },
  ];

  return (
    <div className="constraints-workspace">
      <div className="constraints-workspace-header">
        <div className="constraints-workspace-title">
          <h2>Run setup</h2>
          <p>Define the optimisation problem: time window, planning mode, market policy and risk model.</p>
        </div>
        <button className="tb-btn tb-btn--muted" onClick={props.onClose} title="Close (Esc)">Close</button>
      </div>

      <nav className="subnav constraints-workspace-tabs">
        {tabs.map(({ key, label }) => {
          const badge = tabBadge(key);
          return (
            <button
              key={key}
              className={`subnav-btn${tab === key ? ' subnav-btn--active' : ''}`}
              onClick={() => setTab(key)}
            >
              {label}
              {badge && <span className="tab-badge tab-badge--ok">{badge}</span>}
            </button>
          );
        })}
      </nav>

      <div className="constraints-workspace-body">
        {tab === 'window'     && <WindowAndWeightsTab {...props} />}
        {tab === 'planning'   && <PlanningTab {...props} />}
        {tab === 'rolling'    && <RollingTab {...props} />}
        {tab === 'carbon'     && <CarbonPriceTab {...props} />}
        {tab === 'stochastic' && <StochasticTab {...props} />}
        {tab === 'sclopf'     && <SclopfTab {...props} />}
      </div>
    </div>
  );
}

// ── Window & weights ─────────────────────────────────────────────────────────

function WindowAndWeightsTab(props: Props) {
  return (
    <section className="constraints-workspace-section">
      <header className="constraints-workspace-section-header">
        <h3>Simulation window</h3>
        <p>Snapshots the solver sees, and the time-weight applied to each.</p>
      </header>
      <div className="sg-setting-row">
        <label className="sg-setting-label">
          Window — {props.pathwayConfig.enabled
            ? `${props.maxSnapshots} steps (pathway uses full horizon)`
            : `${props.snapshotEnd - props.snapshotStart} of ${props.maxSnapshots} steps`}
        </label>
        {!props.pathwayConfig.enabled && props.maxSnapshots > 1 && (
          <DualRangeSlider
            min={0}
            max={props.maxSnapshots}
            low={props.snapshotStart}
            high={props.snapshotEnd}
            onChange={(lo, hi) => { props.onSnapshotStartChange(lo); props.onSnapshotEndChange(hi); }}
          />
        )}
      </div>
      <div className="sg-setting-row">
        <label className="sg-setting-label">Resolution — every {props.snapshotWeight}h</label>
        <div className="sg-btn-row">
          {RUN_WINDOW.weightOptions.map((n) => (
            <button
              key={n}
              className={`tb-btn sg-solver-btn${props.snapshotWeight === n ? '' : ' tb-btn--muted'}`}
              onClick={() => props.onSnapshotWeightChange(n)}
            >
              {n}h
            </button>
          ))}
        </div>
      </div>
    </section>
  );
}

// ── Multi-year planning ──────────────────────────────────────────────────────

function PlanningTab(props: Props) {
  const { pathwayConfig, onPathwayConfigChange } = props;
  return (
    <section className="constraints-workspace-section">
      <header className="constraints-workspace-section-header">
        <h3>Multi-year planning</h3>
        <p>Single period solves one snapshot window. Pathway optimises investment + dispatch jointly across configured periods.</p>
      </header>
      <div className="sg-setting-row">
        <label className="sg-setting-label">Mode</label>
        <div className="sg-btn-row">
          <button
            className={`tb-btn sg-solver-btn${!pathwayConfig.enabled ? '' : ' tb-btn--muted'}`}
            onClick={() => onPathwayConfigChange({ ...pathwayConfig, enabled: false, planningMode: 'single_period' })}
          >
            Single period
          </button>
          <button
            className={`tb-btn sg-solver-btn${pathwayConfig.enabled ? '' : ' tb-btn--muted'}`}
            onClick={() => onPathwayConfigChange({
              ...pathwayConfig,
              enabled: true,
              planningMode: 'pathway',
              periods: pathwayConfig.periods.length
                ? pathwayConfig.periods
                : [
                  { period: 2030, objectiveWeight: 1, yearsWeight: 5 },
                  { period: 2040, objectiveWeight: 1, yearsWeight: 10 },
                ],
              selectedPeriod: pathwayConfig.selectedPeriod ?? 2030,
            })}
          >
            Pathway
          </button>
        </div>
      </div>
      {pathwayConfig.enabled && (
        <>
          <div className="sg-setting-divider" />
          <div className="sg-setting-row">
            <label className="sg-setting-label">Investment periods</label>
            <div className="sg-pathway-grid">
              <strong>Period</strong>
              <strong>Obj. weight</strong>
              <strong>Years</strong>
              <span />
              {pathwayConfig.periods.map((row, index) => (
                <React.Fragment key={`pathway-row-${index}`}>
                  <input
                    type="number"
                    className="sg-pathway-input"
                    value={row.period}
                    onChange={(e) => onPathwayConfigChange({
                      ...pathwayConfig,
                      periods: pathwayConfig.periods.map((item, i) =>
                        i === index ? { ...item, period: Number(e.target.value) || item.period } : item,
                      ),
                    })}
                  />
                  <input
                    type="number"
                    step="0.1"
                    className="sg-pathway-input"
                    value={row.objectiveWeight}
                    onChange={(e) => onPathwayConfigChange({
                      ...pathwayConfig,
                      periods: pathwayConfig.periods.map((item, i) =>
                        i === index ? { ...item, objectiveWeight: Number(e.target.value) || 1 } : item,
                      ),
                    })}
                  />
                  <input
                    type="number"
                    step="0.1"
                    className="sg-pathway-input"
                    value={row.yearsWeight}
                    onChange={(e) => onPathwayConfigChange({
                      ...pathwayConfig,
                      periods: pathwayConfig.periods.map((item, i) =>
                        i === index ? { ...item, yearsWeight: Number(e.target.value) || 1 } : item,
                      ),
                    })}
                  />
                  <button
                    className="tb-btn tb-btn--muted sg-pathway-remove"
                    onClick={() => onPathwayConfigChange({
                      ...pathwayConfig,
                      periods: pathwayConfig.periods.filter((_, i) => i !== index),
                    })}
                  >
                    ×
                  </button>
                </React.Fragment>
              ))}
            </div>
            <button
              className="tb-btn sg-full"
              style={{ marginTop: 8 }}
              onClick={() => {
                const last = pathwayConfig.periods[pathwayConfig.periods.length - 1]?.period ?? 2030;
                onPathwayConfigChange({
                  ...pathwayConfig,
                  periods: [...pathwayConfig.periods, { period: last + 10, objectiveWeight: 1, yearsWeight: 10 }],
                });
              }}
            >
              Add period
            </button>
          </div>
          <div className="sg-setting-row">
            <label className="sg-setting-label" htmlFor="rs-pathway-mapping">Snapshot mapping</label>
            <select
              id="rs-pathway-mapping"
              className="sg-setting-select"
              value={pathwayConfig.snapshotMappingMode}
              onChange={(e) => onPathwayConfigChange({
                ...pathwayConfig,
                snapshotMappingMode: e.target.value as PathwayConfig['snapshotMappingMode'],
              })}
            >
              <option value="explicit_period_column">Use snapshots.period column</option>
              <option value="repeat_all_snapshots">Repeat all snapshots for each period</option>
            </select>
            <p className="sg-setting-hint">
              Pathway runs need either a <code>period</code> column on the snapshots sheet, or repeat-all mapping.
            </p>
          </div>
        </>
      )}
    </section>
  );
}

// ── Rolling horizon ──────────────────────────────────────────────────────────

function RollingTab(props: Props) {
  const { rollingConfig, onRollingConfigChange } = props;
  return (
    <section className="constraints-workspace-section">
      <header className="constraints-workspace-section-header">
        <h3>Rolling horizon</h3>
        <p>Stitch many short solves into one result. Independent from pathway mode; the backend hands each window to PyPSA in turn and forwards storage state.</p>
      </header>
      <div className="sg-setting-row">
        <label className="sg-setting-label">Mode</label>
        <div className="sg-btn-row">
          <button
            className={`tb-btn sg-solver-btn${!rollingConfig.enabled ? '' : ' tb-btn--muted'}`}
            onClick={() => onRollingConfigChange({ ...normalizeRollingConfig(rollingConfig), enabled: false })}
          >
            Off
          </button>
          <button
            className={`tb-btn sg-solver-btn${rollingConfig.enabled ? '' : ' tb-btn--muted'}`}
            onClick={() => onRollingConfigChange({ ...normalizeRollingConfig(rollingConfig), enabled: true })}
          >
            On
          </button>
        </div>
      </div>
      {rollingConfig.enabled && (
        <>
          <div className="sg-setting-divider" />
          <div className="sg-setting-row">
            <label className="sg-setting-label" htmlFor="rs-rolling-horizon">Horizon (snapshots)</label>
            <input
              id="rs-rolling-horizon"
              type="number"
              min={1}
              step={1}
              className="sg-num-input"
              value={rollingConfig.horizonSnapshots}
              onChange={(e) => onRollingConfigChange({
                ...rollingConfig,
                horizonSnapshots: Number(e.target.value) || 1,
              })}
            />
          </div>
          <div className="sg-setting-row">
            <label className="sg-setting-label" htmlFor="rs-rolling-overlap">Overlap (snapshots)</label>
            <input
              id="rs-rolling-overlap"
              type="number"
              min={0}
              step={1}
              className="sg-num-input"
              value={rollingConfig.overlapSnapshots}
              onChange={(e) => onRollingConfigChange({
                ...rollingConfig,
                overlapSnapshots: Math.max(0, Number(e.target.value) || 0),
              })}
            />
          </div>
          <div className="sg-setting-row">
            <label className="sg-setting-label">Effective step</label>
            <div className="sg-setting-value">{rollingConfig.stepSnapshots} snapshots</div>
          </div>
        </>
      )}
    </section>
  );
}

// ── Carbon price ─────────────────────────────────────────────────────────────

function CarbonPriceTab(props: Props) {
  const settingsRanges = SETTINGS_CONFIG.ranges;
  const schedule = props.carbonPriceSchedule;
  const scheduleActive = schedule.length > 0;

  const setSchedule = (next: CarbonPriceScheduleEntry[]) => {
    // Keep rows sorted ascending by year on every edit.
    const sorted = [...next].sort((a, b) => a.year - b.year);
    props.onCarbonPriceScheduleChange(sorted);
  };

  const addRow = () => {
    const lastYear = schedule.length > 0 ? schedule[schedule.length - 1].year : new Date().getFullYear();
    const lastPrice = schedule.length > 0 ? schedule[schedule.length - 1].price : Math.max(props.carbonPrice, 30);
    setSchedule([...schedule, { year: lastYear + 5, price: lastPrice * 1.5 }]);
  };

  const updateRow = (i: number, patch: Partial<CarbonPriceScheduleEntry>) =>
    setSchedule(schedule.map((r, idx) => (idx === i ? { ...r, ...patch } : r)));

  const removeRow = (i: number) => setSchedule(schedule.filter((_, idx) => idx !== i));

  return (
    <section className="constraints-workspace-section">
      <header className="constraints-workspace-section-header">
        <h3>Carbon price</h3>
        <p>Added to each generator's marginal cost proportional to its carrier's <code>co2_emissions</code> factor. Use a schedule to ramp the price across years (pathway runs apply the price for each investment period; single-period runs use the snapshot timestamp's year).</p>
      </header>

      <div className="sg-setting-row">
        <label className="sg-setting-label" htmlFor="rs-carbon-price">
          Scalar price <span style={{ color: 'var(--muted)', fontSize: '0.78rem', marginLeft: 6 }}>(used when the schedule below is empty)</span>
        </label>
        <div className="sg-carbon-row">
          <span className="sg-carbon-sym">{props.currencySymbol}</span>
          <input
            id="rs-carbon-price"
            type="number"
            className="sg-carbon-input"
            min={settingsRanges.carbonPrice.min}
            max={settingsRanges.carbonPrice.max}
            step={settingsRanges.carbonPrice.step}
            value={props.carbonPrice}
            disabled={scheduleActive}
            onChange={(e) => props.onCarbonPriceChange(Math.max(settingsRanges.carbonPrice.min, parseFloat(e.target.value) || 0))}
          />
          <span className="sg-carbon-unit">/tCO₂</span>
        </div>
      </div>

      <div className="sg-setting-divider" />

      <div className="sg-setting-row">
        <label className="sg-setting-label">Schedule</label>
        {schedule.length === 0 ? (
          <p className="sg-setting-hint" style={{ marginTop: 0 }}>
            No schedule rows — the scalar above applies to every snapshot. Add a row to switch to a year-indexed schedule.
          </p>
        ) : (
          <table className="constraints-table" style={{ marginBottom: 8 }}>
            <thead>
              <tr>
                <th>Year</th>
                <th>Price ({props.currencySymbol}/tCO₂)</th>
                <th aria-label="actions" />
              </tr>
            </thead>
            <tbody>
              {schedule.map((row, i) => (
                <tr key={`carbon-row-${i}`}>
                  <td>
                    <input
                      type="number"
                      className="constraints-cell-input constraints-cell-input--num"
                      value={row.year}
                      step={1}
                      onChange={(e) => updateRow(i, { year: parseInt(e.target.value, 10) || row.year })}
                    />
                  </td>
                  <td>
                    <input
                      type="number"
                      className="constraints-cell-input constraints-cell-input--num"
                      value={row.price}
                      step={settingsRanges.carbonPrice.step}
                      min={0}
                      onChange={(e) => updateRow(i, { price: parseFloat(e.target.value) || 0 })}
                    />
                  </td>
                  <td>
                    <button className="gcc-del" onClick={() => removeRow(i)} title="Delete row">×</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <button className="tb-btn" onClick={addRow}>+ Add schedule row</button>
        {scheduleActive && (
          <p className="sg-setting-hint">
            Snapshot resolution: each snapshot uses the most-recent schedule entry whose year is ≤ the snapshot's year. Pathway runs use the investment period year; single-period runs use the snapshot timestamp year.
          </p>
        )}
      </div>
    </section>
  );
}

// ── Stochastic ───────────────────────────────────────────────────────────────

function StochasticTab(props: Props) {
  const { stochasticConfig, onStochasticConfigChange, rollingConfig, model } = props;
  const config = stochasticConfig;
  const onChange = onStochasticConfigChange;
  const rollingEnabled = rollingConfig.enabled;

  const update = (patch: Partial<StochasticConfig>) => onChange({ ...config, ...patch });
  const setScenarios = (scenarios: StochasticScenarioConfig[]) => update({ scenarios });

  const addScenario = () => {
    const id = `sc_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`;
    const n = config.scenarios.length + 1;
    setScenarios([
      ...config.scenarios,
      {
        id,
        name: `scenario_${n}`,
        weight: 0.5,
        loadMultiplier: 1.0,
        marginalCostMultiplier: 1.0,
        renewableAvailabilityMultiplier: 1.0,
        overrides: [],
      },
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

// ── SCLOPF ───────────────────────────────────────────────────────────────────

function SclopfTab(props: Props) {
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
            onClick={() => props.onSclopfConfigChange({ enabled: false })}
          >
            Off
          </button>
          <button
            className={`tb-btn sg-solver-btn${props.sclopfConfig.enabled ? '' : ' tb-btn--muted'}`}
            disabled={blocked}
            title={blocked ? `Disable ${blockReason} to enable SCLOPF` : undefined}
            onClick={() => props.onSclopfConfigChange({ enabled: true })}
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
        </>
      )}
    </section>
  );
}

// ── One scenario row: quick knobs + advanced-overrides disclosure ────────────

const OVERRIDABLE_SHEETS = PYPSA_COMPONENTS
  .filter((c) => !['snapshots', 'network', 'carriers'].includes(c.sheet_name) && c.input_static_attributes.length > 0)
  .map((c) => c.sheet_name);

function StochasticScenarioRow({
  scenario,
  model,
  onUpdate,
  onRemove,
}: {
  scenario: StochasticScenarioConfig;
  model: WorkbookModel;
  onUpdate: (patch: Partial<StochasticScenarioConfig>) => void;
  onRemove: () => void;
}) {
  const [showOverrides, setShowOverrides] = useState((scenario.overrides ?? []).length > 0);

  const setOverrides = (next: StochasticScenarioOverride[]) => onUpdate({ overrides: next });
  const addOverride = () => {
    const id = `ov_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`;
    const firstSheet = OVERRIDABLE_SHEETS[0] ?? 'generators';
    const sheetSchema = PYPSA_COMPONENTS.find((c) => c.sheet_name === firstSheet);
    const firstAttr = sheetSchema?.input_static_attributes[0] ?? 'marginal_cost';
    setOverrides([
      ...scenario.overrides,
      { id, sheet: firstSheet, attribute: firstAttr, scopeType: 'all', scopeValue: '', operation: 'multiply', value: 1.0 },
    ]);
  };
  const updateOverride = (id: string, patch: Partial<StochasticScenarioOverride>) =>
    setOverrides(scenario.overrides.map((o) => (o.id === id ? { ...o, ...patch } : o)));
  const removeOverride = (id: string) =>
    setOverrides(scenario.overrides.filter((o) => o.id !== id));

  return (
    <div className="stochastic-scenario-row">
      <div className="sg-stochastic-row">
        <input
          className="sg-stochastic-name"
          type="text"
          value={scenario.name}
          onChange={(e) => onUpdate({ name: e.target.value })}
          placeholder="name"
        />
        <label className="sg-stochastic-field" title="Probability weight">
          <span>w</span>
          <input
            type="number"
            step="0.05"
            min="0"
            value={scenario.weight}
            onChange={(e) => onUpdate({ weight: Number(e.target.value) || 0 })}
          />
        </label>
        <label className="sg-stochastic-field" title="Scales every load.p_set in this scenario">
          <span>×load</span>
          <input
            type="number"
            step="0.05"
            min="0"
            value={scenario.loadMultiplier}
            onChange={(e) => onUpdate({ loadMultiplier: Number(e.target.value) || 0 })}
          />
        </label>
        <label className="sg-stochastic-field" title="Scales every generator's marginal_cost (post-carbon adder) — proxy for fuel-price uncertainty">
          <span>×fuel</span>
          <input
            type="number"
            step="0.05"
            min="0"
            value={scenario.marginalCostMultiplier}
            onChange={(e) => onUpdate({ marginalCostMultiplier: Number(e.target.value) || 0 })}
          />
        </label>
        <label className="sg-stochastic-field" title="Scales p_max_pu for renewable-carrier generators (solar / wind / hydro …) — proxy for weather uncertainty">
          <span>×renew</span>
          <input
            type="number"
            step="0.05"
            min="0"
            value={scenario.renewableAvailabilityMultiplier}
            onChange={(e) => onUpdate({ renewableAvailabilityMultiplier: Number(e.target.value) || 0 })}
          />
        </label>
        <button className="gcc-del" onClick={onRemove} title="Remove scenario">x</button>
      </div>

      <div style={{ marginLeft: 6, marginTop: 4, marginBottom: 8 }}>
        <button
          className="tb-btn tb-btn--muted"
          style={{ fontSize: '0.78rem', padding: '2px 8px' }}
          onClick={() => setShowOverrides((v) => !v)}
        >
          {showOverrides ? '− Advanced overrides' : `+ Advanced overrides${scenario.overrides.length > 0 ? ` (${scenario.overrides.length})` : ''}`}
        </button>

        {showOverrides && (
          <div style={{ marginTop: 8, marginLeft: 12 }}>
            {scenario.overrides.length === 0 ? (
              <p className="sg-setting-hint" style={{ marginTop: 0 }}>
                Add an override to vary a specific (sheet, attribute) by name, carrier, or for the whole sheet.
              </p>
            ) : (
              <table className="constraints-table" style={{ marginBottom: 6 }}>
                <thead>
                  <tr>
                    <th>Sheet</th>
                    <th>Attribute</th>
                    <th>Scope</th>
                    <th>Filter</th>
                    <th>Op</th>
                    <th>Value</th>
                    <th aria-label="actions" />
                  </tr>
                </thead>
                <tbody>
                  {scenario.overrides.map((o) => {
                    const sheetSchema = PYPSA_COMPONENTS.find((c) => c.sheet_name === o.sheet);
                    const attrOptions = sheetSchema?.input_static_attributes ?? [];
                    const carriers = Array.from(
                      new Set((model.carriers ?? []).map((r) => stringValue(r.name)).filter(Boolean)),
                    );
                    const names = ((model[o.sheet] ?? []) as Array<Record<string, unknown>>)
                      .map((r) => String(r.name ?? '').trim())
                      .filter(Boolean);
                    return (
                      <tr key={o.id}>
                        <td>
                          <select
                            className="constraints-cell-input"
                            value={o.sheet}
                            onChange={(e) => {
                              const nextSheet = e.target.value;
                              const next = PYPSA_COMPONENTS.find((c) => c.sheet_name === nextSheet);
                              const nextAttr = next?.input_static_attributes[0] ?? o.attribute;
                              updateOverride(o.id, { sheet: nextSheet, attribute: nextAttr, scopeValue: '' });
                            }}
                          >
                            {OVERRIDABLE_SHEETS.map((s) => (<option key={s} value={s}>{s}</option>))}
                          </select>
                        </td>
                        <td>
                          <select
                            className="constraints-cell-input"
                            value={o.attribute}
                            onChange={(e) => updateOverride(o.id, { attribute: e.target.value })}
                          >
                            {attrOptions.map((a) => (<option key={a} value={a}>{a}</option>))}
                          </select>
                        </td>
                        <td>
                          <select
                            className="constraints-cell-input"
                            value={o.scopeType}
                            onChange={(e) => updateOverride(o.id, { scopeType: e.target.value as 'all' | 'name' | 'carrier', scopeValue: '' })}
                          >
                            <option value="all">all rows</option>
                            <option value="name">by name</option>
                            <option value="carrier">by carrier</option>
                          </select>
                        </td>
                        <td>
                          {o.scopeType === 'all' ? (
                            <span style={{ color: 'var(--muted)', fontStyle: 'italic' }}>—</span>
                          ) : (
                            <input
                              className="constraints-cell-input"
                              value={o.scopeValue}
                              list={`ov-${o.id}-list`}
                              onChange={(e) => updateOverride(o.id, { scopeValue: e.target.value })}
                              placeholder={o.scopeType === 'name' ? 'row name' : 'carrier'}
                            />
                          )}
                          {o.scopeType !== 'all' && (
                            <datalist id={`ov-${o.id}-list`}>
                              {(o.scopeType === 'carrier' ? carriers : names).map((v) => (
                                <option key={v} value={v} />
                              ))}
                            </datalist>
                          )}
                        </td>
                        <td>
                          <select
                            className="constraints-cell-input"
                            value={o.operation}
                            onChange={(e) => updateOverride(o.id, { operation: e.target.value as 'multiply' | 'set' })}
                          >
                            <option value="multiply">×</option>
                            <option value="set">=</option>
                          </select>
                        </td>
                        <td>
                          <input
                            type="number"
                            className="constraints-cell-input constraints-cell-input--num"
                            value={o.value}
                            step="0.1"
                            onChange={(e) => updateOverride(o.id, { value: Number(e.target.value) || 0 })}
                          />
                        </td>
                        <td>
                          <button className="gcc-del" onClick={() => removeOverride(o.id)} title="Delete override">×</button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
            <button className="tb-btn" style={{ fontSize: '0.85rem' }} onClick={addOverride}>+ Add override</button>
          </div>
        )}
      </div>
    </div>
  );
}
