/**
 * Tabular editor for PyPSA native `global_constraints` rows.
 *
 * Schema-driven and fully user-definable: the column set comes straight from
 * the PyPSA `global_constraints` schema (no hardcoded type/attribute lists),
 * and every field is free-form with inline `<datalist>` suggestions sourced
 * from the model. PyPSA accepts arbitrary `type` / `carrier_attribute` values
 * and silently ignores ones it doesn't recognise, so we suggest rather than
 * restrict. Only `sense` is a strict dropdown (PyPSA allows exactly <=, ==, >=).
 */
import React from 'react';
import { GridRow, Primitive } from '../../../shared/types';
import { stringValue } from '../../../shared/utils/helpers';
import { getOrderedInputAttributes } from '../../../constants/pypsa_schema';
import { SearchableSelect } from '../../../shared/components/SearchableSelect';

// PyPSA's five recognised constraint types — offered as suggestions only.
const TYPE_SUGGESTIONS = [
  'primary_energy',
  'operational_limit',
  'tech_capacity_expansion_limit',
  'transmission_volume_expansion_limit',
  'transmission_expansion_cost_limit',
];

const NATIVE_SENSES = ['<=', '==', '>='] as const;

interface Props {
  rows: GridRow[];
  /** Carrier names from the carriers sheet (model.carriers[].name). */
  carriers: string[];
  /** Numeric column names on the carriers sheet (e.g. co2_emissions). */
  carrierAttributes: string[];
  /** Bus names from the buses sheet (model.buses[].name). */
  busNames: string[];
  /** Configured investment periods (pathway periods); empty in single-period mode. */
  investmentPeriods: number[];
  onAdd: () => void;
  onDelete: (rowIndex: number) => void;
  onSet: (rowIndex: number, key: string, value: Primitive) => void;
}

export function GlobalConstraintsTableEditor({
  rows,
  carriers,
  carrierAttributes,
  busNames,
  investmentPeriods,
  onAdd,
  onDelete,
  onSet,
}: Props) {
  // Columns come from the schema, so any attribute PyPSA adds shows up here
  // automatically. `name` is rendered first as the required key column.
  const attrs = getOrderedInputAttributes('global_constraints');

  if (rows.length === 0) {
    return (
      <div className="constraints-empty">
        <p>No global constraints yet. Add one below to cap primary energy, transmission expansion, or other PyPSA-native limits.</p>
        <button className="tb-btn" onClick={onAdd}>+ Add global constraint</button>
      </div>
    );
  }

  // carrier_attribute can be either a carriers-sheet column (primary_energy) or
  // a carrier name (the limit types) or comma-separated carriers (transmission),
  // so suggest the union and let the user type whatever they need.
  const carrierAttrSuggestions = Array.from(new Set([...carrierAttributes, ...carriers]));

  return (
    <div className="constraints-table-wrap">
      <datalist id="gc-type-options">
        {TYPE_SUGGESTIONS.map((t) => (<option key={t} value={t} />))}
      </datalist>
      <datalist id="gc-period-options">
        {investmentPeriods.map((p) => (<option key={p} value={p} />))}
      </datalist>

      <table className="constraints-table">
        <thead>
          <tr>
            {attrs.map((attr) => (
              <th key={attr.attribute} title={attr.description}>
                {attr.attribute}
              </th>
            ))}
            <th aria-label="actions" />
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i}>
              {attrs.map((attr) => (
                <td key={attr.attribute}>
                  {renderField(attr.attribute, row, i, onSet, carrierAttrSuggestions, busNames)}
                </td>
              ))}
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

function renderField(
  key: string,
  row: GridRow,
  i: number,
  onSet: (rowIndex: number, key: string, value: Primitive) => void,
  carrierAttrSuggestions: string[],
  busNames: string[],
): React.ReactNode {
  if (key === 'sense') {
    return (
      <select
        className="constraints-cell-input"
        value={stringValue(row.sense) || '<='}
        onChange={(e) => onSet(i, 'sense', e.target.value)}
      >
        {NATIVE_SENSES.map((s) => (<option key={s}>{s}</option>))}
      </select>
    );
  }

  if (key === 'constant') {
    return (
      <input
        type="number"
        className="constraints-cell-input constraints-cell-input--num"
        value={Number(row.constant ?? 0)}
        onChange={(e) => onSet(i, 'constant', parseFloat(e.target.value) || 0)}
      />
    );
  }

  if (key === 'investment_period') {
    const raw = row.investment_period;
    const value = raw === undefined || raw === null || raw === '' ? '' : String(raw);
    return (
      <input
        type="text"
        inputMode="numeric"
        list="gc-period-options"
        className="constraints-cell-input"
        value={value}
        placeholder="all"
        onChange={(e) => {
          const v = e.target.value.trim();
          onSet(i, 'investment_period', v === '' ? '' : (parseFloat(v) || 0));
        }}
      />
    );
  }

  // carrier_attribute and bus: searchable dropdowns sourced from the model.
  if (key === 'carrier_attribute' || key === 'bus') {
    return (
      <SearchableSelect
        className="constraints-cell-input"
        value={stringValue(row[key])}
        options={key === 'carrier_attribute' ? carrierAttrSuggestions : busNames}
        placeholder="—"
        onChange={(v) => onSet(i, key, v)}
      />
    );
  }

  // name (free text) and type (free text + datalist suggestions).
  return (
    <input
      className="constraints-cell-input"
      value={stringValue(row[key])}
      list={key === 'type' ? 'gc-type-options' : undefined}
      placeholder={key === 'name' ? 'name' : '—'}
      onChange={(e) => onSet(i, key, e.target.value)}
    />
  );
}
