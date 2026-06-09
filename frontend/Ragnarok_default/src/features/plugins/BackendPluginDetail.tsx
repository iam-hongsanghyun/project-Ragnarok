/**
 * Detail pane for one BACKEND (server-side) plugin.
 *
 * Renders the same config panel used for browser plugins (via PluginPanel), but
 * action hooks run on the server: a `transform`/`contribute` action POSTs to
 * `/api/plugins/{id}/{hook}`, the backend writes the model into the session, and
 * the parent rehydrates the editor from there. The model never enters the
 * browser — the frontend only sends config and reads back the session meta.
 */
import React, { useEffect, useMemo, useState } from 'react';
import {
  ModuleConfigField,
  ModuleConfigSchema,
  ModuleDescriptor,
  ModulePanelConfig,
  WorkbookModel,
} from 'lib/types';
import { BackendPluginManifest, runBackendHook } from 'lib/api/plugins';
import type { SessionMeta } from 'lib/api/session';
import { PluginPanel } from './PluginPanel';
import { useToast } from '../../shared/components/Toast';

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

/** A binary `file` field holds the whole upload as a multi-MB base64 `data:`
 *  string. Persisting that to localStorage on every config edit makes the form
 *  crawl (same bug as frontend plugins), so heavy values are kept in memory
 *  only and merged over the persisted (light) config. */
function isHeavyValue(v: unknown): boolean {
  return typeof v === 'string' && (v.length > 50_000 || v.startsWith('data:'));
}

export function BackendPluginDetail({ manifest, model, onBuilt }: Props) {
  const { showToast } = useToast();
  // Config lives in plain React state (fast, in-memory) and is persisted to
  // localStorage on a DEBOUNCE — never on every keystroke. A synchronous
  // JSON.stringify + setItem of this (large, table-heavy) config per character
  // is what made typing lag. Heavy/binary values (uploaded files) are never
  // persisted (re-select after a reload).
  const storeKey = `ui:be-plugin-cfg:${manifest.id}`;
  const [config, setConfig] = useState<Record<string, unknown>>(() => {
    try {
      const raw = window.localStorage.getItem(storeKey);
      return raw ? (JSON.parse(raw) as Record<string, unknown>) : {};
    } catch {
      return {};
    }
  });
  const setConfigValue = (key: string, value: unknown) => setConfig((prev) => ({ ...prev, [key]: value }));
  useEffect(() => {
    const id = window.setTimeout(() => {
      try {
        const slim: Record<string, unknown> = {};
        for (const [k, v] of Object.entries(config)) {
          if (!isHeavyValue(v)) slim[k] = v;
        }
        window.localStorage.setItem(storeKey, JSON.stringify(slim));
      } catch {
        /* quota / privacy mode — ignore */
      }
    }, 400);
    return () => window.clearTimeout(id);
  }, [config, storeKey]);
  const [busy, setBusy] = useState(false);

  const descriptor = useMemo(() => toDescriptor(manifest), [manifest]);
  const carriers = useMemo(
    () => ((model.carriers as Array<Record<string, unknown>> | undefined) ?? []).map((r) => String(r.name ?? '')).filter(Boolean),
    [model.carriers],
  );

  const runHook = async (hook: 'transform' | 'contribute', successMessage?: string) => {
    setBusy(true);
    try {
      const meta = await runBackendHook(manifest.id, hook, withDefaults(manifest.config, config), {
        filename: `${manifest.id}.xlsx`,
      });
      onBuilt(meta);
      showToast(successMessage ?? `${manifest.name}: applied to the session.`, 'success');
    } catch (err) {
      showToast(`${manifest.name}: ${err instanceof Error ? err.message : 'failed'}`, 'error');
    } finally {
      setBusy(false);
    }
  };

  const handleAction = async (_moduleId: string, _fieldKey: string, field: ModuleConfigField) => {
    // Default action verb is the model-producing hook the plugin exposes.
    const hook = field.hook ?? (manifest.hooks.transform ? 'transform' : 'contribute');
    if (hook !== 'transform' && hook !== 'contribute') {
      // e.g. a frontend-only named action (fill table) that has no server hook.
      showToast(`This action ("${hook}") has no server-side hook.`, 'info');
      return;
    }
    await runHook(hook, field.successMessage);
  };

  const hasActionField = Object.values(manifest.config ?? {}).some((f) => f?.type === 'action');
  // Fallback button verb when the manifest declares no action field.
  const fallbackHook: 'transform' | 'contribute' | null =
    manifest.hooks.transform ? 'transform' : manifest.hooks.contribute ? 'contribute' : null;

  return (
    <div className="plugin-detail">
      <PluginPanel
        modules={[descriptor]}
        moduleConfigs={{ [manifest.id]: withDefaults(manifest.config, config) }}
        onModuleConfigChange={(_id, key, value) => setConfigValue(key, value)}
        carriers={carriers}
        model={model}
        pluginAnalytics={{}}
        onModuleAction={handleAction}
      />
      {/* Schema with no action field: offer a default apply button. */}
      {fallbackHook && !hasActionField && (
        <div className="sg-setting-row plugin-detail-footer">
          <button className="tb-btn" disabled={busy} onClick={() => runHook(fallbackHook)}>
            {busy ? 'Working…' : 'Build & load into Ragnarok'}
          </button>
        </div>
      )}
    </div>
  );
}
