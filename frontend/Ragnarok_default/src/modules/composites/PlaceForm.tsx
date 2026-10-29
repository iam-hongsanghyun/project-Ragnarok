/**
 * PlaceForm — place one composite on several buses (copy-paste). The source is an existing composite or a saved template
 * (`RAGNAROK_CompositeTemplates`); the result is N independent instances named `<prefix>_<bus>`, each a row in the
 * `RAGNAROK_Composites` sheet that can be edited alone afterwards. Fuel / H2 / product ports are either created per instance
 * or shared: the choice is explicit below.
 */
import React, { useEffect, useMemo, useState } from 'react';
import type { GridRow, WorkbookModel } from 'lib/types';
import { plantCards, type PlantCard, type PlantChange } from 'lib/build/plants';
import { previewPlace, type PlacePreview } from 'lib/api/plants';
import { stringValue } from 'lib/utils/helpers';
import { isElectricCarrier } from 'lib/build/connections';

interface Props {
  model: WorkbookModel;
  onApply: (change: PlantChange, label: string) => void | Promise<void>;
  /** Source to start from (the table's Place on buses button). */
  initialSource?: PlantCard | null;
}

interface Source { key: string; label: string; type: string; spec: Record<string, unknown>; prefix: string }

export function PlaceForm({ model, onApply, initialSource }: Props) {
  const sources = useMemo<Source[]>(() => {
    const inst = plantCards(model).filter((c) => c.editable && c.type).map((c) => ({ key: `instance:${c.plantId}`, label: `${c.plantId} (instance)`, type: c.type as string, spec: c.spec ?? {}, prefix: c.plantId }));
    const tpl: Source[] = [];
    for (const r of ((model.RAGNAROK_CompositeTemplates ?? []) as GridRow[])) {
      try { tpl.push({ key: `template:${stringValue(r.name)}`, label: `${stringValue(r.name)} (template)`, type: stringValue(r.type), spec: JSON.parse(stringValue(r.spec)) as Record<string, unknown>, prefix: stringValue(r.name).replace(/_template$/, '') }); } catch { /* unreadable template row: not offered */ }
    }
    return [...tpl, ...inst];
  }, [model]);
  const buses = ((model.buses ?? []) as GridRow[]).filter((b) => isElectricCarrier(stringValue(b.carrier)));      // the electricity port: electric buses only
  const [sourceKey, setSourceKey] = useState(initialSource ? `instance:${initialSource.plantId}` : '');
  const source = sources.find((s) => s.key === sourceKey) ?? sources[0];
  const [chosen, setChosen] = useState<string[]>([]);
  const [prefix, setPrefix] = useState('');
  const [share, setShare] = useState(false);
  const [preview, setPreview] = useState<PlacePreview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => { setPrefix(source?.prefix ?? ''); }, [source?.key]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!source || chosen.length === 0) { setPreview(null); setError(null); return undefined; }
    let live = true;
    const timer = window.setTimeout(() => {
      previewPlace(source.type, source.spec, chosen, prefix, share, model)
        .then((p) => { if (live) { setPreview(p); setError(null); } })
        .catch((e: unknown) => { if (live) { setPreview(null); setError(e instanceof Error ? e.message : 'could not preview'); } });
    }, 250);
    return () => { live = false; window.clearTimeout(timer); };
  }, [source, chosen, prefix, share, model]);

  if (sources.length === 0) return <p className="cmp-note">Nothing to place yet: add a composite first (or save a template from one).</p>;
  const toggle = (b: string) => setChosen((c) => (c.includes(b) ? c.filter((x) => x !== b) : [...c, b]));
  const place = async () => {
    if (!preview || busy) return;
    setBusy(true);
    try { await onApply(preview.change, `Placed ${preview.plantIds.join(', ')}`); setChosen([]); } catch (e) { setError(e instanceof Error ? e.message : 'could not apply'); } finally { setBusy(false); }
  };

  return (
    <div className="cmp-form" data-testid="place-form">
      <h3>Place on buses</h3>
      <p className="cmp-note">Copy one composite onto several buses. Each copy is its own composite (one row in the RAGNAROK_Composites sheet) that you can edit separately afterwards: capacity, ports, build_year.</p>
      <label className="cmp-field" htmlFor="cmp-source"><span>Copy from</span>
        <select id="cmp-source" className="ss-input" value={source?.key ?? ''} onChange={(e) => setSourceKey(e.target.value)}>
          {sources.map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
        </select></label>
      <section className="cmp-section">
        <h4>Electricity buses to place on (one copy each)</h4>
        <div className="cmp-gens" role="group" aria-label="Buses to place on">
          {buses.map((b) => { const n = stringValue(b.name); return <label key={n}><input type="checkbox" checked={chosen.includes(n)} onChange={() => toggle(n)} />{n} <span className="cmp-note">{stringValue(b.carrier)}</span></label>; })}
        </div>
      </section>
      <label className="cmp-field" htmlFor="cmp-prefix"><span>Name prefix (instances are named prefix_bus)</span>
        <input id="cmp-prefix" className="ss-input" value={prefix} onChange={(e) => setPrefix(e.target.value)} /></label>
      <label className="cmp-field cmp-field--check"><input type="checkbox" checked={share} onChange={(e) => setShare(e.target.checked)} />
        <span>Share the fuel, H2 and product buses between the copies</span></label>
      <p className="cmp-note">{share
        ? 'Shared: the copies use the fuel / H2 / product buses of the source (or the first copy creates one and the others reuse it).'
        : 'Per copy (default): each copy creates its own fuel / H2 / product bus (an existing gas bus with a supplier is reused). Tick the box above to share one.'}</p>
      {preview && (
        <ul className="cmp-portlist" aria-label="Instances to be created">
          {preview.instances.map((i) => <li key={i.plantId}><code>{i.plantId}</code> on bus <code>{i.bus}</code>: {Object.entries(i.rowCounts).map(([s, n]) => `${n} ${s}`).join(', ')}</li>)}
        </ul>
      )}
      {preview?.warnings.map((w) => <p key={w} className="cmp-warn">{w}</p>)}
      {error && <p className="cmp-error" role="alert">{error}</p>}
      <div className="cmp-actions"><button className="run-button" type="button" onClick={place} disabled={!preview || busy}>{`Place ${chosen.length || ''} cop${chosen.length === 1 ? 'y' : 'ies'}`.replace('  ', ' ')}</button></div>
    </div>
  );
}
