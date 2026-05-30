/**
 * Detail pane for one installed plugin: config + run actions + analyze output.
 *
 * When the plugin manifest declares a config *schema* (field descriptors), we
 * render the same rich panel the V1 module system used — Description / Input /
 * Output inner tabs, the `panel.inputLayout` grid, grouped sections, and every
 * field/table editor (via PluginPanel + ConfigFieldRow). A schema-less manifest
 * falls back to a raw JSON config box. Everything runs in the browser; the
 * plugin never contacts the Ragnarok backend.
 */
import React, { useEffect, useMemo, useState } from 'react';
import {
  GridRow,
  ModuleConfigField,
  ModuleConfigSchema,
  ModuleDescriptor,
  ModulePanelConfig,
  PluginAnalyticsEntry,
  WorkbookModel,
} from '../../shared/types';
import { FrontendPluginHost, InstalledPlugin } from './frontendPlugins';
import { loadPluginModule, pluginCapabilities } from './pluginRuntime';
import { PluginPanel } from './PluginPanel';
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

/** True when the manifest `config` is a field *schema* (descriptors with a `type`). */
function isConfigSchema(config: unknown): config is ModuleConfigSchema {
  if (!config || typeof config !== 'object') return false;
  const values = Object.values(config as Record<string, unknown>);
  return values.length > 0 && values.every((v) => v !== null && typeof v === 'object' && typeof (v as { type?: unknown }).type === 'string');
}

/** Merge schema defaults under the stored values so hooks + `visibleWhen` see complete config. */
function withDefaults(schema: ModuleConfigSchema | undefined, stored: Record<string, unknown>): Record<string, unknown> {
  if (!schema) return { ...stored };
  const out: Record<string, unknown> = {};
  for (const [key, field] of Object.entries(schema)) {
    if (field.type === 'group' || field.type === 'action') continue;
    if (field.default !== undefined) out[key] = field.default;
  }
  return { ...out, ...stored };
}

function manifestToDescriptor(plugin: InstalledPlugin, schema: ModuleConfigSchema | undefined): ModuleDescriptor {
  const m = plugin.manifest as Record<string, unknown>;
  return {
    id: plugin.id,
    name: plugin.name,
    version: plugin.version ?? String(m.version ?? ''),
    sdkVersion: String(m.sdkVersion ?? ''),
    entry: String(m.entry ?? ''),
    entryPath: String(m.entry ?? ''),
    entryExists: true,
    description: plugin.description ?? '',
    capabilities: (Array.isArray(m.capabilities) ? m.capabilities : []) as ModuleDescriptor['capabilities'],
    permissions: (Array.isArray(m.permissions) ? m.permissions : []) as ModuleDescriptor['permissions'],
    compatible: true,
    valid: true,
    status: 'ready',
    diagnostics: [],
    manifestPath: 'module.json',
    modulePath: '(browser plugin)',
    isManaged: false,
    config: schema,
    panel: (m.panel ?? undefined) as ModulePanelConfig | undefined,
  };
}

