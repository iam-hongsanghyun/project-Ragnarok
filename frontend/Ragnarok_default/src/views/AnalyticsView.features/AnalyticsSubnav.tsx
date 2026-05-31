/**
 * Sub-tab nav for the Analytics view: Validation · Result · Analytics ·
 * Comparison · Log. Shows error/warning counts as a badge on Validation.
 * The Log tab streams backend command-line output (uvicorn / application /
 * tracebacks) via polling.
 */
import React from 'react';
import { AnalyticsSubTab } from 'lib/types';
import { ModelIssue } from '../../features/validation/useModelIssues';

interface ValidationResult {
  valid: boolean;
  errors: string[];
  warnings: string[];
}

interface Props {
  subTab: AnalyticsSubTab;
  onChange: (s: AnalyticsSubTab) => void;
  validateResult: ValidationResult | null;
  modelIssues: ModelIssue[];
}

const SUB_TABS: AnalyticsSubTab[] = ['Validation', 'Result', 'Analytics', 'Comparison', 'Log'];

export function AnalyticsSubnav({ subTab, onChange, validateResult, modelIssues }: Props) {
  const errorCount = modelIssues.filter((i) => i.severity === 'error').length;

  return (
    <nav className="subnav">
      {SUB_TABS.map((s) => (
        <button
          key={s}
          className={`subnav-btn${subTab === s ? ' subnav-btn--active' : ''}${
            s === 'Validation' && validateResult && !validateResult.valid ? ' subnav-btn--error' : ''}${
            s === 'Validation' && validateResult?.valid ? ' subnav-btn--ok' : ''}`}
          onClick={() => onChange(s)}
        >
          {s}
          {s === 'Validation' && errorCount > 0 && (
            <span className="tab-badge tab-badge--error">{errorCount}</span>
          )}
          {s === 'Validation' && errorCount === 0 && validateResult && (
            <span className={`tab-badge ${validateResult.valid ? 'tab-badge--ok' : 'tab-badge--error'}`}>
              {validateResult.valid ? 'ok' : validateResult.errors.length + validateResult.warnings.length}
            </span>
          )}
        </button>
      ))}
    </nav>
  );
}
