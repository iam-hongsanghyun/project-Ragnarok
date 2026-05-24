/**
 * CapacityByPeriodCard — for pathway runs, shows how active installed
 * capacity (MW) evolves across investment periods, stacked by carrier or
 * grouped by generator. Driven entirely off `(model, outputs)` so it
 * matches whatever data is currently cached — works on imported projects
 * too, with no backend call.
 *
 * Activity rule for a generator g in period P:
 *   active = build_year ≤ P < build_year + lifetime
 *   capacity = p_nom_opt if p_nom_extendable else p_nom
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

interface ActiveRow {
  name: string;
  carrier: string;
  capacity: number;
  isInvested: boolean;
}

function activeCapacityAt(row: GridRow, optStatic: Record<string, Record<string, unknown>>, period: number): ActiveRow | null {
  const name = stringValue(row.name);
  if (!name) return null;
  const buildYear = numberValue(row.build_year);
  const lifetime = numberValue(row.lifetime);
  if (buildYear > 0 && period < buildYear) return null;
  if (buildYear > 0 && lifetime > 0 && period >= buildYear + lifetime) return null;
  const extendable = row.p_nom_extendable === true ||
    String(row.p_nom_extendable ?? '').toLowerCase() === 'true';
  const fallback = numberValue(row.p_nom);
  const optAttrs = optStatic[name] ?? {};
  const opt = optAttrs.p_nom_opt;
  const capacity = extendable && opt !== undefined && opt !== null && opt !== ''
    ? Number(opt)
    : fallback;
  if (!Number.isFinite(capacity) || capacity <= 0) return null;
  return {
    name,
    carrier: stringValue(row.carrier) || 'Other',
    capacity,
    isInvested: extendable && capacity > fallback + 1e-6,
  };
}

export function CapacityByPeriodCard({ model, results }: Props) {
  const [mode, setMode] = useState<GroupMode>('carrier');
  const [investedOnly, setInvestedOnly] = useState(false);

  const periods = useMemo(() => results.pathway?.periods ?? [], [results.pathway]);
  const optStatic = useMemo(
    () => results.outputs?.static?.generators ?? {},
    [results.outputs],
  );

  const { rows, series } = useMemo(() => {
    if (!periods.length) return { rows: [], series: [] };
    const generators = model.generators ?? [];

    // For each period, gather active generators
    const perPeriod = periods.map((p) => {
      const active = generators
        .map((g) => activeCapacityAt(g, optStatic, p))
        .filter((x): x is ActiveRow => !!x)
        .filter((g) => !investedOnly || g.isInvested);
      return { period: p, active };
    });

    // Pivot to rows: one row per period, one column per key (carrier or generator)
    const keys = new Set<string>();
    const tableRows: TimeSeriesRow[] = perPeriod.map(({ period, active }) => {
      const row: TimeSeriesRow = { label: String(period), timestamp: String(period) };
      for (const g of active) {
        const key = mode === 'carrier' ? g.carrier : g.name;
        row[key] = (Number(row[key]) || 0) + g.capacity;
        keys.add(key);
      }
      return row;
    });

    const keyList = Array.from(keys);
    const seriesList = keyList.map((k) => {
      if (mode === 'carrier') {
        return { key: k, label: k, color: carrierColor(k) };
      }
      // For generator mode, colour by carrier of any matching generator
      const sample = generators.find((g) => stringValue(g.name) === k);
      const colour = sample
        ? resolvedColor(sample.color, sample.carrier)
        : hashColor(k);
      return { key: k, label: k, color: colour };
    });

    // Sort series by total descending so largest sits on the bottom of the stack
    const totals: Record<string, number> = {};
    for (const r of tableRows) for (const k of keyList) totals[k] = (totals[k] ?? 0) + (Number(r[k]) || 0);
    seriesList.sort((a, b) => (totals[b.key] ?? 0) - (totals[a.key] ?? 0));

    return { rows: tableRows, series: seriesList };
  }, [periods, model.generators, optStatic, mode, investedOnly]);

  if (!periods.length || rows.length === 0) {
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
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 12 }}>
        <div className="period-pill-row" role="group" aria-label="Group capacity by">
          <button
            className={`tb-btn period-pill${mode === 'carrier' ? '' : ' tb-btn--muted'}`}
            onClick={() => setMode('carrier')}
          >
            By carrier
          </button>
          <button
            className={`tb-btn period-pill${mode === 'generator' ? '' : ' tb-btn--muted'}`}
            onClick={() => setMode('generator')}
          >
            By generator
          </button>
        </div>
        <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: '0.85rem' }}>
          <input
            type="checkbox"
            checked={investedOnly}
            onChange={(e) => setInvestedOnly(e.target.checked)}
          />
          Show only newly-invested assets
        </label>
      </div>
      <InteractiveTimeSeriesCard
        title={`Installed capacity over investment periods (${mode === 'carrier' ? 'by carrier' : 'by generator'})`}
        description={investedOnly
          ? 'Only extendable generators whose optimal capacity exceeds the input p_nom (new investments).'
          : 'Active capacity per period: extendable assets use p_nom_opt, fixed assets use p_nom. Lifetime-bound entries drop out when build_year + lifetime ≤ period.'}
        data={rows}
        series={series}
        mode="area"
        stacked
      />
    </div>
  );
}
