/**
 * ConstraintsWorkspaceView — full-width editor that hosts both:
 *
 *  - **Custom**: the existing UI-authored linopy constraints
 *    (CO₂ cap, carrier gen/share/CF bounds, load shedding cap). These are
 *    applied at solve time by `backend/lib/network/custom_constraints.py`.
 *
 *  - **Global constraints**: rows in the PyPSA-native `global_constraints`
 *    sheet (`primary_energy`, `transmission_volume_expansion_limit`,
 *    `tech_capacity_expansion_limit`, …). These flow through the generic
 *    schema-driven import path; no backend code change required.
 *
 * Opened from the sidebar's `Constraints →` shortcut. ESC or the close
 * button dismisses the overlay and returns to the previously active tab.
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { CustomConstraint, GridRow, Primitive, WorkbookModel } from '../../shared/types';
import { GlobalConstraintsSection } from './GlobalConstraintsSection';
import { stringValue } from '../../shared/utils/helpers';

const NATIVE_TYPES = [
  'primary_energy',
  'transmission_volume_expansion_limit',
  'transmission_expansion_cost_limit',
  'operational_limit',
  'tech_capacity_expansion_limit',
] as const;

const NATIVE_SENSES = ['<=', '==', '>='] as const;

type Tab = 'custom' | 'global_constraints';

interface Props {
  model: WorkbookModel;
  carriers: string[];
  constraints: CustomConstraint[];
  onConstraintsChange: (next: CustomConstraint[]) => void;
  onUpdateRow: (sheet: 'global_constraints', rowIndex: number, key: string, value: Primitive) => void;
  onAddRow: (sheet: 'global_constraints') => void;
  onDeleteRow: (sheet: 'global_constraints', rowIndex: number) => void;
  onClose: () => void;
}

export function ConstraintsWorkspaceView({
  model,
  carriers,
  constraints,
  onConstraintsChange,
  onUpdateRow,
  onAddRow,
  onDeleteRow,
  onClose,
}: Props) {
  const [tab, setTab] = useState<Tab>('custom');

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const customCount = constraints.filter((c) => c.enabled).length;
  const globalRows = useMemo(() => (model.global_constraints ?? []) as GridRow[], [model.global_constraints]);
  const globalCount = globalRows.length;

  const setCell = useCallback(
    (rowIndex: number, key: string, value: Primitive) => onUpdateRow('global_constraints', rowIndex, key, value),
    [onUpdateRow],
  );

  return (
    <div className="constraints-workspace">
      <div className="constraints-workspace-header">
        <div className="constraints-workspace-title">
          <h2>Constraints</h2>
          <p>Author custom solver constraints or edit native PyPSA <code>global_constraints</code> rows.</p>
        </div>
        <button className="tb-btn tb-btn--muted" onClick={onClose} title="Close (Esc)">Close</button>
      </div>

      <nav className="subnav constraints-workspace-tabs">
        <button
          className={`subnav-btn${tab === 'custom' ? ' subnav-btn--active' : ''}`}
          onClick={() => setTab('custom')}
        >
          Custom
          <span className="tab-badge tab-badge--ok">{customCount}</span>
        </button>
        <button
          className={`subnav-btn${tab === 'global_constraints' ? ' subnav-btn--active' : ''}`}
          onClick={() => setTab('global_constraints')}
        >
          Global constraints
          <span className="tab-badge tab-badge--ok">{globalCount}</span>
        </button>
      </nav>

      <div className="constraints-workspace-body">
        {tab === 'custom' && (
          <section className="constraints-workspace-section">
            <header className="constraints-workspace-section-header">
              <h3>Custom solver constraints</h3>
              <p>
                Applied as <code>linopy</code> constraints during the solve by
                Ragnarok's <code>extra_functionality</code> hook. Preset rows are
                always present; custom rows append to the list and persist in
                project workbooks.
              </p>
            </header>
            <GlobalConstraintsSection
              constraints={constraints}
              carriers={carriers}
              onChange={onConstraintsChange}
            />
          </section>
        )}

        {tab === 'global_constraints' && (
          <section className="constraints-workspace-section">
            <header className="constraints-workspace-section-header">
              <h3>PyPSA <code>global_constraints</code> sheet</h3>
              <p>
                Native PyPSA constraints — go through the generic import path
                and persist as rows in the <code>global_constraints</code>
                workbook sheet. Set <code>type</code> to the constraint kind,
                <code>sense</code> to the comparison, and <code>constant</code>
                to the right-hand side value.
              </p>
            </header>
            <GlobalConstraintsTableEditor
              rows={globalRows}
              carriers={carriers}
              onAdd={() => onAddRow('global_constraints')}
              onDelete={(rowIndex) => onDeleteRow('global_constraints', rowIndex)}
              onSet={setCell}
            />
          </section>
        )}
      </div>
    </div>
  );
}

export function GlobalConstraintsTableEditor({
  rows,
  carriers,
  onAdd,
  onDelete,
  onSet,
}: {
  rows: GridRow[];
  carriers: string[];
  onAdd: () => void;
  onDelete: (rowIndex: number) => void;
  onSet: (rowIndex: number, key: string, value: Primitive) => void;
}) {
  if (rows.length === 0) {
    return (
      <div className="constraints-empty">
        <p>No global constraints yet. Add one below to cap primary energy, transmission expansion, or other PyPSA-native limits.</p>
        <button className="tb-btn" onClick={onAdd}>+ Add global constraint</button>
      </div>
    );
  }
  return (
    <div className="constraints-table-wrap">
      <table className="constraints-table">
        <thead>
          <tr>
            <th>Name</th>
            <th>Type</th>
            <th>Sense</th>
            <th>Constant</th>
            <th>Carrier attribute</th>
            <th>Investment period</th>
            <th>Bus</th>
            <th aria-label="actions" />
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i}>
              <td>
                <input
                  className="constraints-cell-input"
                  value={stringValue(row.name)}
                  onChange={(e) => onSet(i, 'name', e.target.value)}
                  placeholder="name"
                />
              </td>
              <td>
                <select
                  className="constraints-cell-input"
                  value={stringValue(row.type) || 'primary_energy'}
                  onChange={(e) => onSet(i, 'type', e.target.value)}
                >
                  {NATIVE_TYPES.map((t) => (<option key={t}>{t}</option>))}
                </select>
              </td>
              <td>
                <select
                  className="constraints-cell-input"
                  value={stringValue(row.sense) || '<='}
                  onChange={(e) => onSet(i, 'sense', e.target.value)}
                >
                  {NATIVE_SENSES.map((s) => (<option key={s}>{s}</option>))}
                </select>
              </td>
              <td>
                <input
                  type="number"
                  className="constraints-cell-input constraints-cell-input--num"
                  value={Number(row.constant ?? 0)}
                  onChange={(e) => onSet(i, 'constant', parseFloat(e.target.value) || 0)}
                />
              </td>
              <td>
                <input
                  className="constraints-cell-input"
                  value={stringValue(row.carrier_attribute) || 'co2_emissions'}
                  list={`gc-carriers-${i}`}
                  onChange={(e) => onSet(i, 'carrier_attribute', e.target.value)}
                />
                <datalist id={`gc-carriers-${i}`}>
                  {carriers.map((c) => (<option key={c} value={c} />))}
                </datalist>
              </td>
              <td>
                <input
                  type="number"
                  className="constraints-cell-input constraints-cell-input--num"
                  value={row.investment_period === undefined || row.investment_period === null || row.investment_period === '' ? '' : Number(row.investment_period)}
                  onChange={(e) => onSet(i, 'investment_period', e.target.value === '' ? '' : (parseFloat(e.target.value) || 0))}
                  placeholder="—"
                />
              </td>
              <td>
                <input
                  className="constraints-cell-input"
                  value={stringValue(row.bus)}
                  onChange={(e) => onSet(i, 'bus', e.target.value)}
                  placeholder="—"
                />
              </td>
              <td>
                <button className="gcc-del" onClick={() => onDelete(i)} title="Delete row">x</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <button className="tb-btn" style={{ marginTop: 12 }} onClick={onAdd}>+ Add global constraint</button>
    </div>
  );
}
