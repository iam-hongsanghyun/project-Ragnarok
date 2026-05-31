/**
 * Right-hand pane for the Build wizard.
 *
 * Shows schema metadata for the step's primary sheet: attribute names,
 * units, requiredness, type, and the documentation string from
 * `pypsa_schema.json`. If a single row is highlighted the pane also shows
 * the current values for that row beside each attribute.
 */
import React from 'react';
import { GridRow, WorkbookModel } from 'lib/types';
import { getComponentSchema, PypsaAttribute, TABLE_GROUPS } from 'lib/constants/pypsa_schema';
import { stringValue } from 'lib/utils/helpers';
import { BuildStep, getStepIssues } from 'lib/build/steps';
import { ModelIssue } from '../validation/useModelIssues';

/** Down-sample to at most `maxPts` points so wide profiles stay legible. */
function downsample(values: number[], maxPts = 120): number[] {
  if (values.length <= maxPts) return values;
  const step = (values.length - 1) / (maxPts - 1);
  return Array.from({ length: maxPts }, (_, i) => values[Math.round(i * step)]);
}

function MiniSparkline({ values, color = '#0f766e' }: { values: number[]; color?: string }) {
  const pts = downsample(values);
  if (pts.length < 2) return null;
  const W = 228, H = 48;
  const min = Math.min(...pts);
  const max = Math.max(...pts);
  const range = max - min || 1;
  const px = (i: number) => (i / (pts.length - 1)) * W;
  const py = (v: number) => H - 4 - ((v - min) / range) * (H - 8);
  const linePts = pts.map((v, i) => `${px(i)},${py(v)}`).join(' ');
  const areaPath =
    `M${px(0)},${H} ` + pts.map((v, i) => `L${px(i)},${py(v)}`).join(' ') + ` L${px(pts.length - 1)},${H} Z`;
  return (
    <svg width="100%" height={H} viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" style={{ display: 'block' }}>
      <path d={areaPath} fill={color} fillOpacity={0.1} />
      <polyline points={linePts} fill="none" stroke={color} strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}

/** Pull each time-series profile (e.g. p_max_pu) for the focused asset out of
 *  the `<sheet>-<attr>` temporal sheets, where columns are asset names. */
function focusedRowSeries(
  model: WorkbookModel,
  primarySheet: string,
  assetName: string,
): Array<{ attribute: string; values: number[] }> {
  if (!assetName) return [];
  const group = TABLE_GROUPS.find((g) => g.sheet === primarySheet);
  if (!group) return [];
  const out: Array<{ attribute: string; values: number[] }> = [];
  for (const ts of group.temporalSheets) {
    const tsRows: GridRow[] = (model as Record<string, GridRow[]>)[ts.sheet] ?? [];
    if (tsRows.length === 0) continue;
    if (!(assetName in tsRows[0])) continue;
    const values = tsRows
      .map((r) => Number(r[assetName]))
      .filter((v) => Number.isFinite(v));
    if (values.length >= 2) out.push({ attribute: ts.attribute, values });
  }
  return out;
}

interface Props {
  step: BuildStep;
  model: WorkbookModel;
  issues: ModelIssue[];
  focusedRowIndex: number | null;
}

const isStaticInputAttr = (attr: PypsaAttribute): boolean =>
  attr.status === 'input' && attr.storage !== 'series';

export function BuildDetailPane({ step, model, issues, focusedRowIndex }: Props) {
  const component = getComponentSchema(step.primarySheet);
  const rows: GridRow[] = model[step.primarySheet] ?? [];
  const focusedRow = focusedRowIndex != null ? rows[focusedRowIndex] : null;
  const stepIssues = getStepIssues(step, issues);

  if (!component) {
    return (
      <aside className="build-detail-pane">
        <div className="build-detail-empty">No schema for this step.</div>
      </aside>
    );
  }

  const attrs = component.attributes.filter(isStaticInputAttr);
  const required = attrs.filter((a) => a.required);
  const optional = attrs.filter((a) => !a.required);
  const series = focusedRow ? focusedRowSeries(model, step.primarySheet, stringValue(focusedRow.name)) : [];

  return (
    <aside className="build-detail-pane">
      <div className="build-detail-header">
        <p className="eyebrow">
          {focusedRow ? `${component.sheet_name} · row` : `${component.sheet_name} · schema`}
        </p>
        <h3>
          {focusedRow ? stringValue(focusedRow.name) || `row ${(focusedRowIndex ?? 0) + 1}` : component.label}
        </h3>
      </div>

      {stepIssues.length > 0 && (
        <div className="build-detail-issues">
          <p className="build-detail-issues-title">
            {stepIssues.filter((i) => i.severity === 'error').length} error
            {stepIssues.filter((i) => i.severity === 'error').length === 1 ? '' : 's'},{' '}
            {stepIssues.filter((i) => i.severity === 'warning').length} warning
            {stepIssues.filter((i) => i.severity === 'warning').length === 1 ? '' : 's'}
          </p>
          <ul>
            {stepIssues.slice(0, 6).map((iss, idx) => (
              <li key={idx} className={`build-issue build-issue--${iss.severity}`}>
                <span className="build-issue-badge">{iss.severity === 'error' ? '!' : '?'}</span>
                <span>
                  row {iss.rowIndex + 1}
                  {iss.col ? ` · ${iss.col}` : ''} — {iss.message}
                </span>
              </li>
            ))}
            {stepIssues.length > 6 && (
              <li className="build-issue build-issue--more">+ {stepIssues.length - 6} more</li>
            )}
          </ul>
        </div>
      )}

      {series.length > 0 && (
        <section className="build-detail-section build-detail-series">
          <h4>Profiles</h4>
          {series.map((s) => (
            <div className="build-spark" key={s.attribute}>
              <div className="build-spark-head">
                <span className="build-spark-attr">{s.attribute}</span>
                <span className="build-spark-meta">{s.values.length} steps</span>
              </div>
              <MiniSparkline values={s.values} />
            </div>
          ))}
        </section>
      )}

      {required.length > 0 && (
        <AttributeTable
          title="Required"
          attrs={required}
          focusedRow={focusedRow}
        />
      )}
      {optional.length > 0 && (
        <AttributeTable
          title="Optional"
          attrs={optional}
          focusedRow={focusedRow}
        />
      )}

      <div className="build-detail-footnote">
        <span>{rows.length} row{rows.length === 1 ? '' : 's'}</span>
        <span>· {attrs.length} attribute{attrs.length === 1 ? '' : 's'}</span>
      </div>
    </aside>
  );
}

interface AttributeTableProps {
  title: string;
  attrs: PypsaAttribute[];
  focusedRow: GridRow | null;
}

function AttributeTable({ title, attrs, focusedRow }: AttributeTableProps) {
  return (
    <section className="build-detail-section">
      <h4>{title}</h4>
      <dl className="build-detail-attrs">
        {attrs.map((attr) => {
          const current = focusedRow ? focusedRow[attr.attribute] : undefined;
          const display = current === undefined || current === null || current === ''
            ? null
            : stringValue(current);
          return (
            <div className="build-detail-attr" key={attr.attribute}>
              <dt>
                <span className="build-attr-name">{attr.attribute}</span>
                {attr.unit && attr.unit !== 'n/a' && (
                  <span className="build-attr-unit">{attr.unit}</span>
                )}
                <span className={`build-attr-type build-attr-type--${attr.type}`}>{attr.type}</span>
              </dt>
              <dd>
                {focusedRow ? (
                  <span className="build-attr-value">{display ?? <em>—</em>}</span>
                ) : (
                  <span className="build-attr-desc">{attr.description}</span>
                )}
              </dd>
            </div>
          );
        })}
      </dl>
    </section>
  );
}
