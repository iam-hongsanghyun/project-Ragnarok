/**
 * Tab-module registry — every first-party module tab, and the enablement
 * helpers the shell uses to compose a workspace.
 *
 * Modules are toggled from Settings → Modules; the chosen set persists in
 * `AppSettings.enabledModules` as a comma-separated id list (a plain string so
 * it survives the key/value RAGNAROK_Settings sheet of a project export, whose
 * cells are primitives). An absent value means "all modules" — the state of
 * the app before modules existed — so old settings and old project files keep
 * every tab.
 *
 * Module ≠ plugin: see `src/modules/types.ts`.
 */
import type { WorkspaceTab } from 'lib/types';
import type { TabModuleDefinition, TabModuleId } from './types';
import { dataModule } from './data/manifest';
import { forgeModule } from './forge/manifest';
import { physicalRiskModule } from './physical-risk/manifest';
import { sitingModule } from './siting/manifest';
import { postAnalysisModule } from './post-analysis/manifest';
import { trainingModule } from './training/manifest';

/** Every registered module, in activity-bar order. */
export const TAB_MODULES: readonly TabModuleDefinition[] = [
  dataModule,
  forgeModule,
  physicalRiskModule,
  sitingModule,
  postAnalysisModule,
  trainingModule,
].sort((a, b) => a.order - b.order);

const MODULE_ID_SET: ReadonlySet<string> = new Set(TAB_MODULES.map((m) => m.id));

/** True when a tab is owned by a module (and can therefore be disabled). */
export function isTabModule(tab: WorkspaceTab): tab is TabModuleId {
  return MODULE_ID_SET.has(tab);
}

/** The default setting value: every module enabled (pre-modules behaviour). */
export function defaultEnabledModulesCsv(): string {
  return TAB_MODULES.map((m) => m.id).join(',');
}

/**
 * Parse the persisted csv into the enabled-module set.
 *
 * `undefined`/`null` (setting predates modules) → all modules. An empty string
 * is a deliberate "none". Unknown ids — a renamed module, a file from a newer
 * version — are dropped rather than kept as dead entries.
 */
export function parseEnabledModules(
  csv: string | null | undefined,
): ReadonlySet<TabModuleId> {
  if (csv === null || csv === undefined) {
    return new Set(TAB_MODULES.map((m) => m.id));
  }
  const ids = csv
    .split(',')
    .map((s) => s.trim())
    .filter((s): s is TabModuleId => MODULE_ID_SET.has(s));
  return new Set(ids);
}

/** Serialise an enabled set back to the persisted csv (registry order). */
export function serializeEnabledModules(enabled: ReadonlySet<TabModuleId>): string {
  return TAB_MODULES.filter((m) => enabled.has(m.id)).map((m) => m.id).join(',');
}
