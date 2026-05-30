/**
 * Frontend plugin → constraints panel (Phase 3).
 *
 * Lists frontend-only plugins, lets the user enable + configure them, and runs
 * each plugin's `toConstraintLines` IN THE BROWSER, inserting the result into
 * the Advanced Constraints code box. This realises the target flow:
 *   plugin → Ragnarok frontend (DSL → JSON) → backend → frontend → plugin
 * The Ragnarok backend is never contacted by the plugin.
 */
import React from 'react';
import { WorkbookModel } from '../../shared/types';
import { FrontendPlugin, FrontendPluginHost } from './frontendPlugins';

export interface PluginConstraintsPanelProps {
  host: FrontendPluginHost;
  model: WorkbookModel;
  customDsl: string;
  onCustomDslChange: (text: string) => void;
}

export function PluginConstraintsPanel({ host, model, customDsl, onCustomDslChange }: PluginConstraintsPanelProps) {
  const carriers = Array.from(
    new Set((model.carriers ?? []).map((c) => String(c.name ?? '')).filter(Boolean)),
  );

  const insertLines = (plugin: FrontendPlugin) => {
    const lines = host.linesFor(plugin, model);
    if (lines.length === 0) return;
    const block = [`# ${plugin.name} (plugin)`, ...lines].join('\n');
    const next = customDsl.trim() ? `${customDsl.replace(/\s+$/, '')}\n${block}\n` : `${block}\n`;
    onCustomDslChange(next);
  };

  return (
    <section className="constraints-workspace-section">
      <header className="constraints-workspace-section-header">
        <h3>Constraint plugins</h3>
        <p>Frontend plugins generate constraints in the browser and insert them into the Advanced Constraints code box (Settings → Advanced Constraints) as editable lines. They run entirely in the frontend and never talk to the Ragnarok backend.</p>
      </header>
      {host.plugins.map((plugin) => {
        const enabled = host.isEnabled(plugin.id);
        const cfg = host.getConfig(plugin);
        const selected = Array.isArray(cfg.carriers) ? (cfg.carriers as string[]) : [];
        return (
          <div key={plugin.id} className="plugin-fe-row">
            <label className="sg-setting-label" style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              <input type="checkbox" className="gcc-check" checked={enabled} onChange={(e) => host.toggle(plugin.id, e.target.checked)} />
              <strong>{plugin.name}</strong>
            </label>
            <p className="sg-setting-hint">{plugin.description}</p>
            {enabled && (
              <div className="plugin-fe-config">
                {plugin.fields.map((f) => {
                  if (f.type === 'carriers') {
                    return (
                      <div key={f.key} className="rolling-input">
                        <span className="sg-setting-label">{f.label}</span>
                        <div className="sg-btn-row" style={{ flexWrap: 'wrap' }}>
                          {carriers.length === 0 && <span className="constraints-cell-placeholder">No carriers in model</span>}
                          {carriers.map((c) => {
                            const on = selected.includes(c);
                            return (
                              <button
                                key={c}
                                className={`tb-btn sg-solver-btn${on ? '' : ' tb-btn--muted'}`}
                                onClick={() => host.setConfigField(
                                  plugin.id, f.key,
                                  on ? selected.filter((x) => x !== c) : [...selected, c],
                                )}
                              >
                                {c}
                              </button>
                            );
                          })}
                        </div>
                      </div>
                    );
                  }
                  return (
                    <div key={f.key} className="rolling-input">
                      <label className="sg-setting-label">{f.label}{f.unit ? ` (${f.unit})` : ''}</label>
                      <input
                        type="number"
                        className="sg-num-input"
                        value={Number(cfg[f.key] ?? 0)}
                        onChange={(e) => host.setConfigField(plugin.id, f.key, Number(e.target.value) || 0)}
                      />
                    </div>
                  );
                })}
                <button className="tb-btn" style={{ marginTop: 4 }} onClick={() => insertLines(plugin)}>
                  Insert into code box
                </button>
              </div>
            )}
          </div>
        );
      })}
    </section>
  );
}
