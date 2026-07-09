/**
 * Forge — set a carrier's total capacity to a target (MW).
 *
 * Distributes the target across the carrier's generators by one of three
 * methods (proportional to current p_nom, equal split, or user-defined
 * per-unit MW) and writes it in one of two modes:
 *   • cap — each unit's share → `p_nom_max`, unit marked extendable, so the
 *     optimiser builds *up to* the share and the carrier is bounded AT target.
 *   • fix — each unit's share → `p_nom`, unit marked non-extendable, so the
 *     carrier's installed capacity EQUALS the target.
 *
 * The math lives server-side (`/api/transform/scale-carrier-capacity`); this is
 * the thin UI + the custom per-unit editor.
 */
import React, { useEffect, useMemo, useState } from 'react';
import type { WorkbookModel } from 'lib/types';
import { usePersistedState } from 'shared/hooks/usePersistedState';
import { SearchableSelect } from 'shared/components/SearchableSelect';

export interface ScaleCarrierCapacityResult {
  carrier: string;
  targetMw: number;
  before: number;
  after: number;
  method: string;
  mode: string;
  perUnit: Array<{ name: string; before: number; after: number }>;
  notes?: string[];
}

interface Props {
  model: WorkbookModel;
  onScaleCarrierCapacity: (opts: {
    carrier: string;
    targetMw: number;
    method: 'proportional' | 'equal' | 'custom';
    mode: 'cap' | 'fix';
    shares?: Record<string, number>;
  }) => Promise<ScaleCarrierCapacityResult>;
  onStatus: (msg: string) => void;
}

type Method = 'proportional' | 'equal' | 'custom';
type Mode = 'cap' | 'fix';

const num = (v: unknown): number => {
  const n = Number(v);
  return Number.isFinite(n) ? n : 0;
};

