/**
 * Plugins view — install + manage plugins of two kinds:
 *   • frontend plugins — browser-evaluated JS (installed from a .zip); run in
 *     the browser and never contact the Ragnarok backend.
 *   • backend plugins — installed server-side (uploaded .zip → GET /api/plugins);
 *     run in the Ragnarok backend and import the bundled PyPSA source directly. A
 *     backend `transform` plugin writes its model straight into the session.
 *
 * A left rail lists both (backend ones grouped under their own heading); the
 * main pane shows the selected plugin's config + actions.
 */
import React, { useEffect, useRef, useState } from 'react';
import { WorkbookModel } from 'lib/types';
import { FrontendPluginHost, peekPackageKind } from '../features/plugins/frontendPlugins';
import { PluginDetail } from '../features/plugins/PluginDetail';
import { BackendPluginDetail } from '../features/plugins/BackendPluginDetail';
import { BackendPluginManifest, installBackendPlugin, listBackendPlugins, uninstallBackendPlugin } from 'lib/api/plugins';
import type { SessionMeta } from 'lib/api/session';
import { useToast } from '../shared/components/Toast';
import { ResizablePanels } from '../layout/ResizablePanels';
import { LeftRail } from '../shared/components/primitives';
import { usePersistedState } from 'shared/hooks/usePersistedState';

interface Props {
  host: FrontendPluginHost;
  model: WorkbookModel;
  onReplaceModel: (next: WorkbookModel) => void;
  onMergeSheets: (sheets: Record<string, WorkbookModel[string]>) => void;
  customDsl: string;
  onCustomDslChange: (text: string) => void;
  results: unknown;
  /** Called after a backend plugin builds a model into the session, so the
   *  editor can rehydrate from the (now-updated) session. */
  onBackendModelBuilt: (meta: SessionMeta) => void;
}