export function PluginDetail({ host, plugin, model, onReplaceModel, onMergeSheets, customDsl, onCustomDslChange, results }: PluginDetailProps) {
  const { showToast } = useToast();
  const [analytics, setAnalytics] = useState<PluginAnalyticsEntry | null>(null);
  const [busy, setBusy] = useState(false);

  const caps = pluginCapabilities(plugin);
  const schema = isConfigSchema(plugin.manifest.config) ? (plugin.manifest.config as ModuleConfigSchema) : undefined;
  const hasActionField = !!schema && Object.values(schema).some((f) => f.type === 'action');

  const descriptor = useMemo(() => manifestToDescriptor(plugin, schema), [plugin, schema]);
  const carriers = useMemo(
    () => ((model.carriers as GridRow[] | undefined) ?? []).map((r) => String(r.name ?? '')).filter(Boolean),
    [model.carriers],
  );

  // Apply the plugin's contribution to the model: a transform replaces the whole
  // workbook; a contribution merges sheets + appends constraint DSL lines.
  const apply = async (successMessage?: string) => {
    const mod = loadPluginModule(plugin);
    const cfg = withDefaults(schema, host.getConfig(plugin.id));
    if (mod.transform) {
      const next = await mod.transform(model, cfg);
      if (!next || typeof next !== 'object') throw new Error('transform() did not return a model.');
      onReplaceModel(next as WorkbookModel);
      showToast(successMessage ?? `${plugin.name}: model replaced.`, 'success');
      return;
    }
    if (mod.contribute) {
      const out = (await mod.contribute(model, cfg)) || {};
      if (out.sheets && typeof out.sheets === 'object') onMergeSheets(out.sheets);
      if (Array.isArray(out.constraints) && out.constraints.length) {
        const block = [`# ${plugin.name} (plugin)`, ...out.constraints].join('\n');
        onCustomDslChange(customDsl.trim() ? `${customDsl.replace(/\s+$/, '')}\n${block}\n` : `${block}\n`);
      }
      showToast(successMessage ?? `${plugin.name}: contributed to the model.`, 'success');
      return;
    }
    throw new Error(`${plugin.name} has no transform/contribute hook.`);
  };

  // In-form action button (e.g. "Send model to Ragnarok"). ActionFieldRow owns
  // its own spinner, so we resolve cleanly and surface errors as a toast.
  const handleAction = async (_moduleId: string, _fieldKey: string, field: ModuleConfigField) => {
    try {
      await apply(field.successMessage);
    } catch (err) {
      showToast(`${plugin.name}: ${err instanceof Error ? err.message : 'failed'}`, 'error');
    }
  };

  const applyFromFooter = async () => {
    setBusy(true);
    try {
      await apply();
    } catch (err) {
      showToast(`${plugin.name}: ${err instanceof Error ? err.message : 'failed'}`, 'error');
    } finally {
      setBusy(false);
    }
  };

  // Auto-run the analyze hook so the Output tab reflects the latest run, the way
  // the V1 backend populated pluginAnalytics after each solve.
  useEffect(() => {
    let cancelled = false;
    if (!caps.analyze || !results) {
      setAnalytics(null);
      return;
    }
    (async () => {
      try {
        const mod = loadPluginModule(plugin);
        const cfg = withDefaults(schema, host.getConfig(plugin.id));
        const data = (await mod.analyze!(results, cfg)) || {};
        if (!cancelled) setAnalytics({ name: plugin.name, ui: {}, data });
      } catch {
        if (!cancelled) setAnalytics(null);
      }
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [results, plugin.id]);

  if (schema) {
    return (
      <div className="plugin-detail">
        <PluginPanel
          modules={[descriptor]}
          moduleConfigs={{ [plugin.id]: withDefaults(schema, host.getConfig(plugin.id)) }}
          onModuleConfigChange={(id, key, value) => host.setConfigField(id, key, value)}
          carriers={carriers}
          pluginAnalytics={analytics ? { [plugin.id]: analytics } : {}}
          onModuleAction={handleAction}
        />
        {!hasActionField && (caps.transform || caps.contribute) && (
          <div className="sg-setting-row plugin-detail-footer">
            <button className="tb-btn" disabled={busy} onClick={applyFromFooter}>
              {busy ? 'Working…' : 'Apply to model'}
            </button>
          </div>
        )}
      </div>
    );
  }

  // Schema-less manifest: raw JSON config + run buttons.
  const cfg = host.getConfig(plugin.id);
  return (
    <section className="constraints-workspace-section">
      <header className="constraints-workspace-section-header">
        <h3>{plugin.name}{plugin.version ? ` · v${plugin.version}` : ''}</h3>
        {plugin.description && <p>{plugin.description}</p>}
      </header>
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
          {(caps.transform || caps.contribute) && <button className="tb-btn" disabled={busy} onClick={applyFromFooter}>{busy ? 'Working…' : 'Apply to model'}</button>}
        </div>
        {!caps.transform && !caps.contribute && !caps.analyze && (
          <p className="sg-setting-hint">This plugin exposes no transform / contribute / analyze hook.</p>
        )}
      </div>
    </section>
  );
}
