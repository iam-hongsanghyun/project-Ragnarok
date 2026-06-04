/**
 * Plugins view — install + manage frontend-only plugins.
 *
 * Mirrors the Analytics layout: a left rail to install and switch between
 * plugins, and a main pane showing the selected plugin's config + actions.
 * Plugins run in the browser and never contact the Ragnarok backend.
 */
import React, { useRef, useState } from 'react';
import { WorkbookModel } from 'lib/types';
import { FrontendPluginHost } from '../features/plugins/frontendPlugins';
import { PluginDetail } from '../features/plugins/PluginDetail';
import { useToast } from '../shared/components/Toast';
import { ResizablePanels } from '../layout/ResizablePanels';
import { LeftRail } from '../shared/components/primitives';

interface Props {
  host: FrontendPluginHost;
  model: WorkbookModel;
  onReplaceModel: (next: WorkbookModel) => void;
  onMergeSheets: (sheets: Record<string, WorkbookModel[string]>) => void;
  customDsl: string;
  onCustomDslChange: (text: string) => void;
  results: unknown;
}

export function PluginsView(props: Props) {
  const { host } = props;
  const fileRef = useRef<HTMLInputElement | null>(null);
  const { showToast } = useToast();
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const installed = host.installed;
  const selected = installed.find((p) => p.id === selectedId) ?? installed[0] ?? null;

  const onPick = async (file: File | undefined) => {
    if (!file) return;
    const result = await host.install(file);
    showToast(result.ok ? `Installed "${result.id}"` : `Install failed: ${result.error}`, result.ok ? 'success' : 'error');
    if (result.ok && result.id) setSelectedId(result.id);
    if (fileRef.current) fileRef.current.value = '';
  };

  return (
    <ResizablePanels id="plugins-rail" direction="horizontal" className="view plugins-view" initialSizes={[22, 78]} minSize={180}>
      <LeftRail title="Plugins" ariaLabel="Plugins" className="plugin-rail">
        <input ref={fileRef} type="file" accept=".zip,application/zip" style={{ display: 'none' }} onChange={(e) => onPick(e.target.files?.[0])} />
        <button className="tb-btn plugin-rail-install" onClick={() => fileRef.current?.click()}>Install plugin…</button>
        {installed.length === 0 ? (
          <p className="sg-setting-hint" style={{ padding: '8px 12px' }}>No plugins installed.</p>
        ) : (
          <ul className="plugin-rail-list">
            {installed.map((p) => (
              <li key={p.id}>
                <button
                  className={`plugin-rail-item${selected?.id === p.id ? ' plugin-rail-item--active' : ''}`}
                  onClick={() => setSelectedId(p.id)}
                >
                  <span className="plugin-rail-name">{p.name}</span>
                  <span
                    className="gcc-del plugin-rail-remove"
                    title="Uninstall"
                    role="button"
                    onClick={(e) => { e.stopPropagation(); host.uninstall(p.id); if (selectedId === p.id) setSelectedId(null); }}
                  >
                    x
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </LeftRail>

      <main className="view-main">
        {selected ? (
          <PluginDetail
            host={host}
            plugin={selected}
            model={props.model}
            onReplaceModel={props.onReplaceModel}
            onMergeSheets={props.onMergeSheets}
            customDsl={props.customDsl}
            onCustomDslChange={props.onCustomDslChange}
            results={props.results}
          />
        ) : (
          <div className="view-empty">
            <h3>No plugins installed</h3>
            <p>Use “Install plugin…” in the rail to add a <code>.zip</code> package (a <code>module.json</code> manifest + JS entry).</p>
          </div>
        )}
      </main>
    </ResizablePanels>
  );
}
