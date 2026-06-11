/**
 * Free-text custom-constraint code box (safe DSL) + a read-only list of the
 * constraints actually applied in the last run (custom table, DSL, and plugin
 * contributions), so plugin-added constraints are no longer invisible.
 */
import React, { useMemo } from 'react';
import { AppliedConstraint } from 'lib/types';
import { parseConstraintDsl } from 'lib/constraints/dsl';

export interface CustomDslSectionProps {
  customDsl: string;
  onCustomDslChange: (text: string) => void;
  appliedConstraints?: AppliedConstraint[];
}

const SOURCE_LABEL: Record<AppliedConstraint['source'], string> = {
  custom: 'table',
  dsl: 'DSL',
  plugin: 'plugin',
};

export function CustomDslSection({ customDsl, onCustomDslChange, appliedConstraints }: CustomDslSectionProps) {
  const applied = appliedConstraints ?? [];
  // Live per-line validation: lines with syntax errors are NOT applied at run
  // time, so they must be visible here at author time (and the run path warns
  // again). Cheap — the DSL box is a handful of lines.
  const dslErrors = useMemo(
    () => parseConstraintDsl(customDsl).filter((line) => line.error),
    [customDsl],
  );
  return (
    <section className="constraints-workspace-section">
      <header className="constraints-workspace-section-header">
        <h3>Custom constraints (advanced)</h3>
        <p>One linear constraint per line, applied to the solver. Use this for limits the tables above can't express. <code>#</code> starts a comment. Constraint code is saved with the model workbook, not with scenario presets.</p>
      </header>

      <details className="constraints-help">
        <summary>DSL cheatsheet</summary>
        <ul className="constraints-help-list">
          <li><code>gen(carrier)</code> — energy of a carrier (MWh); bare <code>gen</code> = all supply</li>
          <li><code>cap(carrier)</code> — capacity (MW); bare <code>cap</code> = all supply</li>
          <li><code>emissions(carrier)</code> — CO₂ (tCO₂); bare <code>emissions</code> = total</li>
          <li><code>load_shed</code> — unserved energy (MWh)</li>
          <li><code>cf(carrier) &lt;= 0.8</code> — capacity factor (fraction 0–1)</li>
          <li>Combine with <code>+ - *</code> and a constant, e.g. <code>gen(solar) + gen(wind) &gt;= 5000</code></li>
          <li>Intensity cap: <code>emissions &lt;= 0.5 * gen</code> (tCO₂/MWh)</li>
        </ul>
      </details>

      <textarea
        className="constraints-dsl-input"
        spellCheck={false}
        rows={6}
        value={customDsl}
        placeholder={'# examples\ngen(coal) <= 200000\ncf(nuclear) <= 0.85\nemissions <= 0.4 * gen'}
        onChange={(e) => onCustomDslChange(e.target.value)}
      />

      {dslErrors.length > 0 && (
        <ul className="constraints-dsl-errors" role="alert">
          {dslErrors.map((line) => (
            <li key={line.lineNo} className="constraints-dsl-error">
              line {line.lineNo}: {line.error} — <code>{line.raw}</code> (not applied)
            </li>
          ))}
        </ul>
      )}

      <div className="sg-setting-row">
        <label className="sg-setting-label">Applied constraints (last run)</label>
        {applied.length === 0 ? (
          <div className="constraints-cell-placeholder">No custom, DSL, or plugin constraints in the last run.</div>
        ) : (
          <ul className="constraints-applied-list">
            {applied.map((c) => (
              <li key={c.name} className="constraints-applied-item">
                <span className={`constraints-applied-badge constraints-applied-badge--${c.source}`}>{SOURCE_LABEL[c.source]}</span>
                <code className="constraints-applied-name">{c.name}</code>
                {typeof c.shadowPrice === 'number' && Math.abs(c.shadowPrice) > 1e-9 && (
                  <span className="constraints-applied-dual">λ {c.shadowPrice.toLocaleString(undefined, { maximumFractionDigits: 2 })}</span>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
