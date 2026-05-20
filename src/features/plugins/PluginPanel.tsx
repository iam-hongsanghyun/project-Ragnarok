import React, { useState } from 'react';
import {
  ModuleDescriptor,
  PluginAnalyticsEntry,
  PluginFieldHint,
} from '../../shared/types';
import { ConfigFieldRow } from '../modules/ModuleManagerSection';

// ── Helpers (mirrored from ResultsDashboard) ─────────────────────────────────

function formatPluginValue(value: unknown, hint: PluginFieldHint | undefined): string {
  if (value === null || value === undefined) return '—';
  if (hint?.format === 'currency' || hint?.format === 'number') {
    const n = Number(value);
    if (!Number.isFinite(n)) return String(value);
    return n.toLocaleString(undefined, { maximumFractionDigits: 4 });
  }
  return String(value);
}

// ── Plugin results table ──────────────────────────────────────────────────────

function PluginResults({ entry }: { entry: PluginAnalyticsEntry }) {
  const { ui, data } = entry;
  if (!data || Object.keys(data).length === 0) {
    return <p className="sg-setting-hint">No results yet — run the model first.</p>;
  }
  return (
    <table className="plugin-result-table pp-result-table">
      <tbody>
        {Object.entries(data).map(([key, value]) => {
          const hint = ui?.[key];
          if (hint?.format === 'table' && value && typeof value === 'object' && !Array.isArray(value)) {
            return (
              <tr key={key}>
                <td className="plugin-result-label">{hint?.label ?? key}</td>
                <td className="plugin-result-value">
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
                </td>
              </tr>
            );
          }
          if (key === 'error') {
            return (
              <tr key={key}>
                <td colSpan={2} style={{ color: 'var(--danger, #dc2626)', fontSize: '0.82rem' }}>
                  Plugin error: {String(value)}
                </td>
              </tr>
            );
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
}

function PluginTabContent({ module, config, onConfigChange, carriers, analytics }: PluginTabContentProps) {
  const hasConfig = module.config && Object.keys(module.config).length > 0;
  return (
    <div className="pp-tab-content">
      <div className="pp-columns">
        {/* Left: config */}
        {hasConfig && (
          <div className="pp-col pp-col--config">
            <p className="pp-section-title">Configuration</p>
            <p className="sg-setting-hint" style={{ marginBottom: 12 }}>{module.description}</p>
            <div className="sg-module-config-form pp-config-form">
              {Object.entries(module.config!).map(([key, field]) => (
                <ConfigFieldRow
                  key={key}
                  fieldKey={key}
                  field={field}
                  value={config[key]}
                  onChange={(v) => onConfigChange(key, v)}
                  carriers={carriers}
                />
              ))}
            </div>
          </div>
        )}

        {/* Right: results */}
        <div className="pp-col pp-col--results">
          <p className="pp-section-title">Results</p>
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
  modules: ModuleDescriptor[];          // only 'panel' mode + enabled + ready
  moduleConfigs: Record<string, Record<string, unknown>>;
  onModuleConfigChange: (moduleId: string, key: string, value: unknown) => void;
  carriers?: string[];
  pluginAnalytics: Record<string, PluginAnalyticsEntry>;
}

export function PluginPanel({
  modules, moduleConfigs, onModuleConfigChange, carriers, pluginAnalytics,
}: PluginPanelProps) {
  const [activeId, setActiveId] = useState<string>(modules[0]?.id ?? '');

  if (modules.length === 0) {
    return (
      <div className="pp-empty">
        <p>No plugins are set to <strong>Main panel</strong> mode.</p>
        <p className="sg-setting-hint">
          Open the Modules section in the sidebar, expand a plugin card, and switch its Location to "Main panel".
        </p>
      </div>
    );
  }

  const active = modules.find((m) => m.id === activeId) ?? modules[0];

  return (
    <div className="pp-root">
      {/* Sub-tab bar */}
      <div className="pp-subtab-bar">
        {modules.map((m) => (
          <button
            key={m.id}
            className={`pp-subtab${(activeId || modules[0].id) === m.id ? ' pp-subtab--active' : ''}`}
            onClick={() => setActiveId(m.id)}
          >
            {m.name || m.id}
            {pluginAnalytics[m.id] && (
              <span className="pp-subtab-dot" title="Has results" />
            )}
          </button>
        ))}
      </div>

      {/* Active tab */}
      <PluginTabContent
        key={active.id}
        module={active}
        config={moduleConfigs[active.id] ?? {}}
        onConfigChange={(key, value) => onModuleConfigChange(active.id, key, value)}
        carriers={carriers}
        analytics={pluginAnalytics[active.id] ?? null}
      />
    </div>
  );
}
