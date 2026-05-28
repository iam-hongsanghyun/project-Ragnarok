/**
 * Plugins view — module manager (left rail) + plugin host (main).
 *
 * Parallel to Model / Settings / Analytics — not part of the serialized
 * Model → Settings → Analytics flow.
 */
import React from 'react';
import { ModuleConfigField, ModuleDescriptor, ModuleHostInventory, RunResults, WorkbookModel } from '../shared/types';
import { ModuleManagerSection } from '../features/modules/ModuleManagerSection';
import { PluginPanel } from '../features/plugins/PluginPanel';

interface Props {
  model: WorkbookModel;
  displayResults: RunResults | null;
  moduleInventory: ModuleHostInventory | null;
  moduleHostLoading: boolean;
  moduleHostError: string | null;
  enabledModuleIds: string[];
  isModuleEnabled: (moduleId: string) => boolean;
  isModuleEnableEligible: (module: ModuleDescriptor) => boolean;
  onToggleModuleEnabled: (moduleId: string, enabled: boolean) => void;
  onInstallModule: (file: File) => void;
  onUninstallModule: (module: ModuleDescriptor) => void;
  enabledModules: ModuleDescriptor[];
  moduleConfigs: Record<string, Record<string, unknown>>;
  onModuleConfigChange: (moduleId: string, key: string, value: unknown) => void;
  onModuleAction: (moduleId: string, fieldKey: string, field: ModuleConfigField) => Promise<void>;
}

export function PluginsView(props: Props) {
  const carriers = Array.from(
    new Set(props.model.carriers.map((c) => String(c.name ?? '')).filter(Boolean)),
  );

  return (
    <div className="view plugins-view">
      <aside className="view-rail view-rail--left">
        <div className="view-rail-header">Modules</div>
        <ModuleManagerSection
          inventory={props.moduleInventory}
          loading={props.moduleHostLoading}
          error={props.moduleHostError}
          enabledIds={props.enabledModuleIds}
          isEnabled={props.isModuleEnabled}
          isEnableEligible={props.isModuleEnableEligible}
          onToggleEnabled={props.onToggleModuleEnabled}
          onInstall={props.onInstallModule}
          onUninstall={props.onUninstallModule}
        />
      </aside>
      <main className="view-main">
        {props.enabledModules.length === 0 ? (
          <div className="view-empty">
            <h3>No modules enabled</h3>
            <p>Install or enable a module in the rail on the left.</p>
          </div>
        ) : (
          <PluginPanel
            modules={props.enabledModules}
            moduleConfigs={props.moduleConfigs}
            onModuleConfigChange={props.onModuleConfigChange as unknown as (moduleId: string, key: string, value: unknown) => void}
            carriers={carriers}
            pluginAnalytics={props.displayResults?.pluginAnalytics ?? {}}
            onModuleAction={props.onModuleAction}
          />
        )}
      </main>
    </div>
  );
}
