/**
 * "Add conversion technology" panel for the Build Links step.
 *
 * Pick a sector-coupling conversion (CCGT, electrolyser, heat pump, …), the
 * electricity bus it connects to, and a capacity — one click wires the Link,
 * its counterpart carrier bus, the carrier entries, and (for fuel-fed
 * conversions) a fuel-supply generator. The heavy lifting is the pure
 * `buildConversionFragment`; this is presentation + a live preview only.
 */
import React, { useMemo, useState } from 'react';
import type { WorkbookModel } from 'lib/types';
import type { WorkbookFragment } from 'lib/api/databases';
import {
  CONVERSION_TEMPLATES,
  buildConversionFragment,
  defaultAnchorBus,
  type ConversionOptions,
} from 'lib/build/conversions';

interface Props {
  model: WorkbookModel;
  busNames: string[];
  onApply: (fragment: WorkbookFragment, label: string) => void;
}

export function ConversionPicker({ model, busNames, onApply }: Props) {
  const [templateId, setTemplateId] = useState(CONVERSION_TEMPLATES[0].id);
  const [anchorBus, setAnchorBus] = useState<string>(() => defaultAnchorBus(model) ?? '');
  const [name, setName] = useState('');
  const [pNom, setPNom] = useState(100);
  const [extendable, setExtendable] = useState(false);

  const template = CONVERSION_TEMPLATES.find((t) => t.id === templateId) ?? CONVERSION_TEMPLATES[0];
  const anchor = busNames.includes(anchorBus) ? anchorBus : (defaultAnchorBus(model) ?? '');

  const options: ConversionOptions = { anchorBus: anchor, name, pNom, extendable };

  // Live preview of what will be created (also validates the anchor).
  const preview = useMemo(() => {
    if (!anchor) return null;
    try {
      const frag = buildConversionFragment(template, options, model);
      return Object.entries(frag.sheets)
        .map(([sheet, r]) => `${r.length} ${sheet}`)
        .join(', ');
    } catch {
      return null;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [template, anchor, name, pNom, extendable, model]);

  const apply = () => {
    if (!anchor) return;
    const frag = buildConversionFragment(template, options, model);
    onApply(frag, template.label);
    setName('');
  };

  return (
    <div className="conversion-picker">
      <h4 className="conversion-picker__title">Add conversion technology</h4>
      <p className="conversion-picker__hint">{template.description}</p>

      <label className="conversion-picker__field">
        <span>Technology</span>
        <select className="ss-input" value={templateId} onChange={(e) => setTemplateId(e.target.value)}>
          {CONVERSION_TEMPLATES.map((t) => (
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

      <button className="run-button" onClick={apply} disabled={!anchor}>
        Add {template.label.split(' (')[0]}
      </button>
    </div>
  );
}
