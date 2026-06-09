/**
 * Detail pane for one BACKEND (server-side) plugin.
 *
 * Renders the same config panel used for browser plugins (via PluginPanel), but
 * action hooks run on the server: a `transform`/`contribute` action POSTs to
 * `/api/plugins/{id}/{hook}`, the backend writes the model into the session, and
 * the parent rehydrates the editor from there. The model never enters the
 * browser — the frontend only sends config and reads back the session meta.
 *
 * A manifest `file` field is NOT rendered as a base64 input here (that put the
 * whole upload in the browser config — slow + leaky). Instead it becomes a
 * server-side file picker: the file is uploaded ONCE to the plugin's scratch
 * dir, and the config holds only the chosen filename. So nothing heavy lives in
 * the browser, and editing any other field stays cheap.
 */
import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  ModuleConfigField,
  ModuleConfigSchema,
  ModuleDescriptor,
  ModulePanelConfig,
  WorkbookModel,
} from 'lib/types';
import {
  BackendPluginManifest,
  PluginFile,
  deletePluginFile,
  listPluginFiles,
  runBackendHook,
  uploadPluginFile,
} from 'lib/api/plugins';
import type { SessionMeta } from 'lib/api/session';
import { PluginPanel } from './PluginPanel';
import { SearchableSelect } from '../../shared/components/SearchableSelect';
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

function toDescriptor(manifest: BackendPluginManifest, schema: ModuleConfigSchema): ModuleDescriptor {
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
    config: schema,
    panel: (m.panel ?? undefined) as ModulePanelConfig | undefined,
  };
}

/** Safety net: never persist an oversized/binary value (a stray base64 blob). */
function isHeavyValue(v: unknown): boolean {
  return typeof v === 'string' && (v.length > 50_000 || v.startsWith('data:'));
}

/**
 * Backend plugins must NOT fetch dropdown options from an external server while
 * the user edits (that "handles data in the middle" — the lag/leak source, and
 * it couples a backend plugin to a separate localhost server). A manifest can
 * declare server-sourced options in several nested shapes (`optionsFrom`,
 * `optionsFromByColumn.cases.*`, table-column `lookup`, …), so we DEEP-walk the
 * schema and neutralise every object with ``source: 'server'`` (drop its
 * endpoint) — wherever it is. The form then uses static options only; the rules
 * are sent as-is and resolved once on the build.
 */
function stripServerOptions(schema: ModuleConfigSchema): ModuleConfigSchema {
  const walk = (v: unknown): unknown => {
    if (Array.isArray(v)) return v.map(walk);
    if (v && typeof v === 'object') {
      const out: Record<string, unknown> = {};
      for (const [k, val] of Object.entries(v as Record<string, unknown>)) out[k] = walk(val);
      if (out.source === 'server') {
        out.source = 'static'; // no live fetch — fall back to static options
        delete out.endpoint;
      }
      return out;
    }
    return v;
  };
  return walk(schema) as ModuleConfigSchema;
}

/**
 * Upload-once + pick-from-dropdown control for a `file`-typed manifest field.
 * The file is streamed to the plugin's server-side scratch dir; the config
 * holds only the chosen filename.
 */
