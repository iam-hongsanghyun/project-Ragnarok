/**
 * Detail pane for one BACKEND (server-side) plugin.
 *
 * Renders the same config panel used for browser plugins (via PluginPanel), but
 * action hooks run on the server: a `build` action POSTs to
 * `/api/plugins/{id}/build`, the backend writes the model into the session, and
 * the parent rehydrates the editor from there. The model never enters the
 * browser — the frontend only sends config and reads back the session meta.
 */
import React, { useMemo, useState } from 'react';
import {
  ModuleConfigField,
  ModuleConfigSchema,
  ModuleDescriptor,
  ModulePanelConfig,
  WorkbookModel,
} from 'lib/types';
import { BackendPluginManifest, buildBackendPlugin } from 'lib/api/plugins';
import type { SessionMeta } from 'lib/api/session';
import { PluginPanel } from './PluginPanel';
import { useToast } from '../../shared/components/Toast';
import { usePersistedState } from 'shared/hooks/usePersistedState';

interface Props {
  manifest: BackendPluginManifest;
  model: WorkbookModel;
  onBuilt: (meta: SessionMeta) => void;
}

/** Merge schema defaults under stored values so hooks see a complete config. */
function withDefaults(schema: ModuleConfigSchema | undefined, stored: Record<string, unknown>): Record<string, unknown> {
  if (!schema) return { ...stored };
  const out: Record<string, unknown> = {};
  for (const [key, field] of Object.entries(schema)) {
    if (field.type === 'group' || field.type === 'action') continue;
    if (field.default !== undefined) out[key] = field.default;
  }
  return { ...out, ...stored };
}

function toDescriptor(manifest: BackendPluginManifest): ModuleDescriptor {
  const m = manifest as unknown as Record<string, unknown>;
  return {
    id: manifest.id,
    name: manifest.name,
    version: manifest.version,
    sdkVersion: '',
    entry: '',
    entryPath: '',
    entryExists: true,
    description: manifest.description ?? '',
    capabilities: (manifest.capabilities ?? []) as ModuleDescriptor['capabilities'],
    permissions: [],
    compatible: true,
    valid: true,
    status: 'ready',
    diagnostics: [],
    manifestPath: 'manifest.json',
    modulePath: '(backend plugin)',
    isManaged: false,
    config: manifest.config,
    panel: (m.panel ?? undefined) as ModulePanelConfig | undefined,
  };
}

export function BackendPluginDetail({ manifest, model, onBuilt }: Props) {
  const { showToast } = useToast();
  const [config, setConfig] = usePersistedState<Record<string, unknown>>(`ui:be-plugin-cfg:${manifest.id}`, {});
  const [busy, setBusy] = useState(false);

  const descriptor = useMemo(() => toDescriptor(manifest), [manifest]);
  const carriers = useMemo(
    () => ((model.carriers as Array<Record<string, unknown>> | undefined) ?? []).map((r) => String(r.name ?? '')).filter(Boolean),
    [model.carriers],
  );

  const handleAction = async (_moduleId: string, _fieldKey: string, field: ModuleConfigField) => {
    const hook = field.hook ?? 'build';
    if (hook !== 'build') {
      showToast(`This backend plugin action ("${hook}") isn't wired in the UI yet.`, 'info');
      return;
    }
    setBusy(true);
    try {
      const meta = await buildBackendPlugin(manifest.id, withDefaults(manifest.config, config), {
        filename: `${manifest.id}.xlsx`,
      });
      onBuilt(meta);
      showToast(field.successMessage ?? `${manifest.name}: built into the session.`, 'success');
    } catch (err) {
      showToast(`${manifest.name}: ${err instanceof Error ? err.message : 'build failed'}`, 'error');
    } finally {
      setBusy(false);
    }
  };

  const hasActionField = Object.values(manifest.config ?? {}).some((f) => f?.type === 'action');

  return (
    <div className="plugin-detail">
      <div className="plugin-detail-kind" title="Runs on the server, using the bundled PyPSA source">
        Backend plugin · v{manifest.version}
      </div>
      <PluginPanel
        modules={[descriptor]}
        moduleConfigs={{ [manifest.id]: withDefaults(manifest.config, config) }}
        onModuleConfigChange={(_id, key, value) => setConfig({ ...config, [key]: value })}
        carriers={carriers}
        model={model}
        pluginAnalytics={{}}
        onModuleAction={handleAction}
      />
      {/* Schema with no action field: offer a default Build button. */}
      {manifest.hooks.build && !hasActionField && (
        <div className="sg-setting-row plugin-detail-footer">
          <button
            className="tb-btn"
            disabled={busy}
            onClick={() => handleAction(manifest.id, 'build', { type: 'action', hook: 'build' } as ModuleConfigField)}
          >
            {busy ? 'Building…' : 'Build & load into Ragnarok'}
          </button>
        </div>
      )}
    </div>
  );
}
