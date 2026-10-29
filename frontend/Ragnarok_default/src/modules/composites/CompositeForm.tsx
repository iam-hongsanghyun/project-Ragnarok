/**
 * CompositeForm — add (or edit) one composite asset: connections first, then sizing and parameters, the technology data it reads,
 * a schematic of how it plugs into the network, and the rows it will create.
 *
 * Every field comes from the backend type catalogue (`GET /api/build/plant/types`); a field with a `port` is a connection and is
 * drawn in the Connections section from the model's own buses and generators. The backend builds every component
 * (`/api/build/plant`) and previews it; applying hands the change set to `onApply`, which removes / merges it as ONE edit.
 */
import React, { useEffect, useMemo, useState } from 'react';
import type { GridRow, WorkbookModel } from 'lib/types';
import { derivedLines, type PlantCard, type PlantChange } from 'lib/build/plants';
import { connectionsOf, fragmentComponentRows, isElectricCarrier, isGasCarrier, isH2Carrier, portPhrase } from 'lib/build/connections';
import { stringValue } from 'lib/utils/helpers';
import {
  fetchPlantTechnologies, fetchPlantTypes, previewPlant, previewPlantEdit,
  type PlantField, type PlantPreview, type PlantTechnologies, type PlantType,
} from 'lib/api/plants';
import { fetchTechnologies, type TechCatalogue, type TechEntry } from 'lib/api/p2x';
import { ConnectionSchematic } from './ConnectionSchematic';

interface Props {
  model: WorkbookModel;
  onApply: (change: PlantChange, label: string) => void | Promise<void>;
  /** Composite to re-derive; the type is then fixed and the button saves changes. */
  editing?: PlantCard | null;
  onDoneEditing?: () => void;
  /** Settings -> Discount rate: written on every cost row unless the composite sets its own. */
  discountRate?: number;
}

type Values = Record<string, unknown>;

/** Spec sent to the backend: blank -> omitted (the backend default applies), numbers parsed, JSON parsed, generator lists kept. */
export function specFromValues(fields: PlantField[], values: Values): { spec: Values; error: string | null } {
  const spec: Values = {};
  for (const f of fields) {
    const raw = values[f.key];
    if (f.kind === 'bool') { spec[f.key] = Boolean(raw); continue; }
    if (f.kind === 'generators') { if (Array.isArray(raw) && raw.length > 0) spec[f.key] = raw; continue; }
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
    if (f.kind === 'generators') out[f.key] = Array.isArray(v) ? v : [];
    else out[f.key] = f.kind === 'json' ? (v && Object.keys(v as object).length ? JSON.stringify(v) : '') : (v ?? '');
  }
  return out;
}

const fmt = (v: number): string => v.toLocaleString(undefined, { maximumFractionDigits: 4 });

function TechTable({ title, notes, params }: { title: string; notes?: string; params: TechEntry['parameters'] }) {
  return (
    <details className="cmp-tech" open>
      <summary>{title}</summary>
      <table className="cmp-table cmp-table--compact" aria-label={`${title} data`}>
        <thead><tr><th>Parameter</th><th className="num">Value</th><th>Unit</th><th>Source</th><th>Verified</th></tr></thead>
        <tbody>
          {Object.entries(params).map(([name, p]) => (
            <tr key={name}>
              <td>{name.replace(/_/g, ' ')}</td>
              <td className="num">{fmt(p.value)}</td>
              <td>{p.unit}</td>
              <td title={p.note}>{p.source.document.split(',')[0]} ({p.source.locator}, {p.source.year})</td>
              <td><span className={`cmp-chip cmp-chip--${p.verified}`}>{p.verified}</span></td>
            </tr>
          ))}
        </tbody>
      </table>
      {notes && <p className="cmp-note">{notes}</p>}
    </details>
  );
}

