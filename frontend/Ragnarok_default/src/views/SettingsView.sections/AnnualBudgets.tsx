/**
 * Annual budgets (module) - a yearly energy or emission budget, written into PyPSA as a horizon total.
 *
 * PyPSA's `e_sum_min` / `e_sum_max` (generators) and the `constant` of a GlobalConstraint (CO2 cap, operational limit)
 * are totals over the modelled snapshots and are never scaled to the horizon. Enter the YEARLY value here; the module
 * writes `annual x sum(w) / 8760` into the PyPSA column (shown below, and in the run notes). Everything is computed
 * on the server; this view only shows its table.
 */
import React, { useCallback, useEffect, useState } from 'react';
import {
  applyAnnualBudgets, previewAnnualBudgets, setAnnualBudget,
  type BudgetPreview, type BudgetRow,
} from 'lib/api/policyModules';

const TARGETS: { component: string; attribute: string; label: string }[] = [
  { component: 'generators', attribute: 'e_sum_max', label: 'Generator energy cap (e_sum_max, MWh per year)' },
  { component: 'generators', attribute: 'e_sum_min', label: 'Generator energy floor (e_sum_min, MWh per year)' },
  { component: 'global_constraints', attribute: 'constant', label: 'Global constraint (CO2 cap / operational limit, per year)' },
];

export function AnnualBudgetsSection() {
  const [preview, setPreview] = useState<BudgetPreview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState<BudgetRow>({ component: 'generators', attribute: 'e_sum_max', name: '', annual: 0 });
  const [applied, setApplied] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try { setPreview(await previewAnnualBudgets()); setError(null); } catch (e) { setError((e as Error).message); }
  }, []);
  useEffect(() => { void refresh(); }, [refresh]);

  const save = async () => {
    try { await setAnnualBudget(draft); setApplied(null); await refresh(); } catch (e) { setError((e as Error).message); }
  };
  const apply = async () => {
    try {
      const out = await applyAnnualBudgets();
      setApplied(`Written into: ${out.sheetsWritten.join(', ') || 'nothing'}. Apply again after the snapshots or the horizon change.`);
      await refresh();
    } catch (e) { setError((e as Error).message); }
  };

  return (
    <section className="constraints-workspace-section">
      <header className="constraints-workspace-section-header">
        <h3>Annual budgets</h3>
        <p>
          PyPSA's <code>e_sum_min/max</code> and a GlobalConstraint <code>constant</code> are totals over the modelled horizon;
          they are not scaled to it. Enter the <b>yearly</b> value; the module writes <code>annual x sum(w) / 8760</code> with the
          <code> generators</code> snapshot weighting (hours each snapshot represents). A 168 h run gets 168/8760 of it.
        </p>
        <p>
          <b>Pathways:</b> an <code>e_sum</code> is one whole-horizon total over all periods (energy may move between periods).
          A global constraint with an <code>investment_period</code> is that period's total: annual x its hours / 8760 x its
          <code> years</code> weight; without one it covers all periods, each weighted by its years. Caps you typed as totals in
          the Constraints tables stay exactly as typed.
        </p>
        <p>If the timestamps are further apart than the snapshot weighting (a 4-hourly model with weight 1), the notes warn; nothing is changed for you.</p>
      </header>
      {error && <p className="sg-setting-hint" role="alert">{error}</p>}
      <div className="sg-setting-row">
        <select value={`${draft.component}.${draft.attribute}`} onChange={(e) => {
          const [component, attribute] = e.target.value.split('.');
          setDraft({ ...draft, component, attribute });
        }}>
          {TARGETS.map((t) => <option key={`${t.component}.${t.attribute}`} value={`${t.component}.${t.attribute}`}>{t.label}</option>)}
        </select>
        <input aria-label="Component name" placeholder="component name" value={draft.name}
          onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
        <input aria-label="Annual value" type="number" value={draft.annual}
          onChange={(e) => setDraft({ ...draft, annual: Number(e.target.value) })} />
        <button type="button" onClick={() => void save()} disabled={!draft.name}>Save budget</button>
      </div>
      {preview && preview.table.length > 0 && (
        <table className="sg-table">
          <thead><tr><th>Component</th><th>Attribute</th><th>Per year</th><th>Horizon (years)</th><th>Written to PyPSA</th><th>Scope</th></tr></thead>
          <tbody>
            {preview.table.map((r) => (
              <tr key={`${r.component}.${r.name}.${r.attribute}`}>
                <td>{r.component} / {r.name}</td><td>{r.attribute}</td><td>{r.annual.toLocaleString()}</td>
                <td>{r.horizonYears.toFixed(4)}</td><td>{r.value.toLocaleString(undefined, { maximumFractionDigits: 2 })}</td><td>{r.scope}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {preview?.notes.map((n) => <p key={n} className="sg-setting-hint">{n}</p>)}
      <div className="sg-setting-row">
        <button type="button" onClick={() => void apply()} disabled={!preview || preview.table.length === 0}>Write into the workbook</button>
        {applied && <span className="sg-setting-hint">{applied}</span>}
      </div>
    </section>
  );
}
