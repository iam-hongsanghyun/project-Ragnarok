/**
 * Activity bar — vertical, far-left strip with the view switches.
 *
 * Each button shows a line icon that hints at the view, plus the full view
 * name as a tooltip that appears on hover (to the right of the icon). This is
 * the only entry point into a view; there are no tabs anywhere else.
 *
 * CORE tabs (Build, Model, Market & Policy, Settings, Analytics, History,
 * Plugins) are declared here and always present. MODULE tabs come from the
 * tab-module registry (`src/modules/registry`) and render only when enabled in
 * Settings → Modules — `enabledModules` decides. The two interleave by each
 * entry's `order`, so toggling a module never reshuffles its neighbours.
 */
import React from 'react';
import { WorkspaceTab } from 'lib/types';
import { TAB_MODULES } from '../modules/registry';
import type { TabModuleId } from '../modules/types';
import { lineIcon } from 'shared/components/lineIcon';

interface ValidationResult {
  valid: boolean;
  errors: string[];
  warnings: string[];
}

interface Props {
  tab: WorkspaceTab;
  onTabChange: (t: WorkspaceTab) => void;
  validateResult: ValidationResult | null;
  pluginCount: number;
  /** Module tabs to show (Settings → Modules). Core tabs ignore this. */
  enabledModules: ReadonlySet<TabModuleId>;
}

interface Entry {
  id: WorkspaceTab;
  label: string;
  hint: string;
  icon: React.ReactNode;
  order: number;
}

// The always-present core entries. Module entries (Data, Forge, Physical Risk,
// Siting, Post-analysis, Training) live in their manifests under src/modules/.
const CORE_ENTRIES: Entry[] = [
  {
    id: 'Build', label: 'Build', hint: 'Assemble a model', order: 10,
    // A box with a plus (assemble a model from scratch).
    icon: lineIcon(<>
      <rect x="3.5" y="3.5" width="13" height="13" rx="1.5" />
      <path d="M10 7v6M7 10h6" />
    </>),
  },
  {
    id: 'Model', label: 'Model', hint: 'Edit components', order: 20,
    // A cell grid (the component spreadsheet).
    icon: lineIcon(<>
      <rect x="3.5" y="3.5" width="13" height="13" rx="1.5" />
      <path d="M3.5 8.5h13M3.5 13h13M8.5 3.5v13" />
    </>),
  },
  {
    id: 'Market', label: 'Market & Policy', hint: 'Inputs that change the solve', order: 40,
    // An institution (columns + roof): policy that shapes the solve.
    icon: lineIcon(<>
      <path d="M3.5 7.5 10 3.5l6.5 4" />
      <path d="M5 8v6M8 8v6M12 8v6M15 8v6" />
      <path d="M3.5 16.5h13" />
    </>),
  },
  {
    id: 'Settings', label: 'Settings', hint: 'Run setup & preferences', order: 50,
    // A gear.
    icon: lineIcon(<>
      <circle cx="10" cy="10" r="2.4" />
      <path d="M10 3v2.2M10 14.8V17M3 10h2.2M14.8 10H17M5 5l1.6 1.6M13.4 13.4 15 15M15 5l-1.6 1.6M6.6 13.4 5 15" />
    </>),
  },
  {
    id: 'Analytics', label: 'Analytics', hint: 'Results dashboard', order: 60,
    // A bar chart (the results dashboard).
    icon: lineIcon(<>
      <path d="M4 16V4" />
      <path d="M4 16h12" />
      <rect x="6.5" y="10" width="2.4" height="4" />
      <rect x="10.3" y="7" width="2.4" height="7" />
      <rect x="14.1" y="11.5" width="2.4" height="2.5" />
    </>),
  },
  {
    id: 'History', label: 'History', hint: 'Past runs', order: 100,
    // A clock with a rewind arrow.
    icon: lineIcon(<>
      <path d="M3.5 10a6.5 6.5 0 1 1 2 4.6" />
      <path d="M3.5 14v-3.2h3.2" />
      <path d="M10 6.5V10l2.5 1.6" />
    </>),
  },
  {
    id: 'Plugins', label: 'Plugins', hint: 'Extensions', order: 110,
    // A puzzle piece.
    icon: lineIcon(<>
      <path d="M8 4h4v2.2a1.4 1.4 0 1 0 2.8 0V4H16v4h-1.8a1.4 1.4 0 1 0 0 2.8H16v5h-4v-1.8a1.4 1.4 0 1 0-2.8 0V16H5v-5h1.8a1.4 1.4 0 1 0 0-2.8H5V4h3Z" />
    </>),
  },
];

export function ActivityBar({ tab, onTabChange, validateResult, pluginCount, enabledModules }: Props) {
  const entries: Entry[] = [
    ...CORE_ENTRIES,
    ...TAB_MODULES.filter((m) => enabledModules.has(m.id)).map((m) => ({
      id: m.id, label: m.label, hint: m.hint, icon: m.icon, order: m.order,
    })),
  ].sort((a, b) => a.order - b.order);

  return (
    <nav className="activity-bar" aria-label="Views">
      {entries.map((e) => {
        const showAnalyticsBadge = e.id === 'Analytics' && validateResult;
        const showPluginsBadge = e.id === 'Plugins' && pluginCount > 0;
        return (
          <button
            key={e.id}
            className={`activity-bar-btn${tab === e.id ? ' is-active' : ''}`}
            onClick={() => onTabChange(e.id)}
            aria-label={e.label}
            aria-current={tab === e.id ? 'page' : undefined}
          >
            <span className="activity-bar-glyph">{e.icon}</span>
            <span className="activity-bar-tip" role="tooltip">
              <span className="activity-bar-tip-name">{e.label}</span>
              <span className="activity-bar-tip-hint">{e.hint}</span>
            </span>
            {showAnalyticsBadge && validateResult && (
              <span className={`activity-bar-badge ${validateResult.valid ? 'is-ok' : 'is-error'}`}>
                {validateResult.valid ? '✓' : (validateResult.errors.length + validateResult.warnings.length)}
              </span>
            )}
            {showPluginsBadge && (
              <span className="activity-bar-badge is-ok">{pluginCount}</span>
            )}
          </button>
        );
      })}
    </nav>
  );
}
