import React, { useMemo, useState } from 'react';
import { BackendRunMeta } from 'lib/types';
import { RunComparisonTable } from '../run-history/RunComparisonTable';
import { ScenarioPivotCard } from './cards/ScenarioPivotCard';

// ── Mini horizontal-bar chart ─────────────────────────────────────────────────

interface BarEntry { id: string; label: string; value: number; active: boolean }

function MiniBarChart({ title, unit, entries }: { title: string; unit: string; entries: BarEntry[] }) {
  const maxAbs = Math.max(...entries.map((e) => Math.abs(e.value)), 0.001);
  return (
    <div className="cmp-bar-chart">
      <div className="cmp-bar-chart-title">{title}</div>
      {entries.map((e) => (
        <div key={e.id} className="cmp-bar-row">
          <div className="cmp-bar-label" title={e.label}>{e.label}</div>
          <div className="cmp-bar-track">
            <div
              className={`cmp-bar-fill${e.active ? ' cmp-bar-fill--active' : ''}`}
              style={{ width: `${(Math.abs(e.value) / maxAbs) * 100}%` }}
            />
          </div>
          <div className="cmp-bar-value">
            {e.value.toLocaleString(undefined, { maximumFractionDigits: 1 })}{unit}
          </div>
        </div>
      ))}
    </div>
  );
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function firstNumericSummary(entry: BackendRunMeta, predicate: (label: string) => boolean): number {
  const s = (entry.summary ?? []).find((x) => predicate(x.label));
  if (!s) return 0;
  const m = s.value.replace(/,/g, '').match(/[-+]?[0-9]*\.?[0-9]+/);
  const n = m ? parseFloat(m[0]) : NaN;
  return isNaN(n) ? 0 : n;
}

// ── Comparison pane ───────────────────────────────────────────────────────────

interface Props {
  /** Every backend-stored run meta (the single source of truth for history). */
  backendRuns: BackendRunMeta[];
  /** Name of the run currently shown in the viewer (highlighted as "active"). */
  activeRunName: string | null;
  currencySymbol?: string;
}

export function ComparisonPane({ backendRuns, activeRunName, currencySymbol = '$' }: Props) {
  // Client-side "included in comparison" selection: a set of run names. Default
  // is include-all; the user can drop a column to exclude it from the view
  // (the run stays stored). Runs that disappear from `backendRuns` (deleted)
  // are naturally ignored since we intersect against the live list below.
  const [excluded, setExcluded] = useState<Set<string>>(() => new Set());

  const included = useMemo(
    () => backendRuns.filter((m) => !excluded.has(m.name)),
    [backendRuns, excluded],
  );

  const removeFromComparison = (name: string) =>
    setExcluded((prev) => {
      const next = new Set(prev);
      next.add(name);
      return next;
    });

  if (included.length < 2) {
    return (
      <div className="analytics-empty">
        <h3>No runs to compare yet</h3>
        <p>
          Run the model at least twice. Every run is stored automatically and
          appears here — remove a column to drop it from the comparison (the run
          stays in History).
        </p>
      </div>
    );
  }

  // ── KPI bar data ────────────────────────────────────────────────────────────

  const dispatchEntries: BarEntry[] = included.map((e) => ({
    id: e.name,
    label: e.label,
    value: (e.carrierMix ?? []).reduce((s, m) => s + m.value, 0) / 1000,
    active: e.name === activeRunName,
  }));

  const emissionsEntries: BarEntry[] = included.map((e) => ({
    id: e.name,
    label: e.label,
    value: firstNumericSummary(e, (l) => l.toLowerCase().includes('emission')),
    active: e.name === activeRunName,
  }));

  const priceEntries: BarEntry[] = included.map((e) => ({
    id: e.name,
    label: e.label,
    value: firstNumericSummary(e, (l) => l.toLowerCase().includes('price')),
    active: e.name === activeRunName,
  }));

  const showKpiCharts = included.some((e) => (e.carrierMix ?? []).length > 0);
  const pathwayRuns = included.filter((e) => e.pathway?.enabled && (e.pathway.summaries?.length ?? 0) > 0);
  const hasPathwayComparison = pathwayRuns.length > 0;

  return (
    <div className="results-dashboard">

      {/* ── Cross-scenario pivot ──────────────────────────────────────────── */}
      <ScenarioPivotCard
        runs={included}
        activeRunName={activeRunName}
        currencySymbol={currencySymbol}
      />

      {/* ── KPI bar charts ────────────────────────────────────────────────── */}
      {showKpiCharts && (
        <div className="cmp-bar-strip">
          <MiniBarChart title="Total dispatch" unit=" GWh" entries={dispatchEntries} />
          <MiniBarChart title="Emissions" unit="" entries={emissionsEntries} />
          <MiniBarChart title="Avg system price" unit="" entries={priceEntries} />
        </div>
      )}

      {/* ── Comparison table ──────────────────────────────────────────────── */}
      <RunComparisonTable
        runs={included}
        activeRunName={activeRunName}
        onRemoveFromComparison={removeFromComparison}
      />

      {hasPathwayComparison && (
        <div className="cmp-table-wrap" style={{ marginTop: 20 }}>
          <table className="cmp-table">
            <thead>
              <tr>
                <th>Run</th>
                <th>Period</th>
                <th>Hours</th>
                <th>Dispatch</th>
                <th>Peak load</th>
                <th>Avg price</th>
                <th>Emissions</th>
              </tr>
            </thead>
            <tbody>
              {pathwayRuns.flatMap((entry) =>
                (entry.pathway?.summaries ?? []).map((row) => (
                  <tr key={`${entry.name}-${row.period}`}>
                    <td className={entry.name === activeRunName ? 'cmp-col--active' : ''}>{entry.label}</td>
                    <td>{row.period}</td>
                    <td>{row.modeledHours.toLocaleString(undefined, { maximumFractionDigits: 1 })}</td>
                    <td>{(row.totalDispatch / 1000).toLocaleString(undefined, { maximumFractionDigits: 1 })} GWh</td>
                    <td>{row.peakLoad.toLocaleString(undefined, { maximumFractionDigits: 0 })} MW</td>
                    <td>{row.averagePrice.toLocaleString(undefined, { maximumFractionDigits: 1 })} {currencySymbol}/MWh</td>
                    <td>{row.totalEmissions.toLocaleString(undefined, { maximumFractionDigits: 0 })} t</td>
                  </tr>
                )),
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
