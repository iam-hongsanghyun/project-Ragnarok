import React, { useState } from 'react';
import { ConstraintMetric, CustomConstraint } from '../../shared/types';
import { METRIC_DEFS } from '../../constants';

export function GlobalConstraintsSection({
  constraints,
  carriers,
  onChange,
}: {
  constraints: CustomConstraint[];
  carriers: string[];
  onChange: (next: CustomConstraint[]) => void;
}) {
  const [addOpen, setAddOpen] = useState(false);
  const [newMetric, setNewMetric] = useState<ConstraintMetric>('co2_cap');
  const [newCarrier, setNewCarrier] = useState('');
  const [newValue, setNewValue] = useState(0);
  const [newLabel, setNewLabel] = useState('');

  const update = (id: string, patch: Partial<CustomConstraint>) =>
    onChange(constraints.map((c) => (c.id === id ? { ...c, ...patch } : c)));

  const presets = constraints.filter((c) => c.id.startsWith('p_'));
  const customs = constraints.filter((c) => !c.id.startsWith('p_'));
  const activeCount = constraints.filter((c) => c.enabled).length;
  const def = METRIC_DEFS[newMetric];

  const handleAdd = () => {
    if (!newLabel.trim() && !def) return;
    const nc: CustomConstraint = {
      id: `cc_${Date.now()}`,
      enabled: true,
      label: newLabel.trim() || def.label,
      metric: newMetric,
      carrier: def.needsCarrier ? newCarrier : '',
      value: newValue,
      unit: def.unit,
    };
    onChange([...constraints, nc]);
    setAddOpen(false);
    setNewLabel('');
    setNewValue(0);
  };

  return (
    <div className="gcc">
      {activeCount > 0 && (
        <div className="gcc-active-row">
          <span className="gcc-active-dot" />
          <span className="gcc-active-label">{activeCount} active</span>
        </div>
      )}

      <div className="gcc-section-label">Presets</div>
      {presets.map((c) => {
        const d = METRIC_DEFS[c.metric];
        return (
          <div key={c.id} className={`gcc-row${c.enabled ? ' gcc-row--on' : ''}`}>
            <input className="gcc-check" type="checkbox" checked={c.enabled} onChange={(e) => update(c.id, { enabled: e.target.checked })} />
            <span className="gcc-sense" title={d?.description}>{d?.sense}</span>
            <span className="gcc-label" title={d?.description}>{c.label}</span>
            {d?.needsCarrier && (
              <select className="gcc-carrier" value={c.carrier} onChange={(e) => update(c.id, { carrier: e.target.value })}>
                {carriers.map((ca) => <option key={ca}>{ca}</option>)}
              </select>
            )}
            <input className="gcc-val" type="number" value={c.value} onChange={(e) => update(c.id, { value: parseFloat(e.target.value) || 0 })} />
            <span className="gcc-unit">{c.unit}</span>
          </div>
        );
      })}

      {customs.length > 0 && (
        <>
          <div className="gcc-section-label" style={{ marginTop: 6 }}>Custom</div>
          {customs.map((c) => {
            const d = METRIC_DEFS[c.metric];
            return (
              <div key={c.id} className={`gcc-row${c.enabled ? ' gcc-row--on' : ''}`}>
                <input className="gcc-check" type="checkbox" checked={c.enabled} onChange={(e) => update(c.id, { enabled: e.target.checked })} />
                <span className="gcc-sense">{d?.sense}</span>
                <input className="gcc-label-input" value={c.label} onChange={(e) => update(c.id, { label: e.target.value })} />
                {d?.needsCarrier && (
                  <select className="gcc-carrier" value={c.carrier} onChange={(e) => update(c.id, { carrier: e.target.value })}>
                    {carriers.map((ca) => <option key={ca}>{ca}</option>)}
                  </select>
                )}
                <input className="gcc-val" type="number" value={c.value} onChange={(e) => update(c.id, { value: parseFloat(e.target.value) || 0 })} />
                <span className="gcc-unit">{c.unit}</span>
                <button className="gcc-del" onClick={() => onChange(constraints.filter((x) => x.id !== c.id))}>x</button>
              </div>
            );
          })}
        </>
      )}

      {!addOpen ? (
        <button className="gcc-add-btn" onClick={() => setAddOpen(true)}>+ Add constraint</button>
      ) : (
        <div className="gcc-add-form">
          <div className="gcc-add-row">
            <select className="gcc-add-metric" value={newMetric} onChange={(e) => { setNewMetric(e.target.value as ConstraintMetric); setNewCarrier(''); }}>
              {(Object.keys(METRIC_DEFS) as ConstraintMetric[]).map((m) => (
                <option key={m} value={m}>{METRIC_DEFS[m].label}</option>
              ))}
            </select>
          </div>
          <div className="gcc-add-row">
            {def.needsCarrier && (
              <select className="gcc-carrier" value={newCarrier} onChange={(e) => setNewCarrier(e.target.value)}>
                <option value="">— carrier —</option>
                {carriers.map((ca) => <option key={ca}>{ca}</option>)}
              </select>
            )}
            <input className="gcc-val" type="number" value={newValue} onChange={(e) => setNewValue(parseFloat(e.target.value) || 0)} />
            <span className="gcc-unit">{def.unit}</span>
          </div>
          <div className="gcc-add-row">
            <input className="gcc-label-input" placeholder="Label (optional)" value={newLabel} onChange={(e) => setNewLabel(e.target.value)} />
          </div>
          <div className="gcc-add-row">
            <button className="tb-btn" onClick={handleAdd}>Add</button>
            <button className="tb-btn tb-btn--muted" onClick={() => setAddOpen(false)}>Cancel</button>
          </div>
        </div>
      )}
    </div>
  );
}
