/**
 * Activity bar — vertical, far-left strip with the view switches.
 *
 * Each button shows a single-letter glyph (D / B / M / F / S / A / P) plus
 * the full view name as a tooltip. This is the only entry point into a
 * view; there are no tabs anywhere else.
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
  glyph: string;
  label: string;
}

const ENTRIES: Entry[] = [
  { id: 'Data',      glyph: 'D', label: 'Data' },
  { id: 'Build',     glyph: 'B', label: 'Build' },
  { id: 'Model',     glyph: 'M', label: 'Model' },
  { id: 'Forge',     glyph: 'F', label: 'Forge' },
  { id: 'Settings',  glyph: 'S', label: 'Settings' },
  { id: 'Analytics', glyph: 'A', label: 'Analytics' },
  { id: 'Plugins',   glyph: 'P', label: 'Plugins' },
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
            title={e.label}
            aria-label={e.label}
            aria-current={tab === e.id ? 'page' : undefined}
          >
            <span className="activity-bar-glyph">{e.glyph}</span>
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
