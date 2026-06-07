import React from 'react';
import { BackendRunMeta } from 'lib/types';
import { formatRelTime } from 'lib/utils/formatRelTime';

interface RunComparisonTableProps {
  /** Backend-stored run metas selected for comparison. */
  runs: BackendRunMeta[];
  /** Name of the run currently shown in the viewer (highlighted column). */
  activeRunName: string | null;
  /** Remove a run from the client-side comparison selection (keeps it stored). */
  onRemoveFromComparison?: (name: string) => void;
}

/** Strip units/commas and return the first numeric token, or null. */
function parseNum(val: string): number | null {
  const m = val.replace(/,/g, '').match(/[-+]?[0-9]*\.?[0-9]+/);
  if (!m) return null;
  const n = parseFloat(m[0]);
  return isNaN(n) ? null : n;
}

/** Compute relative delta of `target` vs `base` as a labelled object. */
function delta(base: number, target: number): { text: string; dir: 'up' | 'down' | 'same' } {
  if (Math.abs(base) < 0.001) return { text: '—', dir: 'same' };
  const pct = ((target - base) / Math.abs(base)) * 100;
  if (Math.abs(pct) < 0.05) return { text: '±0%', dir: 'same' };
  return { text: `${pct > 0 ? '+' : ''}${pct.toFixed(1)}%`, dir: pct > 0 ? 'up' : 'down' };
}

export function RunComparisonTable({ runs, activeRunName, onRemoveFromComparison }: RunComparisonTableProps) {
  if (runs.length < 2) return null;

  // Newest run first
  const sorted = [...runs].sort(
    (a, b) => new Date(b.savedAt).getTime() - new Date(a.savedAt).getTime(),
  );
  const activeIdx = sorted.findIndex((e) => e.name === activeRunName);

  const summaryLabels = (sorted[0].summary ?? []).map((s) => s.label);

  const snapWindow = (e: BackendRunMeta): string =>
    e.snapshotStart != null && e.snapshotEnd != null ? `${e.snapshotStart} → ${e.snapshotEnd}` : '—';

  const settingRows: Array<{ label: string; fn: (e: BackendRunMeta) => string }> = [
    { label: 'Scenario', fn: (e) => e.scenarioLabel ?? '—' },
    { label: 'Planning mode', fn: (e) => e.pathway?.enabled ? 'Pathway' : 'Single period' },
    { label: 'Rolling horizon', fn: (e) => e.rolling?.enabled ? 'On' : 'Off' },
    { label: 'Rolling horizon size', fn: (e) => e.rolling?.enabled ? String(e.rolling.horizonSnapshots ?? 0) : '—' },
    { label: 'Rolling overlap', fn: (e) => e.rolling?.enabled ? String(e.rolling.overlapSnapshots ?? 0) : '—' },
    { label: 'Rolling windows', fn: (e) => e.rolling?.enabled ? String(e.rolling.windowCount ?? 0) : '—' },
    { label: 'Periods',       fn: (e) => e.pathway?.enabled ? (e.pathway.periods ?? []).join(', ') : '—' },
    { label: 'Active period', fn: (e) => e.pathway?.selectedPeriod != null ? String(e.pathway.selectedPeriod) : '—' },
    { label: 'Window',        fn: (e) => snapWindow(e) },
    { label: 'Resolution',    fn: (e) => e.snapshotWeight != null ? `${e.snapshotWeight} h` : '—' },
    { label: 'Generators',    fn: (e) => String(e.componentCounts.generators ?? 0) },
    { label: 'Storage units', fn: (e) => String(e.componentCounts.storage_units ?? 0) },
  ];

  return (
    <div className="cmp-table-wrap">
      <table className="cmp-table">
        <thead>
          <tr>
            <th style={{ width: 160 }} />
            {sorted.map((entry, i) => (
              <th
                key={entry.name}
                className={`cmp-th${i === activeIdx ? ' cmp-col--active' : ''}`}
              >
                <div className="cmp-th-top">
                  <div className="cmp-th-label">{entry.label}</div>
                  {onRemoveFromComparison && (
                    <button
                      className="cmp-col-remove"
                      title="Remove from comparison (keeps run stored)"
                      onClick={() => onRemoveFromComparison(entry.name)}
                    >
                      x
                    </button>
                  )}
                </div>
                <div className="cmp-th-meta">
                  {formatRelTime(entry.savedAt)}
                  {i === activeIdx && <span className="cmp-active-badge">active</span>}
                </div>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {/* ── Settings ── */}
          <tr className="cmp-section-header">
            <td colSpan={sorted.length + 1}>Settings</td>
          </tr>
          {settingRows.map((row) => (
            <tr key={row.label}>
              <td className="cmp-row-label">{row.label}</td>
              {sorted.map((entry, i) => (
                <td key={entry.name} className={i === activeIdx ? 'cmp-col--active' : ''}>
                  {row.fn(entry)}
                </td>
              ))}
            </tr>
          ))}

          {/* ── Results ── */}
          <tr className="cmp-section-header">
            <td colSpan={sorted.length + 1}>Results</td>
          </tr>
          {summaryLabels.map((label, si) => {
            const vals = sorted.map((e) => e.summary?.[si]?.value ?? '—');
            const nums = vals.map(parseNum);
            const activeNum = activeIdx >= 0 ? nums[activeIdx] : null;

            return (
              <tr key={label}>
                <td className="cmp-row-label">{label}</td>
                {sorted.map((entry, i) => {
                  const isActive = i === activeIdx;
                  const n = nums[i];

                  // Delta tag for non-active columns
                  let deltaTag: React.ReactNode = null;
                  if (!isActive && n !== null && activeNum !== null) {
                    const d = delta(activeNum, n);
                    if (d.dir !== 'same') {
                      deltaTag = (
                        <span className={`cmp-delta cmp-delta--${d.dir}`}>{d.text}</span>
                      );
                    }
                  }

                  return (
                    <td key={entry.name} className={isActive ? 'cmp-col--active' : ''}>
                      <div className="cmp-cell-main">{vals[i]}</div>
                      {deltaTag}
                    </td>
                  );
                })}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
