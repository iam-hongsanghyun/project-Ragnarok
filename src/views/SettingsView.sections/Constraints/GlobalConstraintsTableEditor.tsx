/**
 * Tabular editor for PyPSA native `global_constraints` rows.
 */
import React from 'react';
import { GridRow, Primitive } from '../../../shared/types';
import { stringValue } from '../../../shared/utils/helpers';

const NATIVE_TYPES = [
  'primary_energy',
  'transmission_volume_expansion_limit',
  'transmission_expansion_cost_limit',
  'operational_limit',
  'tech_capacity_expansion_limit',
] as const;

const NATIVE_SENSES = ['<=', '==', '>='] as const;

interface Props {
  rows: GridRow[];
  carriers: string[];
  onAdd: () => void;
  onDelete: (rowIndex: number) => void;
  onSet: (rowIndex: number, key: string, value: Primitive) => void;
}

export function GlobalConstraintsTableEditor({ rows, carriers, onAdd, onDelete, onSet }: Props) {
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
