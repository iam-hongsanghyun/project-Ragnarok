/**
 * One plant-type picker for the Build Generators step.
 *
 * Pick a type (Generator, BESS, CCGT, OCGT, gas + H2 co-firing in two modes, P2X chain), a bus and a capacity (fixed MW or
 * "let the solver size it") plus the type's few key fields; everything else is defaulted from the technology data files and sits
 * behind "Advanced". The backend builds every component (`/api/build/plant`) and previews what it will create; applying hands
 * the change set to `onApply`, which removes / merges it as ONE edit. With `editing` set the same form re-derives that plant.
 */
import React, { useEffect, useMemo, useState } from 'react';
import type { WorkbookModel } from 'lib/types';
import type { PlantCard, PlantChange } from 'lib/build/plants';
import {
  fetchPlantTypes,
  previewPlant,
  previewPlantEdit,
  type PlantField,
  type PlantPreview,
  type PlantType,
} from 'lib/api/plants';
import './plants.css';

interface Props {
  model: WorkbookModel;
  busNames: string[];
  carrierNames: string[];
  onApply: (change: PlantChange, label: string) => void | Promise<void>;
  /** Plant to re-derive; the type is then fixed and the button saves changes. */
  editing?: PlantCard | null;
  onDoneEditing?: () => void;
  /** Settings -> Discount rate: written on every cost row (PyPSA's `discount_rate`) unless the plant sets its own. */
  discountRate?: number;
}

type Values = Record<string, unknown>;

/** Spec sent to the backend: blank -> omitted (the backend default applies), numbers parsed, JSON parsed. */
export function specFromValues(fields: PlantField[], values: Values): { spec: Values; error: string | null } {
  const spec: Values = {};
  for (const f of fields) {
    const raw = values[f.key];
    if (f.kind === 'bool') { spec[f.key] = Boolean(raw); continue; }
    if (raw === undefined || raw === null || raw === '') continue;
    if (f.kind === 'number') {
      const n = Number(raw);
      if (!Number.isFinite(n)) return { spec, error: `${f.label} must be a number.` };
      spec[f.key] = n;
    } else if (f.kind === 'json') {
      if (typeof raw === 'string') {
        if (raw.trim() === '' || raw.trim() === '{}') continue;
        try { spec[f.key] = JSON.parse(raw); } catch { return { spec, error: `${f.label} is not valid JSON.` }; }
      } else if (typeof raw === 'object' && Object.keys(raw as object).length > 0) {
        spec[f.key] = raw;
      }
    } else {
      spec[f.key] = raw;
    }
  }
  return { spec, error: null };
}

function startValues(type: PlantType, editing?: PlantCard | null, discountRate?: number): Values {
  const out: Values = {};
  for (const f of type.fields) {
    const stored = editing?.spec?.[f.key];
    const v = stored !== undefined ? stored : (f.key === 'discountRate' && discountRate !== undefined ? discountRate : f.default);
    out[f.key] = f.kind === 'json' ? (v && Object.keys(v as object).length ? JSON.stringify(v) : '') : (v ?? '');
  }
  return out;
}

