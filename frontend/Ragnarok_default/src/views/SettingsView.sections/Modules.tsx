/**
 * Modules section — compose the workspace: which module tabs are on the bar.
 *
 * Two halves:
 *  • BUILT-IN modules (src/modules/registry) — compiled in, toggled here.
 *  • EXTERNAL modules — third-party tabs added from a directory or .zip
 *    (a `tabmodule.json` manifest + a CommonJS entry exporting mount(el, ctx)).
 *
 * Core tabs — Build, Model, Market & Policy, Settings, Analytics, History,
 * Plugins — are the modelling loop itself and are not listed; they can never
 * be switched off. This is NOT the plugin manager: plugins are the SMALL
 * extension system with its own tab; a module is a whole tab.
 */
import React, { useRef, useState } from 'react';
import { TAB_MODULES, parseEnabledModules, serializeEnabledModules } from '../../modules/registry';
import type { TabModuleId } from '../../modules/types';
import type { ExternalModulesApi } from '../../modules/external/useExternalModules';
import { MANIFEST_NAME } from '../../modules/external/api';

export interface ModulesSectionProps {
  /** The csv persisted in AppSettings.enabledModules. */
  enabledModules: string;
  onEnabledModulesChange: (csv: string) => void;
  externalModules: ExternalModulesApi;
}

export function ModulesSection({ enabledModules, onEnabledModulesChange, externalModules }: ModulesSectionProps) {
  const enabled = parseEnabledModules(enabledModules);
  const dirInputRef = useRef<HTMLInputElement | null>(null);
  const zipInputRef = useRef<HTMLInputElement | null>(null);
  const [installError, setInstallError] = useState<string | null>(null);

  const toggle = (id: TabModuleId) => {
    const next = new Set(enabled);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    onEnabledModulesChange(serializeEnabledModules(next));
  };

  const [busy, setBusy] = useState(false);

  const handlePicked = async (files: FileList | null) => {
    if (!files || files.length === 0) return;
    setInstallError(null);
    setBusy(true);
    try {
      await externalModules.install(Array.from(files));
    } catch (err) {
      setInstallError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const handleRemove = async (id: string, label: string) => {
    setInstallError(null);
    try {
      await externalModules.remove(id);
    } catch (err) {
      setInstallError(`Could not remove ${label}: ${err instanceof Error ? err.message : String(err)}`);
    }
  };

  return (
    <section className="constraints-workspace-section">
      <header className="constraints-workspace-section-header">
        <h3>Modules</h3>
        <p>
          Compose this workspace: each module is a whole Ragnarok tab that can be switched
          off when a project doesn&apos;t need it. The core tabs — Build, Model, Market &amp;
          Policy, Settings, Analytics, History, Plugins — are the modelling loop itself and
          are always on. Turning a module off only hides its tab; nothing is uninstalled,
          and the model, settings and results are untouched.
          (Third-party <b>plugins</b> are the small extension system — manage those on the
          Plugins tab. A <b>module</b> is bigger: a whole tab, first- or third-party.)
        </p>
      </header>

      <div className="settings-modules-list">
        {TAB_MODULES.map((m) => (
          <label key={m.id} className="settings-modules-item">
            <input
              type="checkbox"
              checked={enabled.has(m.id)}
              onChange={() => toggle(m.id)}
              aria-label={`Enable the ${m.label} tab`}
            />
            <span className="settings-modules-icon" aria-hidden>{m.icon}</span>
            <span className="settings-modules-text">
              <span className="settings-modules-name">{m.label}</span>
              <span className="settings-modules-desc">{m.description}</span>
            </span>
          </label>
        ))}
      </div>

      <header className="constraints-workspace-section-header" style={{ marginTop: 24 }}>
        <h3>External modules</h3>
        <p>
          Add a module from outside the app: pick its directory (or a .zip of it). The
          package needs a <code>{MANIFEST_NAME}</code> manifest and a CommonJS entry file
          exporting <code>mount(el, ctx)</code> — <code>ctx</code> carries the backend API
          base and session id, which is the same reach a native tab has: read the working
          model, submit runs, read analytics. Re-adding the same id updates it in place.
          Installed modules are stored on the <b>server</b> (<code>backend/data/modules/</code>),
          so they survive a &quot;Clear cache&quot;, an app update and a different browser.
        </p>
      </header>

      <div className="section-toolbar">
        <input
          ref={dirInputRef}
          type="file"
          // Non-standard but universal in Chromium/WebKit — directory picking.
          {...({ webkitdirectory: '', directory: '' } as Record<string, string>)}
          multiple
          hidden
          onChange={(e) => { void handlePicked(e.target.files); e.target.value = ''; }}
        />
        <input
          ref={zipInputRef}
          type="file"
          accept=".zip,application/zip"
          multiple
          hidden
          onChange={(e) => { void handlePicked(e.target.files); e.target.value = ''; }}
        />
        <button className="ghost-button sm" disabled={busy} onClick={() => dirInputRef.current?.click()}>
          {busy ? 'Installing…' : 'Add module from folder'}
        </button>
        <button className="ghost-button sm" disabled={busy} onClick={() => zipInputRef.current?.click()}>
          Add module from .zip
        </button>
      </div>
      {installError && <p className="settings-modules-error">{installError}</p>}

      {externalModules.installed.length === 0 ? (
        <p className="settings-modules-empty">
          {externalModules.loading ? 'Loading installed modules…' : 'No external modules installed.'}
        </p>
      ) : (
        <div className="settings-modules-list">
          {externalModules.installed.map((m) => (
            <div key={m.manifest.id} className="settings-modules-item">
              <input
                type="checkbox"
                checked={m.enabled}
                onChange={(e) => { void externalModules.setEnabled(m.manifest.id, e.target.checked); }}
                aria-label={`Enable the ${m.manifest.label} tab`}
              />
              <span className="settings-modules-text">
                <span className="settings-modules-name">
                  {m.manifest.label}
                  <span className="settings-modules-id"> · {m.manifest.id}</span>
                </span>
                <span className="settings-modules-desc">
                  {m.manifest.description || 'No description provided.'}
                </span>
              </span>
              <button
                className="ghost-button sm"
                onClick={() => { void handleRemove(m.manifest.id, m.manifest.label); }}
                title="Uninstall this module (its tab disappears; nothing else changes)"
              >
                Remove
              </button>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
