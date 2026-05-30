/**
 * Plugins tab — install and manage frontend plugins.
 *
 * Plugins are installed into a frontend "plugin location" (browser storage),
 * configured here, and run in the browser. They never talk to the Ragnarok
 * backend. No sample plugins are bundled — install your own `.zip` package
 * (a `module.json` manifest + its files).
 */
import React, { useRef, useState } from 'react';
import { FrontendPluginHost } from './frontendPlugins';

export interface PluginManagerPanelProps {
  host: FrontendPluginHost;
}

export function PluginManagerPanel({ host }: PluginManagerPanelProps) {
  const fileRef = useRef<HTMLInputElement | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const onPick = async (file: File | undefined) => {
    if (!file) return;
    const result = await host.install(file);
    setMessage(result.ok ? `Installed "${result.id}".` : `Install failed: ${result.error}`);
    if (fileRef.current) fileRef.current.value = '';
  };

  return (
    <section className="constraints-workspace-section">
      <header className="constraints-workspace-section-header">
        <h3>Plugins</h3>
        <p>Install a plugin package (<code>.zip</code>) into the frontend. Plugins run in the browser and feed the model / read run output — they never contact the Ragnarok backend directly.</p>
      </header>

      <div className="sg-setting-row">
        <input
          ref={fileRef}
          type="file"
          accept=".zip"
          style={{ display: 'none' }}
          onChange={(e) => onPick(e.target.files?.[0])}
        />
        <div className="sg-btn-row">
          <button className="tb-btn" onClick={() => fileRef.current?.click()}>Install plugin…</button>
        </div>
        {message && <p className="sg-setting-hint">{message}</p>}
      </div>

      {host.installed.length === 0 ? (
        <div className="constraints-empty">
          <p>No plugins installed. Use “Install plugin…” to add one.</p>
        </div>
      ) : (
        <div className="plugin-list">
          {host.installed.map((p) => (
            <div key={p.id} className="plugin-list-item">
              <label className="plugin-list-head">
                <input
                  type="checkbox"
                  className="gcc-check"
                  checked={host.isEnabled(p.id)}
                  onChange={(e) => host.toggle(p.id, e.target.checked)}
                />
                <strong>{p.name}</strong>
                {p.version && <span className="plugin-list-version">v{p.version}</span>}
                <button className="gcc-del" title="Uninstall" onClick={() => host.uninstall(p.id)}>x</button>
              </label>
              {p.description && <p className="sg-setting-hint">{p.description}</p>}
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
