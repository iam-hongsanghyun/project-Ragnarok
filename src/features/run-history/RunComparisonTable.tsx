import React from 'react';
import { RunHistoryEntry, RunResults } from '../../shared/types';
import { formatRelTime } from '../../shared/utils/formatRelTime';

interface RunComparisonTableProps {
  runHistory: RunHistoryEntry[];
  activeResults: RunResults;
  onToggleComparison?: (id: string, inComparison: boolean) => void;
  currencySymbol?: string;
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

export function RunComparisonTable({ runHistory, activeResults, onToggleComparison, currencySymbol = '$' }: RunComparisonTableProps) {
  if (runHistory.length < 2) return null;

  // Newest run first
  const sorted = [...runHistory].sort(
    (a, b) => new Date(b.savedAt).getTime() - new Date(a.savedAt).getTime(),
  );
  const activeIdx = sorted.findIndex((e) => e.results === activeResults);

  const summaryLabels = sorted[0].results.summary.map((s) => s.label);

  const settingRows: Array<{ label: string; fn: (e: RunHistoryEntry) => string }> = [
    { label: 'Planning mode', fn: (e) => e.results.pathway?.enabled ? 'Pathway' : 'Single period' },
    { label: 'Rolling horizon', fn: (e) => e.results.rolling?.enabled ? 'On' : 'Off' },
    { label: 'Rolling horizon size', fn: (e) => e.results.rolling?.enabled ? String(e.results.rolling.horizonSnapshots) : '—' },
    { label: 'Rolling overlap', fn: (e) => e.results.rolling?.enabled ? String(e.results.rolling.overlapSnapshots) : '—' },
    { label: 'Rolling windows', fn: (e) => e.results.rolling?.enabled ? String(e.results.rolling.windowCount) : '—' },
    { label: 'Periods',       fn: (e) => e.results.pathway?.enabled ? e.results.pathway.periods.join(', ') : '—' },
    { label: 'Active period', fn: (e) => e.results.pathway?.selectedPeriod != null ? String(e.results.pathway.selectedPeriod) : '—' },
    { label: 'Carbon price',  fn: (e) => e.carbonPrice > 0 ? `${currencySymbol}${e.carbonPrice}/t` : '—' },
    { label: 'Window',        fn: (e) => `${e.snapshotStart} → ${e.snapshotEnd}` },
    { label: 'Resolution',    fn: (e) => `${e.snapshotWeight} h` },
    { label: 'Generators',    fn: (e) => String(e.componentCounts.generators ?? 0) },
    { label: 'Storage units', fn: (e) => String(e.componentCounts.storage_units ?? 0) },
    { label: 'Constraints',   fn: (e) => e.activeConstraints.length > 0
        ? e.activeConstraints.map((c) => c.label).join(', ')
        : '—' },
  ];

  return (
    <div className="cmp-table-wrap">
      <table className="cmp-table">
        <thead>
          <tr>
            <th style={{ width: 160 }} />
            {sorted.map((entry, i) => (
              <th
                key={entry.id}
                className={`cmp-th${i === activeIdx ? ' cmp-col--active' : ''}`}
              >
                <div className="cmp-th-top">
                  <div className="cmp-th-label">{entry.label}</div>
                  {onToggleComparison && (
                    <button
                      className="cmp-col-remove"
                      title="Remove from comparison (keeps run in history)"
                      onClick={() => onToggleComparison(entry.id, false)}
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
                <td key={entry.id} className={i === activeIdx ? 'cmp-col--active' : ''}>
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
            const vals = sorted.map((e) => e.results.summary[si]?.value ?? '—');
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
                    <td key={entry.id} className={isActive ? 'cmp-col--active' : ''}>
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