export function CapacityTargetPanel({ model, onScaleCarrierCapacity, onStatus }: Props) {
  const generators = model.generators ?? [];
  const carriers = useMemo(
    () =>
      Array.from(new Set(generators.map((g) => String(g.carrier ?? '')).filter(Boolean))).sort(),
    [generators],
  );

  const [carrier, setCarrier] = usePersistedState<string>('ui:forge-captarget-carrier', carriers[0] ?? '');
  const [target, setTarget] = usePersistedState<number>('ui:forge-captarget-mw', 0);
  const [method, setMethod] = usePersistedState<Method>('ui:forge-captarget-method', 'proportional');
  const [mode, setMode] = usePersistedState<Mode>('ui:forge-captarget-mode', 'cap');
  const [shares, setShares] = useState<Record<string, number>>({});
  const [busy, setBusy] = useState(false);

  const activeCarrier = carriers.includes(carrier) ? carrier : (carriers[0] ?? '');
  const carrierGens = useMemo(
    () => generators.filter((g) => String(g.carrier ?? '') === activeCarrier),
    [generators, activeCarrier],
  );
  const currentTotal = useMemo(
    () => carrierGens.reduce((s, g) => s + num(g.p_nom), 0),
    [carrierGens],
  );

  // Seed the custom per-unit editor from current p_nom whenever it opens or the
  // carrier changes; preserve any values the user has already typed.
  useEffect(() => {
    if (method !== 'custom') return;
    setShares((prev) => {
      const next: Record<string, number> = {};
      carrierGens.forEach((g) => {
        const name = String(g.name);
        next[name] = name in prev ? prev[name] : num(g.p_nom);
      });
      return next;
    });
  }, [method, activeCarrier, carrierGens]);

  const shareSum = useMemo(
    () => carrierGens.reduce((s, g) => s + num(shares[String(g.name)]), 0),
    [shares, carrierGens],
  );
  const customValid = method !== 'custom' || Math.abs(shareSum - target) <= 1e-6 * Math.max(1, target);
  const canApply = !!activeCarrier && carrierGens.length > 0 && target > 0 && customValid && !busy;

  const apply = async () => {
    if (!canApply) return;
    setBusy(true);
    try {
      const r = await onScaleCarrierCapacity({
        carrier: activeCarrier,
        targetMw: target,
        method,
        mode,
        shares: method === 'custom' ? shares : undefined,
      });
      onStatus(
        `${r.carrier}: ${r.before.toFixed(1)} → ${r.after.toFixed(1)} MW ` +
          `(${r.method}, ${r.mode === 'cap' ? 'expansion limit' : 'fixed capacity'})` +
          (r.notes && r.notes.length ? ` — ${r.notes.join(' ')}` : ''),
      );
    } catch (e) {
      onStatus(e instanceof Error ? e.message : 'Capacity adjustment failed.');
    } finally {
      setBusy(false);
    }
  };

  if (carriers.length === 0) {
    return (
      <section className="forge-section">
        <header className="forge-section-header"><h3>Set carrier capacity target</h3></header>
        <p className="sg-setting-hint">No generators in this model to retarget.</p>
      </section>
    );
  }

  return (
    <section className="forge-section">
      <header className="forge-section-header">
        <h3>Set carrier capacity target</h3>
        <p>
          Adjust a carrier's total capacity to a target and distribute it across its
          generators. <b>Expansion limit</b> writes <code>p_nom_max</code> (extendable — the
          solver builds up to the target); <b>fixed capacity</b> writes <code>p_nom</code>
          (installed capacity equals the target).
        </p>
      </header>

      <div className="sg-setting-row">
        <label className="sg-setting-label">Carrier</label>
        <SearchableSelect
          className="forge-adjust-select"
          value={activeCarrier}
          placeholder="carrier"
          options={carriers.map((c) => ({
            value: c,
            label: `${c} (${generators.filter((g) => String(g.carrier ?? '') === c).length})`,
          }))}
          onChange={setCarrier}
        />
        <span className="sg-setting-hint" style={{ margin: 0 }}>
          {carrierGens.length} generator{carrierGens.length === 1 ? '' : 's'} · currently {currentTotal.toFixed(1)} MW
        </span>
      </div>

      <div className="sg-setting-row">
        <label className="sg-setting-label">Target capacity (MW)</label>
        <input
          type="number" className="forge-number" min={0} step={100}
          value={target}
          onChange={(e) => setTarget(Math.max(0, num(e.target.value)))}
          style={{ width: 120 }}
        />
      </div>

      <div className="sg-setting-row">
        <label className="sg-setting-label">Distribute</label>
        <select className="forge-adjust-select" value={method} onChange={(e) => setMethod(e.target.value as Method)}>
          <option value="proportional">Proportional to current capacity</option>
          <option value="equal">Equal across generators</option>
          <option value="custom">User-defined per generator</option>
        </select>
      </div>

      <div className="sg-setting-row">
        <label className="sg-setting-label">Write as</label>
        <select className="forge-adjust-select" value={mode} onChange={(e) => setMode(e.target.value as Mode)}>
          <option value="cap">Expansion limit (p_nom_max, extendable — up to target)</option>
          <option value="fix">Fixed capacity (p_nom — exactly target)</option>
        </select>
      </div>

      {method === 'custom' && (
        <div className="forge-captarget-custom">
          {carrierGens.map((g) => {
            const name = String(g.name);
            return (
              <div className="forge-adjust-row" key={name}>
                <span className="sg-setting-label" style={{ minWidth: 160 }}>{name}</span>
                <input
                  type="number" className="forge-number" min={0} step={10}
                  value={shares[name] ?? 0}
                  onChange={(e) => setShares((prev) => ({ ...prev, [name]: Math.max(0, num(e.target.value)) }))}
                  style={{ width: 110 }}
                />
                <span className="sg-setting-hint" style={{ margin: 0 }}>MW</span>
              </div>
            );
          })}
          <p className="sg-setting-hint" style={{ color: customValid ? undefined : 'var(--warning, #b45309)' }}>
            Per-unit total: {shareSum.toFixed(1)} MW {customValid ? '=' : '≠'} target {target.toFixed(1)} MW
          </p>
        </div>
      )}

      <div className="forge-adjust-actions">
        <button type="button" className="primary-button" onClick={apply} disabled={!canApply}>
          {busy ? 'Applying…' : `Set ${activeCarrier || 'carrier'} to ${target.toFixed(0)} MW`}
        </button>
      </div>
    </section>
  );
}
