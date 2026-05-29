import React, { useState } from 'react';
import { ModelIssue } from './useModelIssues';

interface ValidationResult {
  valid: boolean;
  errors: string[];
  warnings: string[];
  notes: string[];
  snapshotCount: number;
  networkSummary: Record<string, number>;
}

interface Props {
  validateResult: ValidationResult | null;
  issues: ModelIssue[];
  onValidate: () => void;
  onRun: () => void;
  onNavigate: (sheet: string, rowIndex: number) => void;
}

// ── Issue list ────────────────────────────────────────────────────────────────

function IssueItem({ issue, onNavigate }: { issue: ModelIssue; onNavigate: (sheet: string, rowIndex: number) => void }) {
  return (
    <li className={`vi-item vi-item--${issue.severity}`}>
      <span className="vi-icon">{issue.severity === 'error' ? 'error' : 'warn'}</span>
      <span className="vi-body">
        <button
          className="vi-loc"
          onClick={() => onNavigate(issue.sheet, issue.rowIndex)}
          title={`Go to ${issue.sheet}, row ${issue.rowIndex + 1}`}
        >
          {issue.sheet} · row {issue.rowIndex + 1}{issue.col ? ` · ${issue.col}` : ''}
        </button>
        <span className="vi-msg">{issue.message}</span>
      </span>
    </li>
  );
}

// ── Main pane ─────────────────────────────────────────────────────────────────

export function ValidationPane({ validateResult, issues, onValidate, onRun, onNavigate }: Props) {
  const [showAll, setShowAll] = useState(false);

  const errors = issues.filter((i) => i.severity === 'error');
  const warnings = issues.filter((i) => i.severity === 'warning');
  const totalIssues = issues.length;

  const visibleIssues = showAll ? issues : issues.slice(0, 20);

  const inputOk = errors.length === 0;

  return (
    <div className="pane validation-pane">

      {/* ── Frontend input checks ──────────────────────────────────────── */}
      <div className="validation-report">
        <div className="validation-report-header">
          <div>
            <p className="eyebrow">Input checks</p>
            <h2 className={inputOk ? 'text-ok' : 'text-error'}>
              {inputOk
                ? warnings.length > 0 ? `${warnings.length} warning${warnings.length > 1 ? 's' : ''}` : 'All clear'
                : `${errors.length} error${errors.length > 1 ? 's' : ''}${warnings.length > 0 ? `, ${warnings.length} warning${warnings.length > 1 ? 's' : ''}` : ''}`}
            </h2>
          </div>
          <div style={{ display: 'flex', gap: 8, alignSelf: 'flex-start', marginTop: 4 }}>
            <button className="tb-btn" onClick={onValidate}>Dry-run validate</button>
            {inputOk && (
              <button className="run-button" onClick={onRun}>Run model</button>
            )}
          </div>
        </div>

        {totalIssues === 0 ? (
          <p className="status-text" style={{ marginTop: 4 }}>
            No issues found in the model inputs. Click <strong>Dry-run validate</strong> to check with the solver.
          </p>
        ) : (
          <>
            <p className="status-text" style={{ marginTop: 4, marginBottom: 8 }}>
              Click a location link to jump to the affected sheet and row.
            </p>
            <ul className="vi-list">
              {visibleIssues.map((issue, idx) => (
                <IssueItem key={idx} issue={issue} onNavigate={onNavigate} />
              ))}
            </ul>
            {issues.length > 20 && (
              <button
                className="ghost-button sm"
                style={{ marginTop: 6 }}
                onClick={() => setShowAll((v) => !v)}
              >
                {showAll ? 'Show fewer' : `Show all ${issues.length} issues`}
              </button>
            )}
          </>
        )}
      </div>

      {/* ── Backend dry-run result ─────────────────────────────────────── */}
      {validateResult ? (
        <div className="validation-report">
          <div className="validation-report-header">
            <div>
              <p className="eyebrow">Solver validation</p>
              <h2 className={validateResult.valid ? 'text-ok' : 'text-error'}>
                {validateResult.valid ? 'Passed' : 'Failed'}
              </h2>
            </div>
            <button className="tb-btn" style={{ alignSelf: 'flex-start', marginTop: 4 }} onClick={onValidate}>
              Re-run
            </button>
          </div>

          {validateResult.errors.length > 0 && (
            <div className="validation-section validation-section--error">
              <p className="validation-section-title">Errors ({validateResult.errors.length})</p>
              <ul className="validation-list">
                {validateResult.errors.map((e, i) => <li key={i}>{e}</li>)}
              </ul>
            </div>
          )}

          {validateResult.warnings.length > 0 && (
            <div className="validation-section validation-section--warn">
              <p className="validation-section-title">Warnings ({validateResult.warnings.length})</p>
              <ul className="validation-list">
                {validateResult.warnings.map((w, i) => <li key={i}>{w}</li>)}
              </ul>
            </div>
          )}

          {Object.keys(validateResult.networkSummary).length > 0 && (
            <div className="validation-section">
              <p className="validation-section-title">Network summary</p>
              <div className="validation-summary-grid">
                {Object.entries(validateResult.networkSummary).map(([k, v]) => (
                  <div key={k} className="metric-card">
                    <span>{k}</span>
                    <strong>{v}</strong>
                  </div>
                ))}
              </div>
            </div>
          )}

          {validateResult.notes.length > 0 && (
            <div className="validation-section">
              <p className="validation-section-title">Build notes</p>
              <ul className="validation-list validation-list--notes">
                {validateResult.notes.map((n, i) => <li key={i}>{n}</li>)}
              </ul>
            </div>
          )}
        </div>
      ) : (
        <div className="validation-section" style={{ marginTop: 0 }}>
          <p className="status-text">
            No solver validation yet. Click <strong>Dry-run validate</strong> above to check the model structure with the backend.
          </p>
        </div>
      )}
    </div>
  );
}