function ServerFilePicker({
  pluginId,
  fieldKey,
  field,
  value,
  onChange,
}: {
  pluginId: string;
  fieldKey: string;
  field: ModuleConfigField;
  value: string;
  onChange: (filename: string) => void;
}) {
  const { showToast } = useToast();
  const [files, setFiles] = useState<PluginFile[]>([]);
  const [busy, setBusy] = useState(false);
  const inputRef = useRef<HTMLInputElement | null>(null);

  const refresh = async () => {
    try { setFiles(await listPluginFiles(pluginId)); } catch { /* leave as-is */ }
  };
  useEffect(() => {
    void refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pluginId]);

  const onUpload = async (file: File | undefined) => {
    if (!file) return;
    setBusy(true);
    try {
      const up = await uploadPluginFile(pluginId, file);
      await refresh();
      onChange(up.name);
      showToast(`Uploaded ${up.name}`, 'success');
    } catch (err) {
      showToast(`Upload failed: ${err instanceof Error ? err.message : 'error'}`, 'error');
    } finally {
      setBusy(false);
      if (inputRef.current) inputRef.current.value = '';
    }
  };

  const onDelete = async () => {
    if (!value) return;
    setBusy(true);
    try {
      await deletePluginFile(pluginId, value);
      onChange('');
      await refresh();
    } catch (err) {
      showToast(`Delete failed: ${err instanceof Error ? err.message : 'error'}`, 'error');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="sg-module-config-row sg-module-config-row--file">
      <span className="sg-module-config-label">{field.label ?? fieldKey}</span>
      <div className="be-file-picker">
        <SearchableSelect
          className="sg-module-config-select"
          value={value}
          options={[{ value: '', label: '— none —' }, ...files.map((f) => ({ value: f.name, label: f.name }))]}
          onChange={onChange}
          placeholder="Select an uploaded file…"
        />
        <input
          ref={inputRef}
          type="file"
          accept={field.accept}
          style={{ display: 'none' }}
          onChange={(e) => void onUpload(e.target.files?.[0])}
        />
        <button className="tb-btn" disabled={busy} onClick={() => inputRef.current?.click()}>
          {busy ? 'Uploading…' : 'Upload…'}
        </button>
        {value && (
          <button className="tb-btn tb-btn--muted" disabled={busy} onClick={() => void onDelete()} title="Delete this file from the server">
            Delete
          </button>
        )}
      </div>
      {field.description && <p className="sg-setting-hint">{field.description}</p>}
    </div>
  );
}

export function BackendPluginDetail({ manifest, model, onBuilt }: Props) {
  const { showToast } = useToast();
  // Config lives in plain React state (fast, in-memory) and is persisted to
  // localStorage on a DEBOUNCE — never on every keystroke. Heavy/binary values
  // are never persisted (and with the server-file picker the config no longer
  // holds file bytes at all — only a filename reference).
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

  // `file` fields are rendered as server-side pickers (above); everything else
  // is rendered by PluginPanel from a schema with the file fields removed.
  const fileFields = useMemo(
    () => Object.entries(manifest.config ?? {}).filter(([, f]) => f?.type === 'file'),
    [manifest.config],
  );
  const panelSchema = useMemo(() => {
    const out: ModuleConfigSchema = { ...(manifest.config ?? {}) };
    for (const [k] of fileFields) delete out[k];
    return stripServerOptions(out);
  }, [manifest.config, fileFields]);

  const descriptor = useMemo(() => toDescriptor(manifest, panelSchema), [manifest, panelSchema]);
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
    const hook = field.hook ?? (manifest.hooks.transform ? 'transform' : 'contribute');
    if (hook !== 'transform' && hook !== 'contribute') {
      showToast(`This action ("${hook}") has no server-side hook.`, 'info');
      return;
    }
    await runHook(hook, field.successMessage);
  };

  const hasActionField = Object.values(manifest.config ?? {}).some((f) => f?.type === 'action');
  const fallbackHook: 'transform' | 'contribute' | null =
    manifest.hooks.transform ? 'transform' : manifest.hooks.contribute ? 'contribute' : null;

  return (
    <div className="plugin-detail">
      {fileFields.length > 0 && (
        <div className="plugin-panel-section be-file-section">
          {fileFields.map(([key, field]) => (
            <ServerFilePicker
              key={key}
              pluginId={manifest.id}
              fieldKey={key}
              field={field}
              value={String(config[key] ?? '')}
              onChange={(filename) => setConfigValue(key, filename)}
            />
          ))}
        </div>
      )}
      <PluginPanel
        modules={[descriptor]}
        moduleConfigs={{ [manifest.id]: withDefaults(panelSchema, config) }}
        onModuleConfigChange={(_id, key, value) => setConfigValue(key, value)}
        carriers={carriers}
        model={model}
        pluginAnalytics={{}}
        onModuleAction={handleAction}
      />
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
