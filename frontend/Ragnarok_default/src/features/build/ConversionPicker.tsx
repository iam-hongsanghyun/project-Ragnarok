/**
 * "Add conversion technology" panel for the Build Links step.
 *
 * Pick a sector-coupling conversion (CCGT, electrolyser, heat pump, …), the
 * electricity bus it connects to, and a capacity — one click wires the Link,
 * its counterpart carrier bus, the carrier entries, and (for fuel-fed
 * conversions) a fuel-supply generator. The templates and the wiring come from
 * the backend (`/api/build/conversions`, `/api/build/conversion`) — the same
 * code the MCP `add_conversion` tool runs; this is presentation + a live preview.
 */
import React, { useEffect, useState } from 'react';
import type { WorkbookModel } from 'lib/types';
import type { WorkbookFragment } from 'lib/api/databases';
import {
  buildConversion,
  fetchConversionTemplates,
  type ConversionList,
  type ConversionOptions,
} from 'lib/api/forgeBuild';

interface Props {
  model: WorkbookModel;
  busNames: string[];
  /** Settings -> Discount rate: written to an extendable conversion as `discount_rate`. */
  discountRate?: number;
  onApply: (fragment: WorkbookFragment, label: string) => void;
}

export function ConversionPicker({ model, busNames, discountRate, onApply }: Props) {
  const [catalog, setCatalog] = useState<ConversionList | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [templateId, setTemplateId] = useState('');
  const [anchorBus, setAnchorBus] = useState<string>('');
  const [name, setName] = useState('');
  const [pNom, setPNom] = useState(100);
  const [extendable, setExtendable] = useState(false);
  const [preview, setPreview] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let live = true;
    fetchConversionTemplates()
      .then((list) => { if (live) { setCatalog(list); setTemplateId((id) => id || list.items[0]?.id || ''); } })
      .catch((e: unknown) => { if (live) setLoadError(e instanceof Error ? e.message : 'could not load templates'); });
    return () => { live = false; };
  }, []);

  const templates = catalog?.items ?? [];
  const template = templates.find((t) => t.id === templateId) ?? templates[0];
  // The anchor: the user's pick, else the bus the backend resolved as the default
  // electricity bus of this model (returned by the preview call below).
  const [resolvedAnchor, setResolvedAnchor] = useState('');
  const anchor = busNames.includes(anchorBus) ? anchorBus : resolvedAnchor;

  const options: ConversionOptions = { anchorBus: anchor, name, pNom, extendable, discountRate };

  // Live preview of what will be created (also validates the anchor), from the backend.
  useEffect(() => {
    if (!template || busNames.length === 0) { setPreview(null); return undefined; }
    let live = true;
    const timer = window.setTimeout(() => {
      buildConversion(template.id, { anchorBus: busNames.includes(anchorBus) ? anchorBus : undefined, name, pNom, extendable, discountRate }, model)
        .then((built) => {
          if (!live) return;
          setResolvedAnchor(built.anchorBus);
          setPreview(Object.entries(built.fragment.sheets).map(([sheet, r]) => `${r.length} ${sheet}`).join(', '));
        })
        .catch(() => { if (live) setPreview(null); });
    }, 150);
    return () => { live = false; window.clearTimeout(timer); };
  }, [template, anchorBus, busNames, name, pNom, extendable, model, discountRate]);

  const apply = async () => {
    if (!anchor || !template || busy) return;
    setBusy(true);
    try {
      const built = await buildConversion(template.id, options, model);
      onApply(built.fragment, template.label);
      setName('');
    } catch (e) {
      setPreview(null);
      setLoadError(e instanceof Error ? e.message : 'could not build the conversion');
    } finally {
      setBusy(false);
    }
  };

  if (!template) {
    return (
      <div className="conversion-picker">
        <h4 className="conversion-picker__title">Add conversion technology</h4>
        <p className="conversion-picker__hint">{loadError ?? 'Loading templates...'}</p>
      </div>
    );
  }

  return (
    <div className="conversion-picker">
      <h4 className="conversion-picker__title">Add conversion technology</h4>
      <p className="conversion-picker__hint">{template.description}</p>

      <label className="conversion-picker__field">
        <span>Technology</span>
        <select className="ss-input" value={templateId} onChange={(e) => setTemplateId(e.target.value)}>
          {templates.map((t) => (
            <option key={t.id} value={t.id}>{t.label}</option>
          ))}
        </select>
      </label>

      <label className="conversion-picker__field">
        <span>Connect at bus</span>
        <select className="ss-input" value={anchor} onChange={(e) => setAnchorBus(e.target.value)} disabled={busNames.length === 0}>
          {busNames.length === 0 && <option value="">(add a bus first)</option>}
          {busNames.map((b) => (
            <option key={b} value={b}>{b}</option>
          ))}
        </select>
      </label>

      <label className="conversion-picker__field">
        <span>Name (optional)</span>
        <input className="ss-input" value={name} placeholder={template.id} onChange={(e) => setName(e.target.value)} />
      </label>

      <div className="conversion-picker__row">
        <label className="conversion-picker__field conversion-picker__field--inline">
          <span>Capacity (MW)</span>
          <input
            className="ss-input"
            type="number"
            min={0}
            value={pNom}
            disabled={extendable}
            onChange={(e) => setPNom(Math.max(0, Number(e.target.value) || 0))}
          />
        </label>
        <label className="conversion-picker__check">
          <input type="checkbox" checked={extendable} onChange={(e) => setExtendable(e.target.checked)} />
          <span>Let the solver size it</span>
        </label>
      </div>

      {preview && <p className="conversion-picker__preview">Creates: {preview}.</p>}
      {loadError && <p className="conversion-picker__hint">{loadError}</p>}

      <button className="run-button" onClick={apply} disabled={!anchor || busy}>
        Add {template.label.split(' (')[0]}
      </button>
    </div>
  );
}
