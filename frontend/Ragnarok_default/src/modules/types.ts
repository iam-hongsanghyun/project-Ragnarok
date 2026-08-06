/**
 * Tab-module contract — the shape every first-party module tab declares.
 *
 * A MODULE is a built-in Ragnarok tab that is not required for the core
 * modelling loop (edit workbook → run → read results) and can therefore be
 * switched off per workspace from Settings → Modules. A module is NOT a
 * plugin: plugins (`features/plugins/`, the Plugins tab) are third-party
 * extensions loaded at runtime; modules are first-party code compiled into
 * the app and merely toggled. Keep the two vocabularies disjoint.
 *
 * Core tabs — Welcome, Build, Model, Market & Policy, Settings, Analytics,
 * History (with the queue) and Plugins — are never modules and cannot be
 * disabled.
 */
import type React from 'react';
import type { WorkspaceTab } from 'lib/types';

/** The tabs that are modules. A subset of WorkspaceTab by construction. */
export type TabModuleId =
  | 'Data'
  | 'Forge'
  | 'PhysicalRisk'
  | 'Siting'
  | 'PostAnalysis'
  | 'Reporting'
  | 'Training';

export interface TabModuleDefinition {
  /** The WorkspaceTab this module owns — one module, one tab. */
  id: TabModuleId & WorkspaceTab;
  /** Activity-bar tooltip name, e.g. "Physical Risk". */
  label: string;
  /** One-line tooltip hint under the label. */
  hint: string;
  /** A sentence for the Settings → Modules manager: what turning it on buys. */
  description: string;
  /** Activity-bar glyph (use `lineIcon` so it matches the core icons). */
  icon: React.ReactNode;
  /**
   * Position on the activity bar. Core entries sit at fixed positions
   * (Build 10, Model 20, Market 40, Settings 50, Analytics 60, History 100,
   * Plugins 110); modules interleave by this value so enabling/disabling one
   * never reshuffles the rest.
   */
  order: number;
}