/** The technology data the preview read, with its source and verified flag, from the plant file and the P2X file. */
function TechnologyData({ keys }: { keys: { plants: string[]; p2x: string[] } }) {
  const [plants, setPlants] = useState<PlantTechnologies | null>(null);
  const [p2x, setP2x] = useState<TechCatalogue | null>(null);
  const needPlants = keys.plants.length > 0;
  const needP2x = keys.p2x.length > 0;
  useEffect(() => {
    let live = true;
    if (needPlants && !plants) fetchPlantTechnologies().then((t) => { if (live) setPlants(t); }).catch(() => undefined);
    if (needP2x && !p2x) fetchTechnologies().then((t) => { if (live) setP2x(t); }).catch(() => undefined);
    return () => { live = false; };
  }, [needPlants, needP2x, plants, p2x]);
  if (!needPlants && !needP2x) return null;
  return (
    <section className="cmp-section" data-testid="technology-data">
      <h4>Technology data used</h4>
      {plants && keys.plants.map((k) => (k === 'fuels'
        ? <TechTable key={k} title="Fuels" params={plants.fuels} />
        : plants.technologies[k] ? <TechTable key={k} title={plants.technologies[k].label} notes={plants.technologies[k].notes} params={plants.technologies[k].parameters} /> : null))}
      {p2x && keys.p2x.map((k) => (p2x.technologies[k] ? <TechTable key={k} title={p2x.technologies[k].label} notes={p2x.technologies[k].notes} params={p2x.technologies[k].parameters} /> : null))}
      {((needPlants && !plants) || (needP2x && !p2x)) && <p className="cmp-note">Loading the technology data...</p>}
      <p className="cmp-note">Values are the defaults of the data files; override one in Advanced (parameter overrides) or by editing the rows after applying.</p>
    </section>
  );
}

