/**
 * RawSheetsCard (H2′) — sheets an imported workbook carried that the canonical
 * layout didn't recognise, kept verbatim and shown as plain tables so nothing
 * a third-party export contained is silently dropped.
 */
import React from 'react';

interface Props {
  data: Record<string, Record<string, unknown>[]>;
}

const MAX_ROWS = 50;

export function RawSheetsCard({ data }: Props) {
  const names = Object.keys(data);
  if (names.length === 0) return null;
  return (
    <div className="econ-card">
      {names.map((name) => {
        const rows = data[name] ?? [];
        const cols = rows.length ? Object.keys(rows[0]) : [];
        return (
          <div key={name} className="econ-table-wrap" style={{ marginBottom: 12 }}>
            <p className="econ-footnote" style={{ marginBottom: 4 }}>
              <b>{name}</b> — {rows.length.toLocaleString()} row{rows.length === 1 ? '' : 's'} (unrecognised sheet, kept verbatim)
            </p>
            <table className="econ-table">
              <thead><tr>{cols.map((c) => <th key={c}>{c}</th>)}</tr></thead>
              <tbody>
                {rows.slice(0, MAX_ROWS).map((r, i) => (
                  <tr key={i}>{cols.map((c) => <td key={c}>{String(r[c] ?? '')}</td>)}</tr>
                ))}
              </tbody>
            </table>
            {rows.length > MAX_ROWS && (
              <p className="econ-footnote">Showing the first {MAX_ROWS} of {rows.length.toLocaleString()} rows.</p>
            )}
          </div>
        );
      })}
    </div>
  );
}
