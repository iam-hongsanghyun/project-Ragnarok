/**
 * Activity bar — vertical, far-left strip with the view switches.
 *
 * Each button shows a line icon that hints at the view, plus the full view
 * name as a tooltip that appears on hover (to the right of the icon). This is
 * the only entry point into a view; there are no tabs anywhere else.
 */
import React from 'react';
import { WorkspaceTab } from 'lib/types';

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
}

interface Entry {
  id: WorkspaceTab;
  label: string;
  hint: string;
  icon: React.ReactNode;
}

// Shared SVG frame: 20×20, stroke = currentColor so it inherits the button's
// active/hover colour. Kept deliberately simple to read at ~18 px.
const svg = (children: React.ReactNode) => (
  <svg
    viewBox="0 0 20 20"
    width="18"
    height="18"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.6"
    strokeLinecap="round"
    strokeLinejoin="round"
    aria-hidden="true"
  >
    {children}
  </svg>
);

const ICONS: Record<WorkspaceTab, React.ReactNode> = {
  // Data — a database cylinder (external data import).
  Data: svg(<>
    <ellipse cx="10" cy="5" rx="6" ry="2.4" />
    <path d="M4 5v10c0 1.3 2.7 2.4 6 2.4s6-1.1 6-2.4V5" />
    <path d="M4 10c0 1.3 2.7 2.4 6 2.4s6-1.1 6-2.4" />
  </>),
  // Build — a box with a plus (assemble a model from scratch).
  Build: svg(<>
    <rect x="3.5" y="3.5" width="13" height="13" rx="1.5" />
    <path d="M10 7v6M7 10h6" />
  </>),
  // Model — a cell grid (the component spreadsheet).
  Model: svg(<>
    <rect x="3.5" y="3.5" width="13" height="13" rx="1.5" />
    <path d="M3.5 8.5h13M3.5 13h13M8.5 3.5v13" />
  </>),
  // Forge — sliders (bulk shaping / transforms of the data).
  Forge: svg(<>
    <path d="M4 6h7M15 6h1M4 14h1M9 14h7" />
    <circle cx="13" cy="6" r="1.8" />
    <circle cx="7" cy="14" r="1.8" />
  </>),
  // Market & Policy — an institution (columns + roof): policy that shapes the solve.
  Market: svg(<>
    <path d="M3.5 7.5 10 3.5l6.5 4" />
    <path d="M5 8v6M8 8v6M12 8v6M15 8v6" />
    <path d="M3.5 16.5h13" />
  </>),
  // Settings — a gear.
  Settings: svg(<>
    <circle cx="10" cy="10" r="2.4" />
    <path d="M10 3v2.2M10 14.8V17M3 10h2.2M14.8 10H17M5 5l1.6 1.6M13.4 13.4 15 15M15 5l-1.6 1.6M6.6 13.4 5 15" />
  </>),
  // Analytics — a bar chart (the results dashboard).
  Analytics: svg(<>
    <path d="M4 16V4" />
    <path d="M4 16h12" />
    <rect x="6.5" y="10" width="2.4" height="4" />
    <rect x="10.3" y="7" width="2.4" height="7" />
    <rect x="14.1" y="11.5" width="2.4" height="2.5" />
  </>),
  // Physical Risk — a hazard triangle (climate exposure / physical risk).
  PhysicalRisk: svg(<>
    <path d="M10 3.5 17 16H3Z" />
    <path d="M10 8v4" />
    <circle cx="10" cy="14.2" r="0.6" fill="currentColor" stroke="none" />
  </>),
  // Post-analysis — a lightbulb (decisions drawn from the results).
  PostAnalysis: svg(<>
    <path d="M10 3a5 5 0 0 0-3 9v2h6v-2a5 5 0 0 0-3-9Z" />
    <path d="M8 17h4M8.5 14.5h3" />
  </>),
  // History — a clock with a rewind arrow.
  History: svg(<>
    <path d="M3.5 10a6.5 6.5 0 1 1 2 4.6" />
    <path d="M3.5 14v-3.2h3.2" />
    <path d="M10 6.5V10l2.5 1.6" />
  </>),
  // Plugins — a puzzle piece.
  Plugins: svg(<>
    <path d="M8 4h4v2.2a1.4 1.4 0 1 0 2.8 0V4H16v4h-1.8a1.4 1.4 0 1 0 0 2.8H16v5h-4v-1.8a1.4 1.4 0 1 0-2.8 0V16H5v-5h1.8a1.4 1.4 0 1 0 0-2.8H5V4h3Z" />
  </>),
  Welcome: null,
};

const ENTRIES: Entry[] = [
  { id: 'Data',         label: 'Data',            hint: 'Import external data', icon: ICONS.Data },
  { id: 'Build',        label: 'Build',           hint: 'Assemble a model', icon: ICONS.Build },
  { id: 'Model',        label: 'Model',           hint: 'Edit components', icon: ICONS.Model },
  { id: 'Forge',        label: 'Forge',           hint: 'Shape & transform data', icon: ICONS.Forge },
  { id: 'Market',       label: 'Market & Policy', hint: 'Inputs that change the solve', icon: ICONS.Market },
  { id: 'Settings',     label: 'Settings',        hint: 'Run setup & preferences', icon: ICONS.Settings },
  { id: 'Analytics',    label: 'Analytics',       hint: 'Results dashboard', icon: ICONS.Analytics },
  { id: 'PhysicalRisk', label: 'Physical Risk',   hint: 'Climate exposure & physical risk', icon: ICONS.PhysicalRisk },
  { id: 'PostAnalysis', label: 'Post-analysis',   hint: 'Decisions from results (no re-solve)', icon: ICONS.PostAnalysis },
  { id: 'History',      label: 'History',         hint: 'Past runs', icon: ICONS.History },
  { id: 'Plugins',      label: 'Plugins',         hint: 'Extensions', icon: ICONS.Plugins },
];

export function ActivityBar({ tab, onTabChange, validateResult, pluginCount }: Props) {
  return (
    <nav className="activity-bar" aria-label="Views">
      {ENTRIES.map((e) => {
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
