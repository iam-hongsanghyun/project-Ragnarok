/**
 * Build-mode attribute form.
 *
 * An editable, vertical form for the single row selected on the map or in the
 * table. Fields come from the component schema (required first, then optional)
 * with units and inline descriptions; edits write straight into the model via
 * `onUpdate`. `bus`/`carrier` fields offer a dropdown of defined names.
 *
 * This is the Plexos-style "selected item" editor — focused on one component
 * instead of the whole sheet (the sheet stays editable in the table below).
 */
import React from 'react';
import { GridRow, Primitive } from '../../shared/types';
import { getComponentSchema, PypsaAttribute } from '../../constants/pypsa_schema';
import { stringValue } from '../../shared/utils/helpers';

const isStaticInputAttr = (attr: PypsaAttribute): boolean =>
  attr.status === 'input' && attr.storage !== 'series';

/** Coerce a raw input string to the attribute's declared type. */
function coerce(attr: PypsaAttribute, raw: string): Primitive {
  if (raw === '') return '';
  const t = attr.type.toLowerCase();
  if (t.includes('bool')) return raw === 'true';
  if (t.includes('float') || t.includes('int') || t.includes('number')) {
    const n = Number(raw);
    return Number.isFinite(n) ? n : raw;
  }
  return raw;
}

interface Props {
  sheet: string;
  row: GridRow | null;
  rowIndex: number | null;
  rowCount: number;
  busNames: string[];
  carrierNames: string[];
  onUpdate: (rowIndex: number, col: string, val: Primitive) => void;
  onAddRow: () => void;
  onDeleteRow: (rowIndex: number) => void;
  /** When provided (geo steps), bus fields gain a "pick on map" button that
   *  starts click-to-link for that field. */
  onPickOnMap?: (rowIndex: number, field: string) => void;
}

export function BuildAttributeForm({
  sheet, row, rowIndex, rowCount, busNames, carrierNames, onUpdate, onAddRow, onDeleteRow, onPickOnMap,
}: Props) {
  const component = getComponentSchema(sheet);

  if (!component) {
    return (
      <aside className="build-form">
        <div className="build-form-empty">No editable attributes for this step.</div>
      </aside>
    );
  }

  const attrs = component.attributes.filter(isStaticInputAttr);
  const required = attrs.filter((a) => a.required);
  const optional = attrs.filter((a) => !a.required);

  if (row == null || rowIndex == null) {
    return (
      <aside className="build-form">
        <div className="build-form-head">
          <p className="eyebrow">{component.label} · select an item</p>
          <h3>No selection</h3>
        </div>
        <p className="build-form-empty">
          Click an item on the map or a row in the table to edit it
          {rowCount === 0 ? ', or add the first one.' : '.'}
        </p>
        <button className="primary-button sm" onClick={onAddRow} type="button">+ Add {component.label}</button>
      </aside>
    );
  }

  const renderField = (attr: PypsaAttribute) => {
    const value = row[attr.attribute];
    const strValue = value === undefined || value === null ? '' : String(value);
    const t = attr.type.toLowerCase();
    const isBus = attr.attribute === 'bus' || attr.attribute === 'bus0' || attr.attribute === 'bus1';
    const isCarrier = attr.attribute === 'carrier';

    let field: React.ReactNode;
    if (isBus) {
      field = (
        <div className="build-field-bus">
          <select value={strValue} onChange={(e) => onUpdate(rowIndex, attr.attribute, e.target.value)}>
            <option value="">—</option>
            {busNames.map((b) => <option key={b} value={b}>{b}</option>)}
          </select>
          {onPickOnMap && (
            <button
              type="button"
              className="ghost-button sm build-field-pick"
              title="Click a bus on the map"
              onClick={() => onPickOnMap(rowIndex, attr.attribute)}
            >
              Pick on map
            </button>
          )}
        </div>
      );
    } else if (isCarrier) {
      field = (
        <input
          type="text"
          list="build-carrier-options"
          value={strValue}
          onChange={(e) => onUpdate(rowIndex, attr.attribute, e.target.value)}
        />
      );
    } else if (t.includes('bool')) {
      field = (
        <select value={strValue} onChange={(e) => onUpdate(rowIndex, attr.attribute, e.target.value === 'true')}>
          <option value="true">true</option>
          <option value="false">false</option>
        </select>
      );
    } else if (t.includes('float') || t.includes('int') || t.includes('number')) {
      field = (
        <input
          type="number"
          value={strValue}
          placeholder={attr.default}
          onChange={(e) => onUpdate(rowIndex, attr.attribute, coerce(attr, e.target.value))}
        />
      );
    } else {
      field = (
        <input
          type="text"
          value={strValue}
          placeholder={attr.default}
          onChange={(e) => onUpdate(rowIndex, attr.attribute, e.target.value)}
        />
      );
    }

    return (
      <label className="build-field" key={attr.attribute} title={attr.description}>
        <span className="build-field-label">
          {attr.attribute}
          {attr.unit && attr.unit !== 'n/a' && <span className="build-field-unit">{attr.unit}</span>}
        </span>
        {field}
      </label>
    );
  };

  return (
    <aside className="build-form">
      <datalist id="build-carrier-options">
        {carrierNames.map((c) => <option key={c} value={c} />)}
      </datalist>

      <div className="build-form-head">
        <p className="eyebrow">{component.label} · row {rowIndex + 1}</p>
        <h3>{stringValue(row.name) || `row ${rowIndex + 1}`}</h3>
      </div>

      <section className="build-form-section">
        <h4>Required</h4>
        <div className="build-fields">{required.map(renderField)}</div>
      </section>

      {optional.length > 0 && (
        <section className="build-form-section">
          <h4>Optional</h4>
          <div className="build-fields">{optional.map(renderField)}</div>
        </section>
      )}

      <div className="build-form-actions">
        <button className="ghost-button sm" onClick={onAddRow} type="button">+ Add</button>
        <button className="ghost-button sm build-form-delete" onClick={() => onDeleteRow(rowIndex)} type="button">Delete</button>
      </div>
    </aside>
  );
}
