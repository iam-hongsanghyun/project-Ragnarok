import React, { useState } from 'react';
import {
  ModuleConfigField,
  ModuleDescriptor,
  PluginAnalyticsEntry,
  PluginFieldHint,
} from '../../shared/types';
import { ConfigFieldRow } from '../modules/ModuleManagerSection';

// ── Value formatter ───────────────────────────────────────────────────────────

function formatPluginValue(value: unknown, hint: PluginFieldHint | undefined): string {
  if (value === null || value === undefined) return '—';
  if (hint?.format === 'currency' || hint?.format === 'number') {
    const n = Number(value);
    if (!Number.isFinite(n)) return String(value);
    return n.toLocaleString(undefined, { maximumFractionDigits: 4 });
  }
  return String(value);
}

// ── Table renderer (shared by dict and array-of-rows formats) ─────────────────

function renderTableContent(value: unknown, hint: PluginFieldHint | undefined): React.ReactNode | null {
  // array-of-rows: [{ col1: v, col2: v }, ...]
  if (Array.isArray(value) && value.length > 0 && typeof value[0] === 'object' && value[0] !== null) {
    const cols = Object.keys(value[0] as Record<string, unknown>);
    return (
      <table className="plugin-result-subtable">
        <thead>
          <tr>{cols.map((c) => <th key={c}>{c}</th>)}</tr>
        </thead>
        <tbody>
          {(value as Record<string, unknown>[]).map((row, i) => (
            <tr key={i}>
              {cols.map((c) => (
                <td key={c}>
                  {formatPluginValue(row[c], hint)}
                  {hint?.unit ? <span className="plugin-result-unit"> {hint.unit}</span> : null}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    );
  }
  // dict: { key: scalar, ... }
  if (typeof value === 'object' && !Array.isArray(value) && value !== null) {
    return (
      <table className="plugin-result-subtable">
        <tbody>
          {Object.entries(value as Record<string, unknown>).map(([k, v]) => (
            <tr key={k}>
              <td>{k}</td>
              <td>
                {formatPluginValue(v, hint)}
                {hint?.unit ? <span className="plugin-result-unit"> {hint.unit}</span> : null}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    );
  }
  return null;
}

// ── Results table ─────────────────────────────────────────────────────────────

function PluginResults({ entry }: { entry: PluginAnalyticsEntry }) {
  const { ui, data } = entry;
  if (!data || Object.keys(data).length === 0) {
    return <p className="sg-setting-hint">No results yet — run the model first.</p>;
  }
  return (
    <table className="plugin-result-table">
      <tbody>
        {Object.entries(data).map(([key, value]) => {
          const hint = ui?.[key];

          if (key === 'error') {
            return (
              <tr key={key}>
                <td colSpan={2} style={{ color: 'var(--danger, #dc2626)', fontSize: '0.82rem' }}>
                  Plugin error: {String(value)}
                </td>
              </tr>
            );
          }

          if (hint?.format === 'table') {
            const tableContent = renderTableContent(value, hint);
            if (tableContent) {
              return (
                <tr key={key}>
                  <td className="plugin-result-label" style={{ verticalAlign: 'top' }}>{hint?.label ?? key}</td>
                  <td className="plugin-result-value">{tableContent}</td>
                </tr>
              );
            }
          }

          return (
            <tr key={key}>
              <td className="plugin-result-label">{hint?.label ?? key}</td>
              <td className="plugin-result-value">
                {formatPluginValue(value, hint)}
                {hint?.unit ? <span className="plugin-result-unit"> {hint.unit}</span> : null}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

// ── Single plugin tab content ─────────────────────────────────────────────────

interface PluginTabContentProps {
  module: ModuleDescriptor;
  config: Record<string, unknown>;
  onConfigChange: (key: string, value: unknown) => void;
  carriers?: string[];
  analytics: PluginAnalyticsEntry | null;
  onModuleAction?: (moduleId: string, fieldKey: string, field: ModuleConfigField) => Promise<void>;
}

function PluginTabContent({ module, config, onConfigChange, carriers, analytics, onModuleAction }: PluginTabContentProps) {
  const hasConfig = module.config && Object.keys(module.config).length > 0;
  return (
    <div className="plugin-panel-content">
      <div className="plugin-panel-columns">
        {hasConfig && (
          <div className="plugin-panel-col plugin-panel-col--config">
            <p className="plugin-panel-col-title">Configuration</p>
            {module.description && (
              <p className="sg-setting-hint" style={{ marginBottom: 12 }}>{module.description}</p>
            )}
            <div className="sg-module-config-form">
              {Object.entries(module.config!).map(([key, field]) => (
                <ConfigFieldRow
                  key={key}
                  fieldKey={key}
                  field={field}
                  value={config[key]}
                  onChange={(v) => onConfigChange(key, v)}
                  carriers={carriers}
                  formValues={config}
                  onAction={onModuleAction ? (fk, f) => onModuleAction(module.id, fk, f) : undefined}
                />
              ))}
            </div>
          </div>
        )}

        <div className="plugin-panel-col plugin-panel-col--results">
          <p className="plugin-panel-col-title">Results</p>
          {analytics
            ? <PluginResults entry={analytics} />
            : <p className="sg-setting-hint">No results yet — run the model first.</p>
          }
        </div>
      </div>
    </div>
  );
}

// ── Plugin panel (top-level) ──────────────────────────────────────────────────

interface PluginPanelProps {
  modules: ModuleDescriptor[];
  moduleConfigs: Record<string, Record<string, unknown>>;
  onModuleConfigChange: (moduleId: string, key: string, value: unknown) => void;
  carriers?: string[];
  pluginAnalytics: Record<string, PluginAnalyticsEntry>;
  onModuleAction?: (moduleId: string, fieldKey: string, field: ModuleConfigField) => Promise<void>;
}

export function PluginPanel({
  modules, moduleConfigs, onModuleConfigChange, carriers, pluginAnalytics, onModuleAction,
}: PluginPanelProps) {
  const [activeId, setActiveId] = useState<string>(modules[0]?.id ?? '');

  if (modules.length === 0) {
    return (
      <div className="analytics-empty">
        <h3>No plugins in Main panel mode</h3>
        <p>
          Open the Modules section in the sidebar, expand a plugin card,
          and switch its Location to "Main panel".
        </p>
      </div>
    );
  }

  const active = modules.find((m) => m.id === activeId) ?? modules[0];

  return (
    <div className="plugin-panel-root">
      <div className="analytics-pane-header" style={{ padding: '14px 20px 10px' }}>
        <nav className="analytics-subtab-nav">
          {modules.map((m) => (
            <button
              key={m.id}
              className={`analytics-subtab${(activeId || modules[0].id) === m.id ? ' analytics-subtab--active' : ''}`}
              onClick={() => setActiveId(m.id)}
            >
              {m.name || m.id}
              {pluginAnalytics[m.id] && (
                <span
                  style={{
                    display: 'inline-block',
                    width: 7,
                    height: 7,
                    borderRadius: '50%',
                    background: 'var(--brand, #2563eb)',
                    marginLeft: 6,
                    verticalAlign: 'middle',
                  }}
                  title="Has results"
                />
              )}
            </button>
          ))}
        </nav>
      </div>

      <PluginTabContent
        key={active.id}
        module={active}
        config={moduleConfigs[active.id] ?? {}}
        onConfigChange={(key, value) => onModuleConfigChange(active.id, key, value)}
        carriers={carriers}
        analytics={pluginAnalytics[active.id] ?? null}
        onModuleAction={onModuleAction}
      />
    </div>
  );
}
