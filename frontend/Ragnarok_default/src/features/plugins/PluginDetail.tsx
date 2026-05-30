/**
 * Detail pane for one installed plugin: config + run actions + analyze output.
 * Rendered in the Plugins tab main area; the rail selects which plugin shows.
 */
import React, { useState } from 'react';
import { WorkbookModel } from '../../shared/types';
import { FrontendPluginHost, InstalledPlugin } from './frontendPlugins';
import { loadPluginModule, pluginCapabilities } from './pluginRuntime';
import { useToast } from '../../shared/components/Toast';

export interface PluginDetailProps {
  host: FrontendPluginHost;
  plugin: InstalledPlugin;
  model: WorkbookModel;
  onReplaceModel: (next: WorkbookModel) => void;
  onMergeSheets: (sheets: Record<string, WorkbookModel[string]>) => void;
  customDsl: string;
  onCustomDslChange: (text: string) => void;
  results: unknown;
}

export function PluginDetail({ host, plugin, model, onReplaceModel, onMergeSheets, customDsl, onCustomDslChange, results }: PluginDetailProps) {
  const { showToast } = useToast();
  const [analysis, setAnalysis] = useState<Record<string, unknown> | null>(null);
  const caps = pluginCapabilities(plugin);
  const cfg = host.getConfig(plugin.id);
  const enabled = host.isEnabled(plugin.id);

  const apply = () => {
    try {
      const mod = loadPluginModule(plugin);
      if (mod.transform) {
        const next = mod.transform(model, cfg);
        if (!next || typeof next !== 'object') throw new Error('transform() did not return a model.');
        onReplaceModel(next as WorkbookModel);
        showToast(`${plugin.name}: model replaced.`, 'success');
        return;
      }
      if (mod.contribute) {
        const out = mod.contribute(model, cfg) || {};
        if (out.sheets && typeof out.sheets === 'object') onMergeSheets(out.sheets);
        if (Array.isArray(out.constraints) && out.constraints.length) {
          const block = [`# ${plugin.name} (plugin)`, ...out.constraints].join('\n');
          onCustomDslChange(customDsl.trim() ? `${customDsl.replace(/\s+$/, '')}\n${block}\n` : `${block}\n`);
        }
        showToast(`${plugin.name}: contributed to the model.`, 'success');
        return;
      }
      showToast(`${plugin.name} has no transform/contribute hook.`, 'error');
    } catch (err) {
      showToast(`${plugin.name}: ${err instanceof Error ? err.message : 'failed'}`, 'error');
    }
  };

  const analyze = () => {
    try {
      const mod = loadPluginModule(plugin);
      if (!mod.analyze) { showToast(`${plugin.name} has no analyze hook.`, 'error'); return; }
      setAnalysis(mod.analyze(results, cfg) || {});
    } catch (err) {
      showToast(`${plugin.name}: ${err instanceof Error ? err.message : 'analyze failed'}`, 'error');
    }
  };

  return (
    <section className="constraints-workspace-section">
      <header className="constraints-workspace-section-header">
        <h3>{plugin.name}{plugin.version ? ` · v${plugin.version}` : ''}</h3>
        {plugin.description && <p>{plugin.description}</p>}
      </header>

      {!enabled ? (
        <div className="constraints-empty">
          <p>This plugin is disabled. Enable it in the list on the left to configure and run it.</p>
        </div>
      ) : (
        <>
          <div className="sg-setting-row">
            <label className="sg-setting-label">Config (JSON)</label>
            <textarea
              className="constraints-dsl-input"
              rows={6}
              value={JSON.stringify(cfg, null, 2)}
              onChange={(e) => { try { host.setConfig(plugin.id, JSON.parse(e.target.value || '{}')); } catch { /* keep typing */ } }}
            />
          </div>
          <div className="sg-setting-row">
            <div className="sg-btn-row">
              {(caps.transform || caps.contribute) && <button className="tb-btn" onClick={apply}>Apply to model</button>}
              {caps.analyze && <button className="tb-btn tb-btn--muted" onClick={analyze}>Analyze output</button>}
            </div>
            {!caps.transform && !caps.contribute && !caps.analyze && (
              <p className="sg-setting-hint">This plugin exposes no transform / contribute / analyze hook.</p>
            )}
          </div>
          {analysis && <pre className="plugin-analyze-out">{JSON.stringify(analysis, null, 2)}</pre>}
        </>
      )}
    </section>
  );
}
