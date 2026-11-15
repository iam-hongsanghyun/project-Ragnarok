/**
 * The constraints a model carries as sheets, shown where the other constraints are:
 *  - hourly group limits: `RAGNAROK_CarrierOutputFloor` (sum >= floor) and `RAGNAROK_CarrierOutputCap` (sum <= cap),
 *    one column per group (a carrier, or a selector such as `fuel=lng` / `fuel=coal&region=north`);
 *  - period budgets: `RAGNAROK_PeriodBudgets` (energy or emissions over a month, a year or a start/end range).
 * The hourly sheets are series, so their per-group summary is computed server-side (sheet stats); the budgets are a
 * static sheet already in the model. Both are edited as sheets in the Model view.
 */
import React, { useEffect, useMemo, useState } from 'react';
import { WorkbookModel } from 'lib/types';
import { fetchColumnStats, NumericColumnStats } from 'lib/api/analysis';

const FLOOR_SHEET = 'RAGNAROK_CarrierOutputFloor';
const CAP_SHEET = 'RAGNAROK_CarrierOutputCap';
const BUDGET_SHEET = 'RAGNAROK_PeriodBudgets';
const BUDGET_ROWS_SHOWN = 300;

interface GroupLimit {
  sheet: string;
  sense: '>=' | '<=';
  group: string;
  stats: NumericColumnStats;
}

const fmt = (x: number | undefined, digits = 0) =>
  typeof x === 'number' && Number.isFinite(x) ? x.toLocaleString(undefined, { maximumFractionDigits: digits }) : '—';

function useGroupLimits(model: WorkbookModel): { limits: GroupLimit[]; error: string | null; loading: boolean } {
  const [limits, setLimits] = useState<GroupLimit[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  // Refetch when the model is replaced (an import or an edit gives a new object).
  useEffect(() => {
    let alive = true;
    setLoading(true);
    Promise.all(
      ([[FLOOR_SHEET, '>='], [CAP_SHEET, '<=']] as const).map(([sheet, sense]) =>
        fetchColumnStats(sheet)
          .then((s) => s.columns
            .filter((c): c is NumericColumnStats => c.kind === 'numeric' && c.name !== 'snapshot')
            .map((c) => ({ sheet, sense, group: c.name, stats: c })))
          .catch((e: Error) => (/\(404\)/.test(e.message) ? [] : Promise.reject(e))),
      ),
    )
      .then((parts) => { if (alive) { setLimits(parts.flat()); setError(null); } })
      .catch((e: Error) => { if (alive) setError(e.message); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [model]);
  return { limits, error, loading };
}

export function SheetConstraintsSection({ model }: { model: WorkbookModel }) {
  const { limits, error, loading } = useGroupLimits(model);
  const budgets = useMemo(
    () => ((model as unknown as Record<string, unknown>)[BUDGET_SHEET] as Record<string, unknown>[] | undefined) ?? [],
    [model],
  );
  const [filter, setFilter] = useState('');
  const shown = useMemo(() => {
    const f = filter.trim().toLowerCase();
    const rows = f ? budgets.filter((r) => Object.values(r).some((v) => String(v ?? '').toLowerCase().includes(f))) : budgets;
    return { rows: rows.slice(0, BUDGET_ROWS_SHOWN), total: rows.length };
  }, [budgets, filter]);

  return (
    <section className="constraints-workspace-section" data-tour="sheet-constraints">
      <header className="constraints-workspace-section-header">
        <h3>Sheet constraints</h3>
        <p>
          Limits the model carries as sheets, applied to the solver like the code above. Hourly group limits:{' '}
          <code>{FLOOR_SHEET}</code> (sum ≥ floor) and <code>{CAP_SHEET}</code> (sum ≤ cap), one column per group — a
          carrier, or a selector <code>column=value</code> on the generator or its bus (<code>fuel=lng</code>,{' '}
          <code>fuel=coal&amp;region=north</code>). Period budgets: <code>{BUDGET_SHEET}</code>. Edit them as sheets in the Model view.
        </p>
      </header>

      <div className="sg-setting-row">
        <label className="sg-setting-label">Hourly group limits</label>
        {error ? (
          <div className="constraints-cell-placeholder" role="alert">{error}</div>
        ) : limits.length === 0 ? (
          <div className="constraints-cell-placeholder">{loading ? 'Reading…' : 'No hourly floor or cap in this model.'}</div>
        ) : (
          <div className="constraints-table-wrap">
            <table className="constraints-table">
              <thead>
                <tr><th>Sheet</th><th>Group</th><th>Sense</th><th>Hours set</th><th>Min MW</th><th>Mean MW</th><th>Max MW</th><th>Σ MWh (GWh)</th></tr>
              </thead>
              <tbody>
                {limits.map((l) => (
                  <tr key={`${l.sheet}:${l.group}`}>
                    <td><code>{l.sheet === FLOOR_SHEET ? 'Floor' : 'Cap'}</code></td>
                    <td><code>{l.group}</code></td>
                    <td>{l.sense}</td>
                    <td>{fmt(l.stats.count)}</td>
                    <td>{fmt(l.stats.min)}</td>
                    <td>{fmt(l.stats.mean)}</td>
                    <td>{fmt(l.stats.max)}</td>
                    <td>{fmt(l.stats.sum / 1e3, 1)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="sg-setting-row">
        <label className="sg-setting-label">
          Period budgets ({budgets.length.toLocaleString()})
        </label>
        {budgets.length === 0 ? (
          <div className="constraints-cell-placeholder">No period budgets in this model.</div>
        ) : (
          <>
            <input
              className="constraints-dsl-input"
              style={{ minHeight: 0 }}
              placeholder="Filter (name, generator, period, sense…)"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
            />
            <div className="constraints-table-wrap" style={{ maxHeight: 420, overflow: 'auto' }}>
              <table className="constraints-table">
                <thead>
                  <tr><th>Name</th><th>Measure</th><th>Generators / carrier</th><th>Period</th><th>Sense</th><th>Value</th></tr>
                </thead>
                <tbody>
                  {shown.rows.map((r, i) => {
                    const gens = String(r.generator ?? '');
                    const period = String(r.period ?? '') || [r.start, r.end].filter(Boolean).join(' → ');
                    return (
                      <tr key={`${String(r.name ?? '')}:${i}`}>
                        <td><code>{String(r.name ?? '')}</code></td>
                        <td>{String(r.measure ?? 'energy')}</td>
                        <td title={gens}>{gens ? (gens.length > 60 ? `${gens.slice(0, 60)}… (${gens.split(',').length})` : gens) : String(r.carrier ?? '')}</td>
                        <td>{period}</td>
                        <td>{String(r.sense ?? '<=')}</td>
                        <td>{fmt(Number(r.value), 1)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            {shown.total > shown.rows.length && (
              <div className="constraints-cell-placeholder">
                Showing {shown.rows.length.toLocaleString()} of {shown.total.toLocaleString()} — filter to narrow.
              </div>
            )}
          </>
        )}
      </div>
    </section>
  );
}
