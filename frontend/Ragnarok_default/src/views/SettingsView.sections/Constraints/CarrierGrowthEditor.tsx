/**
 * Carrier growth limits (P27): one row per carrier with `max_growth` (MW of NEW
 * capacity per investment period) and `max_relative_growth` (ratio of the
 * previous period's installed capacity). Both are plain columns of the carriers
 * sheet, so edits go through the same row-update path as the grid; an empty cell
 * means unlimited. The limits only bind on multi-period (pathway) runs, which the
 * hint column says per row (same rule as the server's `validate_model`).
 */
import React from 'react';
import { GridRow, Primitive } from 'lib/types';
import { growthLimitHint } from 'lib/constraints/globalConstraintHints';

const ATTRS = [
  { key: 'max_growth', label: 'max_growth (MW per period)', placeholder: 'unlimited' },
  { key: 'max_relative_growth', label: 'max_relative_growth (ratio)', placeholder: 'unlimited' },
] as const;

interface Props {
  carriers: GridRow[];
  pathwayEnabled: boolean;
  onSet: (rowIndex: number, key: string, value: Primitive) => void;
}

const asText = (v: unknown): string =>
  v === undefined || v === null || (typeof v === 'number' && !Number.isFinite(v)) ? '' : String(v);

export function CarrierGrowthEditor({ carriers, pathwayEnabled, onSet }: Props) {
  if (carriers.length === 0) {
    return <p className="sg-setting-hint">No carriers in this model.</p>;
  }
  return (
    <div className="constraints-table-wrap">
      <table className="constraints-table">
        <thead>
          <tr>
            <th>carrier</th>
            {ATTRS.map((a) => <th key={a.key}>{a.label}</th>)}
            <th>note</th>
          </tr>
        </thead>
        <tbody>
          {carriers.map((row, i) => {
            const hints = ATTRS.map((a) => growthLimitHint(a.key, row[a.key], pathwayEnabled)).filter(Boolean);
            return (
              <tr key={`${String(row.name)}-${i}`} data-carrier={String(row.name ?? '')}>
                <td>{String(row.name ?? '')}</td>
                {ATTRS.map((a) => (
                  <td key={a.key}>
                    <input
                      type="text"
                      inputMode="decimal"
                      className="constraints-cell-input constraints-cell-input--num"
                      aria-label={`${String(row.name)} ${a.key}`}
                      placeholder={a.placeholder}
                      defaultValue={asText(row[a.key])}
                      key={asText(row[a.key])}
                      onBlur={(e) => {
                        const raw = e.target.value.trim();
                        if (raw === asText(row[a.key])) return;
                        if (raw === '') return onSet(i, a.key, '');
                        const n = Number(raw);
                        if (Number.isFinite(n)) onSet(i, a.key, n);
                        else e.target.value = asText(row[a.key]);
                      }}
                    />
                  </td>
                ))}
                <td className="sg-setting-hint">{hints.map((h) => h!.message).join(' ') || '—'}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