export function CompositeForm({ model, onApply, editing, onDoneEditing, discountRate }: Props) {
  const [types, setTypes] = useState<PlantType[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [typeId, setTypeId] = useState('');
  const [values, setValues] = useState<Values>({});
  const [preview, setPreview] = useState<PlantPreview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [showAllBuses, setShowAllBuses] = useState(false);
  const [showOtherGens, setShowOtherGens] = useState(false);

  useEffect(() => {
    let live = true;
    fetchPlantTypes()
      .then((t) => { if (live) setTypes(t); })
      .catch((e: unknown) => { if (live) setLoadError(e instanceof Error ? e.message : 'could not load composite types'); });
    return () => { live = false; };
  }, []);

  const type = useMemo(() => types.find((t) => t.id === (editing?.type ?? typeId)) ?? (editing ? undefined : types[0]), [types, typeId, editing]);
  const buses = useMemo(() => (model.buses ?? []) as GridRow[], [model.buses]);
  const generators = useMemo(() => (model.generators ?? []) as GridRow[], [model.generators]);

  useEffect(() => {
    if (!type) return;
    setValues(startValues(type, editing, discountRate));
    setPreview(null);
    setError(null);
  }, [type, editing, discountRate]);

  const { spec, error: formError } = useMemo(() => (type ? specFromValues(type.fields, values) : { spec: {}, error: null }), [type, values]);
  const specKey = JSON.stringify(spec);

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

  const connections = useMemo(
    () => (preview ? connectionsOf(fragmentComponentRows(preview.change.fragment), buses, Array.isArray(spec.designatedGenerators) ? (spec.designatedGenerators as string[]) : []) : null),
    [preview, buses, spec.designatedGenerators],
  );

  if (!type) {
    return <p className="cmp-note">{loadError ?? (editing && types.length > 0 ? `Composite type ${editing.type ?? '(unknown)'} is not available.` : 'Loading composite types...')}</p>;
  }

  const set = (key: string, v: unknown) => setValues((prev) => ({ ...prev, [key]: v }));
  const extendable = Boolean(values.extendable);
  const ports = type.fields.filter((f) => f.port);
  const params = type.fields.filter((f) => !f.port && !f.advanced);
  const advanced = type.fields.filter((f) => !f.port && f.advanced);

  // A port offers the buses whose carrier fits it (the chosen one always stays listed); "Show all buses" lifts the filter.
  const busesFor = (f: PlantField): GridRow[] => {
    if (showAllBuses) return buses;
    const fits = (carrier: string): boolean => {
      if (f.port === 'electricity') return isElectricCarrier(carrier);
      if (f.port === 'gas') return isGasCarrier(carrier);
      if (f.port === 'h2') return isH2Carrier(carrier);
      return !isElectricCarrier(carrier) && !isGasCarrier(carrier) && !isH2Carrier(carrier);     // a product bus (NH3, MeOH, e-fuel ...)
    };
    const chosen = String(values[f.key] ?? '');
    return buses.filter((b) => fits(stringValue(b.carrier)) || stringValue(b.name) === chosen);
  };
  // Zero-emission carriers (wind, solar, hydro ...) first: matching a chain to a fossil generator for RFNBO makes no sense.
  const zeroCarbon = new Set(((model.carriers ?? []) as GridRow[]).filter((c) => stringValue(c.co2_emissions) !== '' && Number(c.co2_emissions) === 0).map((c) => stringValue(c.name)));

  const renderPort = (f: PlantField) => {
    const id = `cmp-${f.key}`;
    if (f.kind === 'generators') {
      const chosen = (values[f.key] as string[]) ?? [];
      const toggle = (name: string) => set(f.key, chosen.includes(name) ? chosen.filter((g) => g !== name) : [...chosen, name]);
      const isRenewable = (g: GridRow) => zeroCarbon.has(stringValue(g.carrier));
      const renewable = generators.filter(isRenewable);
      const other = generators.filter((g) => !isRenewable(g));
      const item = (g: GridRow) => {
        const name = stringValue(g.name);
        return (
          <label key={name}><input type="checkbox" checked={chosen.includes(name)} onChange={() => toggle(name)} />
            {name} <span className="cmp-note">{stringValue(g.carrier)}{stringValue(g.bus) ? ` on ${stringValue(g.bus)}` : ''}</span></label>
        );
      };
      return (
        <div key={f.key} className="cmp-port" role="group" aria-label={f.label}>
          <span className="cmp-port__label">{f.label}</span>
          <div className="cmp-gens">
            {generators.length === 0 && <span className="cmp-note">The model has no generators.</span>}
            {renewable.length > 0 && <span className="cmp-note">Renewable (zero-emission carrier)</span>}
            {renewable.map(item)}
            {other.length > 0 && (
              <>
                <label className="cmp-note"><input type="checkbox" checked={showOtherGens || other.some((g) => chosen.includes(stringValue(g.name)))} onChange={(e) => setShowOtherGens(e.target.checked)} />
                  Show other generators ({other.length}: fossil or carrier without a zero emission factor)</label>
                {(showOtherGens || other.some((g) => chosen.includes(stringValue(g.name)))) && other.map(item)}
              </>
            )}
          </div>
          <span className="cmp-port__help">{f.help} Leave all unticked: {f.blank}.</span>
        </div>
      );
    }
    return (
      <label key={f.key} className="cmp-port" htmlFor={id}>
        <span className="cmp-port__label">{f.label}</span>
        <select id={id} className="ss-input" value={String(values[f.key] ?? '')} onChange={(e) => set(f.key, e.target.value)}>
          <option value="">{f.blank ? `(${f.blank})` : '(none)'}</option>
          {busesFor(f).map((b) => {
            const name = stringValue(b.name);
            return <option key={name} value={name}>{name}{stringValue(b.carrier) ? ` - ${stringValue(b.carrier)}` : ''}</option>;
          })}
        </select>
        <span className="cmp-port__help">{f.help}</span>
      </label>
    );
  };

  const renderField = (f: PlantField) => {
    const id = `cmp-${f.key}`;
    const label = `${f.label}${f.unit ? ` (${f.unit})` : ''}`;
    if (f.kind === 'bool') {
      return (
        <label key={f.key} className="cmp-field cmp-field--check" title={f.help}>
          <input type="checkbox" checked={Boolean(values[f.key])} onChange={(e) => set(f.key, e.target.checked)} />
          <span>{f.label}</span>
        </label>
      );
    }
    let control: React.ReactNode;
    if (f.kind === 'select') {
      control = <select id={id} className="ss-input" value={String(values[f.key] ?? '')} onChange={(e) => set(f.key, e.target.value)}>{(f.options ?? []).map((o) => <option key={o} value={o}>{o}</option>)}</select>;
    } else if (f.kind === 'carrier') {
      const names = ((model.carriers ?? []) as GridRow[]).map((c) => stringValue(c.name));
      control = <><input id={id} className="ss-input" list={`${id}-list`} value={String(values[f.key] ?? '')} onChange={(e) => set(f.key, e.target.value)} /><datalist id={`${id}-list`}>{names.map((c) => <option key={c} value={c} />)}</datalist></>;
    } else if (f.kind === 'json') {
      control = <textarea id={id} className="ss-input" value={String(values[f.key] ?? '')} placeholder="{}" onChange={(e) => set(f.key, e.target.value)} />;
    } else if (f.kind === 'number') {
      control = <input id={id} className="ss-input" type="number" min={f.min} step="any" disabled={f.key === 'pNom' && extendable} value={String(values[f.key] ?? '')} onChange={(e) => set(f.key, e.target.value)} />;
    } else {
      control = <input id={id} className="ss-input" value={String(values[f.key] ?? '')} disabled={Boolean(editing) && f.key === 'plantId'} placeholder={f.key === 'plantId' ? type.id : undefined} onChange={(e) => set(f.key, e.target.value)} />;
    }
    return (
      <label key={f.key} className="cmp-field" htmlFor={id} title={f.help}>
        <span>{label}</span>
        {control}
      </label>
    );
  };

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
    <div className="cmp-form" data-testid="composite-form">
      <h3>{editing ? `Edit composite ${editing.plantId}` : 'Add a composite'}</h3>
      {!editing && (
        <label className="cmp-field" htmlFor="cmp-type">
          <span>Composite type</span>
          <select id="cmp-type" className="ss-input" value={type.id} onChange={(e) => setTypeId(e.target.value)}>
            {types.map((t) => <option key={t.id} value={t.id}>{t.label}</option>)}
          </select>
        </label>
      )}
      <p className="cmp-note">{type.description}</p>

      <section className="cmp-section" data-testid="composite-connections">
        <h4>Connections</h4>
        <p className="cmp-note">Where this composite plugs into the network. Every choice becomes a bus or generator name in the PyPSA rows it creates.</p>
        {type.portNote && <p className="cmp-note">{type.portNote}</p>}
        <div className="cmp-ports">{ports.map(renderPort)}</div>
        <label className="cmp-field cmp-field--check"><input type="checkbox" checked={showAllBuses} onChange={(e) => setShowAllBuses(e.target.checked)} /><span>Show all buses in the selects (default: only buses whose carrier fits the port)</span></label>
      </section>

      <section className="cmp-section">
        <h4>Size and parameters</h4>
        <div className="cmp-grid">{params.map(renderField)}</div>
        {advanced.length > 0 && (
          <details className="cmp-adv">
            <summary>Advanced (escape hatch){type.technology ? `, defaults: ${type.technology}` : ''}</summary>
            <div className="cmp-grid">{advanced.map(renderField)}</div>
          </details>
        )}
      </section>

      {preview?.technologies && <TechnologyData keys={preview.technologies} />}

      {connections && (
        <section className="cmp-section">
          <h4>How it connects</h4>
          <ul className="cmp-portlist" aria-label="Connections of the preview">
            {connections.ports.map((p) => <li key={p.bus}>{portPhrase(p)} <code>{p.bus}</code>{p.created ? ' (created)' : ''}{p.loadMw !== null ? `; offtake load ${fmt(p.loadMw)} MW` : ''}</li>)}
            {connections.matched.length > 0 && <li>renewable supply matched to generators {connections.matched.map((g) => <code key={g}>{g} </code>)}</li>}
          </ul>
          <ConnectionSchematic connections={connections} />
        </section>
      )}

      {preview && <p className="cmp-note"><strong>{editing ? 'Re-creates' : 'Creates'}:</strong> {counts}.</p>}
      {preview && derivedLines(preview.registry).length > 0 && (
        <div className="cmp-derived" data-testid="plant-derived">
          <strong>Derived values (written to the rows)</strong>
          {derivedLines(preview.registry).map((l) => <p key={l}>{l}</p>)}
        </div>
      )}
      {preview?.warnings.map((w) => <p key={w} className="cmp-warn">{w}</p>)}
      {error && <p className="cmp-error" role="alert">{error}</p>}
      <div className="cmp-actions">
        <button className="run-button" type="button" onClick={apply} disabled={!preview || busy}>
          {editing ? 'Save changes' : `Add ${type.label.split(' (')[0]}`}
        </button>
        {editing && <button className="ghost-button sm" type="button" onClick={onDoneEditing}>Cancel</button>}
      </div>
    </div>
  );
}
