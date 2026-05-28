/**
 * Read-only catalogue table with a filter input and "Add to model" buttons.
 */
import React, { useState } from 'react';
import { GridRow } from '../../../shared/types';
import { stringValue } from '../../../shared/utils/helpers';

interface Props {
  rows: GridRow[];
  cols: Array<{ key: string; label: string }>;
  alreadyInModel: Set<string>;
  onAdd: (row: GridRow) => void;
}

export function CatalogueTable({ rows, cols, alreadyInModel, onAdd }: Props) {
  const [filter, setFilter] = useState('');
  const filtered = filter.trim()
    ? rows.filter((row) => Object.values(row).some((v) => String(v ?? '').toLowerCase().includes(filter.toLowerCase())))
    : rows;
  return (
    <div className="constraints-table-wrap">
      <input
        type="text"
        className="constraints-cell-input"
        placeholder="Filter…"
        value={filter}
        onChange={(e) => setFilter(e.target.value)}
        style={{ maxWidth: 240, marginBottom: 6 }}
      />
      <table className="constraints-table">
        <thead>
          <tr>
            {cols.map((c) => <th key={c.key}>{c.label}</th>)}
            <th aria-label="actions" />
          </tr>
        </thead>
        <tbody>
          {filtered.map((row, i) => {
            const name = stringValue(row.name);
            const inModel = alreadyInModel.has(name);
            return (
              <tr key={i}>
                {cols.map((c) => (
                  <td key={c.key}>{stringValue(row[c.key]) || <span style={{ color: 'var(--muted)' }}>—</span>}</td>
                ))}
                <td>
                  <button className="tb-btn" disabled={inModel} onClick={() => onAdd(row)}>
                    {inModel ? 'In model' : 'Add'}
                  </button>
                </td>
              </tr>
            );
          })}
          {filtered.length === 0 && (
            <tr><td colSpan={cols.length + 1} style={{ color: 'var(--muted)', textAlign: 'center', padding: '12px 0' }}>No matches.</td></tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
