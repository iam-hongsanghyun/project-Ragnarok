/**
 * Modules section — compose the workspace: which module tabs are on the bar.
 *
 * Lists every registered tab-module (src/modules/registry) with a toggle.
 * Core tabs — Build, Model, Market & Policy, Settings, Analytics, History,
 * Plugins — are the modelling loop itself and are not listed; they can never
 * be switched off. This is NOT the plugin manager: plugins are third-party
 * extensions with their own tab; modules are built-in Ragnarok tabs.
 */
import React from 'react';
import { TAB_MODULES, parseEnabledModules, serializeEnabledModules } from '../../modules/registry';
import type { TabModuleId } from '../../modules/types';

export interface ModulesSectionProps {
  /** The csv persisted in AppSettings.enabledModules. */
  enabledModules: string;
  onEnabledModulesChange: (csv: string) => void;
}

export function ModulesSection({ enabledModules, onEnabledModulesChange }: ModulesSectionProps) {
  const enabled = parseEnabledModules(enabledModules);

  const toggle = (id: TabModuleId) => {
    const next = new Set(enabled);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    onEnabledModulesChange(serializeEnabledModules(next));
  };

  return (
    <section className="constraints-workspace-section">
      <header className="constraints-workspace-section-header">
        <h3>Modules</h3>
        <p>
          Compose this workspace: each module is a built-in Ragnarok tab that can be
          switched off when a project doesn&apos;t need it. The core tabs — Build, Model,
          Market &amp; Policy, Settings, Analytics, History, Plugins — are the modelling
          loop itself and are always on. Turning a module off only hides its tab; nothing
          is uninstalled, and the model, settings and results are untouched.
          (Third-party <b>plugins</b> are a different thing — manage those on the Plugins tab.)
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
    </section>
  );
}
