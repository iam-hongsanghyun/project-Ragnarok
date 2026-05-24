/**
 * CapacityByPeriodCard — for pathway runs, shows how installed capacity
 * (MW) evolves across investment periods, stacked by carrier or by
 * generator. Driven entirely off `(model, outputs)` so it matches whatever
 * data is currently cached — works on imported projects too.
 *
 * Two view modes:
 *   • Cumulative  — total active capacity in each period
 *                   (build_year ≤ P < build_year + lifetime).
 *                   Capacity = p_nom_opt for extendable assets, else p_nom.
 *   • New additions — only capacity commissioned in that period
 *                     (build_year == P). For extendable assets the
 *                     newly-added capacity is p_nom_opt − p_nom; for
 *                     fixed assets it is p_nom (a one-period bar).
 */
import React, { useMemo, useState } from 'react';
import { GridRow, RunResults, TimeSeriesRow, WorkbookModel } from '../../../shared/types';
import { carrierColor, hashColor, numberValue, resolvedColor, stringValue } from '../../../shared/utils/helpers';
import { InteractiveTimeSeriesCard } from './InteractiveTimeSeriesCard';

interface Props {
  model: WorkbookModel;
  results: RunResults;
}

type GroupMode = 'carrier' | 'generator';
type ViewMode = 'cumulative' | 'new';

interface GenSpec {
  name: string;
  carrier: string;
  buildYear: number;
  lifetime: number;
  pNom: number;
  pNomOpt: number;
  extendable: boolean;
  color: string;
}

function parseGenerator(
  row: GridRow,
  optStatic: Record<string, Record<string, unknown>>,
): GenSpec | null {
  const name = stringValue(row.name);
  if (!name) return null;
  const extendable =
    row.p_nom_extendable === true ||
    String(row.p_nom_extendable ?? '').toLowerCase() === 'true';
  const pNom = numberValue(row.p_nom);
  const optAttrs = optStatic[name] ?? {};
  const optRaw = optAttrs.p_nom_opt;
  const pNomOpt =
    optRaw !== undefined && optRaw !== null && optRaw !== '' ? Number(optRaw) : pNom;
  return {
    name,
    carrier: stringValue(row.carrier) || 'Other',
    buildYear: numberValue(row.build_year),
    lifetime: numberValue(row.lifetime),
    pNom: Number.isFinite(pNom) ? pNom : 0,
    pNomOpt: Number.isFinite(pNomOpt) ? pNomOpt : 0,
    extendable,
    color: resolvedColor(row.color, row.carrier),
  };
}

/** Active capacity for a generator at the given period (cumulative view). */
function activeCapacity(g: GenSpec, period: number): number {
  if (g.buildYear > 0 && period < g.buildYear) return 0;
  if (g.buildYear > 0 && g.lifetime > 0 && period >= g.buildYear + g.lifetime) return 0;
  const cap = g.extendable ? g.pNomOpt : g.pNom;
  return cap > 0 ? cap : 0;
}

/** New capacity added in this period only (build_year == period). */
function newAdditionCapacity(g: GenSpec, period: number): number {
  if (g.buildYear !== period) return 0;
  if (g.extendable) {
    const delta = g.pNomOpt - g.pNom;
    return delta > 0 ? delta : 0;
  }
  return g.pNom > 0 ? g.pNom : 0;
}

export function CapacityByPeriodCard({ model, results }: Props) {
  const [groupMode, setGroupMode] = useState<GroupMode>('carrier');
  const [viewMode, setViewMode] = useState<ViewMode>('cumulative');

  const periods = useMemo(() => results.pathway?.periods ?? [], [results.pathway]);
  const optStatic = useMemo(
    () => results.outputs?.static?.generators ?? {},
    [results.outputs],
  );

  const generators = useMemo(
    () => (model.generators ?? []).map((row) => parseGenerator(row, optStatic)).filter((g): g is GenSpec => !!g),
    [model.generators, optStatic],
  );

  const { rows, series } = useMemo(() => {
    if (!periods.length) return { rows: [] as TimeSeriesRow[], series: [] };

    const keys = new Set<string>();
    const tableRows: TimeSeriesRow[] = periods.map((period) => {
      const row: TimeSeriesRow = { label: String(period), timestamp: String(period) };
      for (const g of generators) {
        const cap = viewMode === 'cumulative' ? activeCapacity(g, period) : newAdditionCapacity(g, period);
        if (cap <= 0) continue;
        const key = groupMode === 'carrier' ? g.carrier : g.name;
        row[key] = (Number(row[key]) || 0) + cap;
        keys.add(key);
      }
      return row;
    });

    const keyList = Array.from(keys);
    const seriesList = keyList.map((k) => {
      if (groupMode === 'carrier') {
        return { key: k, label: k, color: carrierColor(k) };
      }
      const sample = generators.find((g) => g.name === k);
      return { key: k, label: k, color: sample?.color ?? hashColor(k) };
    });

    const totals: Record<string, number> = {};
    for (const r of tableRows) for (const k of keyList) totals[k] = (totals[k] ?? 0) + (Number(r[k]) || 0);
    seriesList.sort((a, b) => (totals[b.key] ?? 0) - (totals[a.key] ?? 0));

    return { rows: tableRows, series: seriesList };
  }, [periods, generators, groupMode, viewMode]);

  if (!periods.length || rows.length === 0 || series.length === 0) {
    return (
      <p style={{ color: 'var(--muted)', fontSize: '0.85rem' }}>
        No capacity changes to display — confirm <code>build_year</code> /
        <code> lifetime</code> are set on the generators sheet and the pathway
        run produced <code>p_nom_opt</code>.
      </p>
    );
  }

  return (
    <div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, alignItems: 'center', marginBottom: 12 }}>
        <div className="period-pill-row" role="group" aria-label="Group capacity by">
          <button
            className={`tb-btn period-pill${groupMode === 'carrier' ? '' : ' tb-btn--muted'}`}
            onClick={() => setGroupMode('carrier')}
          >
            By carrier
          </button>
          <button
            className={`tb-btn period-pill${groupMode === 'generator' ? '' : ' tb-btn--muted'}`}
            onClick={() => setGroupMode('generator')}
          >
            By generator
          </button>
        </div>
        <div className="period-pill-row" role="group" aria-label="Capacity view">
          <button
            className={`tb-btn period-pill${viewMode === 'cumulative' ? '' : ' tb-btn--muted'}`}
            onClick={() => setViewMode('cumulative')}
            title="Total active capacity in each period"
          >
            Cumulative
          </button>
          <button
            className={`tb-btn period-pill${viewMode === 'new' ? '' : ' tb-btn--muted'}`}
            onClick={() => setViewMode('new')}
            title="Only capacity commissioned in that period"
          >
            New additions
          </button>
        </div>
      </div>
      <InteractiveTimeSeriesCard
        title={`Capacity over investment periods — ${viewMode === 'cumulative' ? 'cumulative' : 'new additions'} (${groupMode === 'carrier' ? 'by carrier' : 'by generator'})`}
        description="MW"
        data={rows}
        series={series}
        mode="bar"
        stacked
      />
    </div>
  );
}