export function PlantPicker({ model, busNames, carrierNames, onApply, editing, onDoneEditing, discountRate }: Props) {
  const [types, setTypes] = useState<PlantType[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [typeId, setTypeId] = useState('');
  const [values, setValues] = useState<Values>({});
  const [preview, setPreview] = useState<PlantPreview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let live = true;
    fetchPlantTypes()
      .then((t) => { if (live) setTypes(t); })
      .catch((e: unknown) => { if (live) setLoadError(e instanceof Error ? e.message : 'could not load plant types'); });
    return () => { live = false; };
  }, []);

  const type = useMemo(() => types.find((t) => t.id === (editing?.type ?? typeId)) ?? (editing ? undefined : types[0]), [types, typeId, editing]);

  // (Re)start the form when the type or the edited plant changes.
  useEffect(() => {
    if (!type) return;
    setValues(startValues(type, editing, discountRate));
    setPreview(null);
    setError(null);
  }, [type, editing, discountRate]);

  const { spec, error: formError } = useMemo(() => (type ? specFromValues(type.fields, values) : { spec: {}, error: null }), [type, values]);
  const specKey = JSON.stringify(spec);

  // Live preview from the backend (also validates the bus, the name and the numbers).
  useEffect(() => {
    if (!type || formError) { setPreview(null); setError(formError); return undefined; }
    let live = true;
    const timer = window.setTimeout(() => {
      const call = editing ? previewPlantEdit(editing.plantId, spec, model) : previewPlant(type.id, spec, model);
      call
        .then((p) => { if (live) { setPreview(p); setError(null); } })
        .catch((e: unknown) => { if (live) { setPreview(null); setError(e instanceof Error ? e.message : 'could not preview'); } });
    }, 250);
    return () => { live = false; window.clearTimeout(timer); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [type, specKey, formError, editing, model]);

  if (!type) {
    return (
      <div className="plant-picker">
        <h4 className="plant-picker__title">Add a plant</h4>
        <p className="plant-picker__hint">{loadError ?? (editing ? 'This plant type is not available.' : 'Loading plant types...')}</p>
      </div>
    );
  }

  const set = (key: string, v: unknown) => setValues((prev) => ({ ...prev, [key]: v }));
  const extendable = Boolean(values.extendable);

  const renderField = (f: PlantField) => {
    const id = `plant-${f.key}`;
    const disabled = f.key === 'pNom' && extendable;
    const label = `${f.label}${f.unit ? ` (${f.unit})` : ''}`;
    if (f.kind === 'bool') {
      return (
        <label key={f.key} className="plant-picker__field plant-picker__field--check" title={f.help}>
          <input type="checkbox" checked={Boolean(values[f.key])} onChange={(e) => set(f.key, e.target.checked)} />
          <span>{f.label}</span>
        </label>
      );
    }
    let control: React.ReactNode;
    if (f.kind === 'select') {
      control = <select id={id} className="ss-input" value={String(values[f.key] ?? '')} onChange={(e) => set(f.key, e.target.value)}>{(f.options ?? []).map((o) => <option key={o} value={o}>{o}</option>)}</select>;
    } else if (f.kind === 'bus') {
      control = (
        <select id={id} className="ss-input" value={String(values[f.key] ?? '')} onChange={(e) => set(f.key, e.target.value)}>
          <option value="">{f.key === 'bus' ? '(first electricity bus)' : '(none / create)'}</option>
          {busNames.map((b) => <option key={b} value={b}>{b}</option>)}
        </select>
      );
    } else if (f.kind === 'carrier') {
      control = <><input id={id} className="ss-input" list={`${id}-list`} value={String(values[f.key] ?? '')} onChange={(e) => set(f.key, e.target.value)} /><datalist id={`${id}-list`}>{carrierNames.map((c) => <option key={c} value={c} />)}</datalist></>;
    } else if (f.kind === 'json') {
      control = <textarea id={id} className="ss-input" value={String(values[f.key] ?? '')} placeholder="{}" onChange={(e) => set(f.key, e.target.value)} />;
    } else if (f.kind === 'number') {
      control = <input id={id} className="ss-input" type="number" min={f.min} step="any" disabled={disabled} value={String(values[f.key] ?? '')} onChange={(e) => set(f.key, e.target.value)} />;
    } else {
      control = <input id={id} className="ss-input" value={String(values[f.key] ?? '')} disabled={editing !== undefined && editing !== null && f.key === 'plantId'} placeholder={f.key === 'plantId' ? type.id : undefined} onChange={(e) => set(f.key, e.target.value)} />;
    }
    return (
      <label key={f.key} className="plant-picker__field" htmlFor={id} title={f.help}>
        <span>{label}</span>
        {control}
      </label>
    );
  };

  const basic = type.fields.filter((f) => !f.advanced);
  const advanced = type.fields.filter((f) => f.advanced);
  const counts = preview ? Object.entries(preview.rowCounts).filter(([s]) => !s.startsWith('RAGNAROK')).map(([s, n]) => `${n} ${s}`).join(', ') : '';

  const apply = async () => {
    if (!preview || busy) return;
    setBusy(true);
    try {
      await onApply(preview.change, `${editing ? 'Updated' : 'Added'} ${preview.label}`);
      if (editing) onDoneEditing?.();
      else setValues(startValues(type, null, discountRate));
    } catch (e) {
      setError(e instanceof Error ? e.message : 'could not apply');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="plant-picker" data-testid="plant-picker">
      <h4 className="plant-picker__title">{editing ? `Edit plant ${editing.plantId}` : 'Add a plant'}</h4>
      {!editing && (
        <label className="plant-picker__field" htmlFor="plant-type">
          <span>Plant type</span>
          <select id="plant-type" className="ss-input" value={type.id} onChange={(e) => setTypeId(e.target.value)}>
            {types.map((t) => <option key={t.id} value={t.id}>{t.label}</option>)}
          </select>
        </label>
      )}
      <p className="plant-picker__hint">{type.description}</p>
      <div className="plant-picker__grid">{basic.map(renderField)}</div>
      {advanced.length > 0 && (
        <details className="plant-picker__adv">
          <summary>Advanced{type.technology ? ` (defaults: ${type.technology})` : ''}</summary>
          <div className="plant-picker__grid">{advanced.map(renderField)}</div>
        </details>
      )}
      {preview && <p className="plant-picker__preview">{editing ? 'Re-creates' : 'Creates'}: {counts}.</p>}
      {preview?.warnings.map((w) => <p key={w} className="plant-picker__warn">{w}</p>)}
      {error && <p className="plant-picker__error">{error}</p>}
      <div className="plant-picker__actions">
        <button className="run-button" type="button" onClick={apply} disabled={!preview || busy}>
          {editing ? 'Save changes' : `Add ${type.label.split(' (')[0]}`}
        </button>
        {editing && <button className="ghost-button sm" type="button" onClick={onDoneEditing}>Cancel</button>}
      </div>
    </div>
  );
}
