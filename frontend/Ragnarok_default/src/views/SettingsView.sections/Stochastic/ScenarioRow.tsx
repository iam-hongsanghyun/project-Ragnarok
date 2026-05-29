/**
 * One stochastic scenario row — name, weight, and a table of attribute
 * overrides (sheet · attribute · scope · op · value).
 */
import React from 'react';
import {
  StochasticScenarioConfig,
  StochasticScenarioOverride,
  WorkbookModel,
} from '../../../shared/types';
import { PYPSA_COMPONENTS } from '../../../constants/pypsa_schema';
import { SearchableSelect } from '../../../shared/components/SearchableSelect';

const OVERRIDABLE_SHEETS = PYPSA_COMPONENTS
  .filter((c) => !['snapshots', 'network', 'carriers'].includes(c.sheet_name) && c.input_static_attributes.length > 0)
  .map((c) => c.sheet_name);

interface Props {
  scenario: StochasticScenarioConfig;
  model: WorkbookModel;
  onUpdate: (patch: Partial<StochasticScenarioConfig>) => void;
  onRemove: () => void;
}

export function StochasticScenarioRow({ scenario, model, onUpdate, onRemove }: Props) {
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
        <span style={{ flex: 1, color: 'var(--muted)', fontSize: '0.78rem' }}>
          {scenario.overrides.length === 0
            ? 'no overrides — equal to baseline'
            : `${scenario.overrides.length} override${scenario.overrides.length === 1 ? '' : 's'}`}
        </span>
        <button className="gcc-del" onClick={onRemove} title="Remove scenario">x</button>
      </div>

      <div style={{ marginLeft: 12, marginTop: 4, marginBottom: 12 }}>
        <table className="constraints-table" style={{ marginBottom: 6 }}>
          <thead>
            <tr>
              <th>Sheet</th>
              <th>Attribute</th>
              <th>Scope</th>
              <th>Match</th>
              <th>Op</th>
              <th>Value</th>
              <th aria-label="actions" />
            </tr>
          </thead>
          <tbody>
            {scenario.overrides.length === 0 && (
              <tr>
                <td colSpan={7} style={{ color: 'var(--muted)', textAlign: 'center', padding: '8px 0', fontStyle: 'italic' }}>
                  No overrides yet — solver sees the baseline values for this scenario.
                </td>
              </tr>
            )}
            {scenario.overrides.map((o) => {
              const sheetSchema = PYPSA_COMPONENTS.find((c) => c.sheet_name === o.sheet);
              const attrOptions = sheetSchema?.input_static_attributes ?? [];
              const sheetRows = (model[o.sheet] ?? []) as Array<Record<string, unknown>>;
              const matchOptions = o.scopeType === 'name'
                ? Array.from(new Set(sheetRows.map((r) => String(r.name ?? '').trim()).filter(Boolean)))
                : o.scopeType === 'carrier'
                  ? Array.from(new Set(sheetRows.map((r) => String(r.carrier ?? '').trim()).filter(Boolean)))
                  : [];
              return (
                <tr key={o.id}>
                  <td>
                    <SearchableSelect
                      className="constraints-cell-input"
                      value={o.sheet}
                      options={OVERRIDABLE_SHEETS}
                      onChange={(nextSheet) => {
                        const next = PYPSA_COMPONENTS.find((c) => c.sheet_name === nextSheet);
                        const nextAttr = next?.input_static_attributes[0] ?? o.attribute;
                        updateOverride(o.id, { sheet: nextSheet, attribute: nextAttr, scopeValue: '' });
                      }}
                    />
                  </td>
                  <td>
                    <SearchableSelect
                      className="constraints-cell-input"
                      value={o.attribute}
                      options={attrOptions}
                      onChange={(v) => updateOverride(o.id, { attribute: v })}
                    />
                  </td>
                  <td>
                    <SearchableSelect
                      className="constraints-cell-input"
                      value={o.scopeType}
                      options={[
                        { value: 'all', label: 'all rows' },
                        { value: 'name', label: 'by name' },
                        { value: 'carrier', label: 'by carrier' },
                      ]}
                      onChange={(v) => updateOverride(o.id, { scopeType: v as 'all' | 'name' | 'carrier', scopeValue: '' })}
                    />
                  </td>
                  <td>
                    {o.scopeType === 'all' ? (
                      <span style={{ color: 'var(--muted)', fontStyle: 'italic' }}>—</span>
                    ) : matchOptions.length === 0 ? (
                      <span style={{ color: 'var(--muted)', fontStyle: 'italic' }}>
                        no {o.scopeType}s
                      </span>
                    ) : (
                      <SearchableSelect
                        className="constraints-cell-input"
                        value={o.scopeValue}
                        options={matchOptions}
                        placeholder={`— pick ${o.scopeType} —`}
                        onChange={(v) => updateOverride(o.id, { scopeValue: v })}
                      />
                    )}
                  </td>
                  <td>
                    <SearchableSelect
                      className="constraints-cell-input"
                      value={o.operation}
                      options={[
                        { value: 'multiply', label: '×' },
                        { value: 'set', label: '=' },
                      ]}
                      onChange={(v) => updateOverride(o.id, { operation: v as 'multiply' | 'set' })}
                    />
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
        <button className="tb-btn" style={{ fontSize: '0.85rem' }} onClick={addOverride}>+ Add override</button>
      </div>
    </div>
  );
}