export function PluginsView(props: Props) {
  const { host } = props;
  const fileRef = useRef<HTMLInputElement | null>(null);
  const { showToast } = useToast();
  // Selection key: "fe:<id>" (frontend) or "be:<id>" (backend). Persisted so it
  // survives leaving/re-entering the tab.
  const [selectedKey, setSelectedKey] = usePersistedState<string | null>('ui:plugin-selected', null);
  const [backendPlugins, setBackendPlugins] = useState<BackendPluginManifest[]>([]);

  const refreshBackendPlugins = React.useCallback(async () => {
    try { setBackendPlugins(await listBackendPlugins()); } catch { /* backend down — leave as-is */ }
  }, []);

  // Discover backend plugins once on mount (and silently no-op if the backend
  // is unreachable — frontend plugins still work).
  useEffect(() => {
    let cancelled = false;
    void listBackendPlugins()
      .then((list) => { if (!cancelled) setBackendPlugins(list); })
      .catch(() => { /* backend down / no plugins — leave empty */ });
    return () => { cancelled = true; };
  }, []);

  const installed = host.installed;
  const selFe = selectedKey?.startsWith('fe:') ? installed.find((p) => `fe:${p.id}` === selectedKey) : undefined;
  const selBe = selectedKey?.startsWith('be:') ? backendPlugins.find((p) => `be:${p.id}` === selectedKey) : undefined;
  // Default selection: first frontend, else first backend.
  const fallback = installed[0] ? `fe:${installed[0].id}` : backendPlugins[0] ? `be:${backendPlugins[0].id}` : null;
  const effectiveKey = selFe || selBe ? selectedKey : fallback;
  const activeFe = effectiveKey?.startsWith('fe:') ? installed.find((p) => `fe:${p.id}` === effectiveKey) ?? null : null;
  const activeBe = effectiveKey?.startsWith('be:') ? backendPlugins.find((p) => `be:${p.id}` === effectiveKey) ?? null : null;

  // One "Install plugin…" button for both kinds: peek the .zip and route a
  // backend package (plugin.py / manifest kind:"backend") to the server install
  // endpoint, else install as a browser plugin.
  const onPick = async (file: File | undefined) => {
    if (!file) return;
    try {
      const kind = await peekPackageKind(file);
      if (kind === 'backend') {
        const manifest = await installBackendPlugin(file);
        await refreshBackendPlugins();
        setSelectedKey(`be:${manifest.id}`);
        showToast(`Installed "${manifest.id}" (backend)`, 'success');
      } else {
        const result = await host.install(file);
        showToast(result.ok ? `Installed "${result.id}"` : `Install failed: ${result.error}`, result.ok ? 'success' : 'error');
        if (result.ok && result.id) setSelectedKey(`fe:${result.id}`);
      }
    } catch (err) {
      showToast(`Install failed: ${err instanceof Error ? err.message : 'unknown error'}`, 'error');
    }
    if (fileRef.current) fileRef.current.value = '';
  };

  const onUninstallBackend = async (id: string) => {
    try {
      await uninstallBackendPlugin(id);
      // Free the browser-side footprint too: drop this plugin's persisted config
      // so nothing lingers after removal (server-side files are deleted by the
      // DELETE endpoint).
      try { window.localStorage.removeItem(`ui:be-plugin-cfg:${id}`); } catch { /* ignore */ }
      if (selectedKey === `be:${id}`) setSelectedKey(null);
      await refreshBackendPlugins();
      showToast(`Uninstalled "${id}"`, 'info');
    } catch (err) {
      showToast(`Uninstall failed: ${err instanceof Error ? err.message : 'unknown error'}`, 'error');
    }
  };

  const nothingInstalled = installed.length === 0 && backendPlugins.length === 0;

  return (
    <ResizablePanels id="plugins-rail" direction="horizontal" className="view plugins-view" initialSizes={[22, 78]} minSize={180}>
      <LeftRail title="Plugins" ariaLabel="Plugins" className="plugin-rail">
        <input ref={fileRef} type="file" accept=".zip,application/zip" style={{ display: 'none' }} onChange={(e) => onPick(e.target.files?.[0])} />
        <button className="tb-btn plugin-rail-install" onClick={() => fileRef.current?.click()}>Install plugin…</button>
        {nothingInstalled ? (
          <p className="sg-setting-hint" style={{ padding: '8px 12px' }}>No plugins installed.</p>
        ) : (
          <>
            {installed.length > 0 && (
              <ul className="plugin-rail-list">
                {installed.map((p) => (
                  <li key={p.id}>
                    <button
                      className={`plugin-rail-item${activeFe?.id === p.id ? ' plugin-rail-item--active' : ''}`}
                      onClick={() => setSelectedKey(`fe:${p.id}`)}
                    >
                      <span className="plugin-rail-name">{p.name}</span>
                      <span
                        className="gcc-del plugin-rail-remove"
                        title="Uninstall"
                        role="button"
                        onClick={(e) => { e.stopPropagation(); host.uninstall(p.id); if (selectedKey === `fe:${p.id}`) setSelectedKey(null); }}
                      >
                        x
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
            {backendPlugins.length > 0 && (
              <>
                <p className="plugin-rail-group">Backend (server-side)</p>
                <ul className="plugin-rail-list">
                  {backendPlugins.map((p) => (
                    <li key={p.id}>
                      <button
                        className={`plugin-rail-item${activeBe?.id === p.id ? ' plugin-rail-item--active' : ''}`}
                        onClick={() => setSelectedKey(`be:${p.id}`)}
                      >
                        <span className="plugin-rail-name">{p.name}</span>
                        <span
                          className="gcc-del plugin-rail-remove"
                          title="Uninstall (removes it from the server)"
                          role="button"
                          onClick={(e) => { e.stopPropagation(); void onUninstallBackend(p.id); }}
                        >
                          x
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              </>
            )}
          </>
        )}
      </LeftRail>

      <main className="view-main">
        {activeFe ? (
          <PluginDetail
            host={host}
            plugin={activeFe}
            model={props.model}
            onReplaceModel={props.onReplaceModel}
            onMergeSheets={props.onMergeSheets}
            customDsl={props.customDsl}
            onCustomDslChange={props.onCustomDslChange}
            results={props.results}
          />
        ) : activeBe ? (
          <BackendPluginDetail manifest={activeBe} model={props.model} onBuilt={props.onBackendModelBuilt} />
        ) : (
          <div className="view-empty">
            <h3>No plugins installed</h3>
            <p>Use “Install plugin…” in the rail to add a plugin <code>.zip</code> — frontend (browser JS) or backend (server-side). Examples live in <code>example_plugins/</code>.</p>
          </div>
        )}
      </main>
    </ResizablePanels>
  );
}
