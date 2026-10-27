/**
 * Advanced solve options — solver choice, n.optimize switches and the piecewise
 * formulation list. Rendered at the bottom of the Solver section; every control
 * maps 1:1 to a run option (see lib/settings/advancedSolve.ts), so an untouched
 * panel changes nothing about the solve call.
 */
import React, { useEffect, useState } from 'react';
import { API_BASE } from 'lib/constants';
import type {
  AdvancedSolveOptions,
  PiecewiseMethod,
  PiecewiseOption,
} from 'lib/settings/advancedSolve';

interface SolverInfo { name: string; label: string; installed: boolean; iis: boolean }
interface PiecewiseCurve { component: string; attribute: string }

const METHODS: PiecewiseMethod[] = ['auto', 'lp', 'incremental', 'sos2'];

export interface SolverAdvancedProps {
  value?: AdvancedSolveOptions;
  onChange: (v: AdvancedSolveOptions) => void;
}

export function SolverAdvanced({ value, onChange }: SolverAdvancedProps) {
  const adv = value ?? {};
  const [solvers, setSolvers] = useState<SolverInfo[]>([]);
  const [curves, setCurves] = useState<PiecewiseCurve[]>([]);

  useEffect(() => {
    let alive = true;
    fetch(`${API_BASE}/api/optimise/options`)
      .then((r) => (r.ok ? r.json() : null))
      .then((j) => { if (alive && j?.solvers) setSolvers(j.solvers as SolverInfo[]); })
      .catch(() => undefined);
    fetch(`${API_BASE}/api/piecewise/catalog`)
      .then((r) => (r.ok ? r.json() : null))
      .then((j) => { if (alive && j?.curves) setCurves(j.curves as PiecewiseCurve[]); })
      .catch(() => undefined);
    return () => { alive = false; };
  }, []);

  const set = (patch: Partial<AdvancedSolveOptions>) => onChange({ ...adv, ...patch });
  const pw = adv.piecewiseOptions ?? [];
  const setPw = (next: PiecewiseOption[]) => set({ piecewiseOptions: next });
  const toggle = (label: string, key: 'transmissionLosses' | 'linearizedUnitCommitment' | 'computeInfeasibilities', hint: string) => (
    <div className="sg-setting-row">
      <label className="sg-setting-label">{label}</label>
      <div className="sg-btn-row">
        {[false, true].map((v) => (
          <button
            key={String(v)}
            className={`tb-btn sg-solver-btn${!!adv[key] === v ? '' : ' tb-btn--muted'}`}
            onClick={() => set({ [key]: v } as Partial<AdvancedSolveOptions>)}
          >
            {v ? 'On' : 'Off'}
          </button>
        ))}
      </div>
      <p className="sg-setting-hint">{hint}</p>
    </div>
  );

  return (
    <details className="sg-setting-row">
      <summary className="sg-setting-label">Advanced (n.optimize)</summary>
      <div className="sg-setting-row">
        <label className="sg-setting-label">Solver</label>
        <div className="sg-btn-row">
          <select
            value={adv.solverName ?? 'highs'}
            onChange={(e) => set({ solverName: e.target.value })}
          >
            {(solvers.length ? solvers.filter((s) => s.installed) : [{ name: 'highs', label: 'HiGHS' } as SolverInfo]).map((s) => (
              <option key={s.name} value={s.name}>{s.label}</option>
            ))}
          </select>
        </div>
        <p className="sg-setting-hint">Only installed solvers are listed; HiGHS is the default. The HiGHS method / auto-scale settings above apply to HiGHS only.</p>
      </div>
      {toggle('Transmission losses', 'transmissionLosses', 'Secant-based line/link losses (adds constraints per branch).')}
      {toggle('Linearised unit commitment', 'linearizedUnitCommitment', 'Relax committable binaries to an LP.')}
      {toggle('Compute infeasibilities (IIS)', 'computeInfeasibilities', 'On an infeasible solve append the solver IIS (Gurobi / Xpress only).')}
      <div className="sg-setting-row">
        <label className="sg-setting-label">Committable big-M (MW)</label>
        <div className="sg-btn-row">
          <input
            type="number"
            min={0}
            placeholder="PyPSA default"
            aria-label="Committable big-M in MW"
            value={adv.committableBigM ?? ''}
            onChange={(e) => {
              const n = Number(e.target.value);
              set({ committableBigM: e.target.value !== '' && Number.isFinite(n) && n > 0 ? n : undefined });
            }}
          />
        </div>
        <p className="sg-setting-hint">Big-M for committable units that are also extendable. Leave empty for PyPSA's default; only a positive value is sent.</p>
      </div>
      <div className="sg-setting-row">
        <label className="sg-setting-label">Cycle basis method</label>
        <div className="sg-btn-row">
          <select
            value={adv.cycleBasisMethod ?? 'bfs-refined'}
            onChange={(e) => set({ cycleBasisMethod: e.target.value as 'bfs-refined' | 'paton' })}
          >
            <option value="bfs-refined">bfs-refined</option>
            <option value="paton">paton</option>
          </select>
        </div>
      </div>
      <div className="sg-setting-row">
        <label className="sg-setting-label">Piecewise formulation</label>
        {pw.map((p, i) => (
          <div className="sg-btn-row" key={i}>
            <select
              value={`${p.component}.${p.attribute}`}
              onChange={(e) => {
                const [component, attribute] = e.target.value.split('.');
                setPw(pw.map((q, j) => (j === i ? { ...q, component, attribute } : q)));
              }}
            >
              {curves.map((c) => (
                <option key={`${c.component}.${c.attribute}`} value={`${c.component}.${c.attribute}`}>
                  {c.component}.{c.attribute}
                </option>
              ))}
            </select>
            <select
              value={p.method}
              onChange={(e) => setPw(pw.map((q, j) => (j === i ? { ...q, method: e.target.value as PiecewiseMethod } : q)))}
            >
              {METHODS.map((m) => <option key={m} value={m}>{m}</option>)}
            </select>
            <select
              value={p.sign ?? ''}
              onChange={(e) => setPw(pw.map((q, j) => (j === i ? { ...q, sign: (e.target.value || undefined) as PiecewiseOption['sign'] } : q)))}
            >
              <option value="">sign: default</option>
              <option value=">=">&gt;=</option>
              <option value="<=">&lt;=</option>
              <option value="=">=</option>
            </select>
            <input
              placeholder="names (comma, optional)"
              value={(p.name ?? []).join(',')}
              onChange={(e) => setPw(pw.map((q, j) => (j === i ? { ...q, name: e.target.value.split(',').map((s) => s.trim()).filter(Boolean) } : q)))}
            />
            <button className="tb-btn tb-btn--muted" onClick={() => setPw(pw.filter((_, j) => j !== i))}>Remove</button>
          </div>
        ))}
        <div className="sg-btn-row">
          <button
            className="tb-btn"
            disabled={!curves.length}
            onClick={() => setPw([...pw, { component: curves[0].component, attribute: curves[0].attribute, method: 'auto' }])}
          >
            Add override
          </button>
        </div>
        <p className="sg-setting-hint">
          Per-curve formulation for piecewise-linear costs / efficiencies. Without an entry PyPSA picks tangent
          cuts (LP) for convex costs and binaries otherwise. Default sign is &gt;= for cost curves and = for
          efficiency / rate curves; <b>sos2</b> is reformulated automatically on HiGHS.
        </p>
      </div>
    </details>
  );
}
