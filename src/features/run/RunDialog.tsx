/**
 * RunDialog — floating modal for single-year run configuration.
 *
 * Extracted from App.tsx to keep the root component focused on state
 * and routing. All run options (snapshot window, resolution, carbon
 * price, dry-run toggle) live here; the parent owns the state values.
 */
import React, { useMemo } from 'react';
import { GridRow } from '../../shared/types';
import { DualRangeSlider } from './DualRangeSlider';

export interface RunDialogProps {
  open: boolean;
  onClose: () => void;

  maxSnapshots: number;
  snapshotStart: number;
  snapshotEnd: number;
  snapshotWeight: number;
  forceLp: boolean;
  dryRun: boolean;
  snapshots: GridRow[];
  dateFormat: string;

  onSnapshotStartChange: (v: number) => void;
  onSnapshotEndChange: (v: number) => void;
  onSnapshotWeightChange: (v: number) => void;
  onForceLpChange: (v: boolean) => void;
  onDryRunChange: (v: boolean) => void;

  onRun: () => void;
}

// ── Snapshot datetime helpers ─────────────────────────────────────────────────

function getRawSnapshotStr(index: number, snapshots: GridRow[]): string {
  const row = snapshots[index];
  if (!row) return '';
  const raw = String(row.snapshot ?? row.name ?? row.datetime ?? '').trim();
  return raw.toLowerCase() === 'now' ? '' : raw;
}

function parseDateWithFormat(raw: string, dateFormat: string): Date {
  // For dmy: rewrite "dd/mm/yyyy hh:mm" or "dd-mm-yyyy hh:mm" to ISO
  if (dateFormat === 'dmy') {
    // Match dd/mm/yyyy or dd-mm-yyyy optionally followed by time
    const m = raw.match(/^(\d{1,2})[\/\-](\d{1,2})[\/\-](\d{4})(.*)$/);
    if (m) return new Date(`${m[3]}-${m[2].padStart(2,'0')}-${m[1].padStart(2,'0')}${m[4]}`);
  }
  if (dateFormat === 'mdy') {
    // Match mm/dd/yyyy or mm-dd-yyyy optionally followed by time
    const m = raw.match(/^(\d{1,2})[\/\-](\d{1,2})[\/\-](\d{4})(.*)$/);
    if (m) return new Date(`${m[3]}-${m[1].padStart(2,'0')}-${m[2].padStart(2,'0')}${m[4]}`);
  }
  // auto / ymd: let the browser parse (works for ISO and most unambiguous formats)
  return new Date(raw);
}

function formatSnapLabel(index: number, snapshots: GridRow[], multiYear: boolean, dateFormat: string): string {
  const raw = getRawSnapshotStr(index, snapshots);
  if (!raw) return String(index);
  try {
    const d = parseDateWithFormat(raw, dateFormat);
    if (isNaN(d.getTime())) return raw;
    const mo = d.toLocaleString('en', { month: 'short' });
    const day = d.getDate();
    const hr = d.getHours().toString().padStart(2, '0') + ':00';
    return multiYear ? `${d.getFullYear()} ${mo} ${day}` : `${mo} ${day} ${hr}`;
  } catch {
    return raw;
  }
}

// ── RunDialog ─────────────────────────────────────────────────────────────────

export function RunDialog({
  open,
  onClose,
  maxSnapshots,
  snapshotStart,
  snapshotEnd,
  snapshotWeight,
  forceLp,
  dryRun,
  snapshots,
  dateFormat,
  onSnapshotStartChange,
  onSnapshotEndChange,
  onSnapshotWeightChange,
  onForceLpChange,
  onDryRunChange,
  onRun,
}: RunDialogProps) {
  // Detect whether snapshots have real datetimes and whether they span multiple years
  const { hasDatetimes, multiYear, yearMarkers } = useMemo(() => {
    if (!snapshots.length) return { hasDatetimes: false, multiYear: false, yearMarkers: [] };

    const firstRaw = getRawSnapshotStr(0, snapshots);
    if (!firstRaw) return { hasDatetimes: false, multiYear: false, yearMarkers: [] };
    const firstDate = parseDateWithFormat(firstRaw, dateFormat);
    if (isNaN(firstDate.getTime())) return { hasDatetimes: false, multiYear: false, yearMarkers: [] };

    // Compute year boundary markers across the full snapshot array
    const seen = new Set<number>();
    const markers: Array<{ year: number; pct: number }> = [];
    const total = snapshots.length;
    for (let i = 0; i < total; i++) {
      const raw = getRawSnapshotStr(i, snapshots);
      if (!raw) break;
      const d = parseDateWithFormat(raw, dateFormat);
      if (isNaN(d.getTime())) break;
      const yr = d.getFullYear();
      if (!seen.has(yr)) {
        seen.add(yr);
        markers.push({ year: yr, pct: total > 1 ? (i / (total - 1)) * 100 : 0 });
      }
    }

    return {
      hasDatetimes: true,
      multiYear: markers.length > 1,
      yearMarkers: markers.length > 1 ? markers : [],
    };
  }, [snapshots, dateFormat]);

  if (!open) return null;

  // snapshotEnd is exclusive (can equal snapshots.length); clamp to last valid row for label display.
  const lastIdx = Math.max(0, snapshots.length - 1);
  const startLabel = hasDatetimes ? formatSnapLabel(Math.min(snapshotStart, lastIdx), snapshots, multiYear, dateFormat) : null;
  const endLabel   = hasDatetimes ? formatSnapLabel(Math.min(snapshotEnd,   lastIdx), snapshots, multiYear, dateFormat) : null;

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-card" onClick={(e) => e.stopPropagation()}>
        <div className="panel-title-row">
          <div>
            <p className="eyebrow">Run</p>
            <h2>Run configuration</h2>
          </div>
        </div>

        {maxSnapshots <= 1 ? (
          <div className="run-static-notice">
            <strong>Static single-period model</strong>
            <p>The workbook defines 1 snapshot (<code>now</code>). This runs as a single dispatch period.</p>
          </div>
        ) : (
          <>
            <div className="field" style={{ marginBottom: yearMarkers.length ? 4 : 16 }}>
              <span style={{ color: 'var(--muted)', fontSize: '0.88rem' }}>
                Simulation window — <strong>{snapshotEnd - snapshotStart} hourly steps</strong>
                {' '}
                {hasDatetimes
                  ? <span>({startLabel} → {endLabel})</span>
                  : <span>(step {snapshotStart} → {snapshotEnd} of {maxSnapshots})</span>
                }
              </span>
              <DualRangeSlider
                min={0}
                max={maxSnapshots}
                low={snapshotStart}
                high={snapshotEnd}
                formatLabel={(v) => formatSnapLabel(v, snapshots, multiYear, dateFormat)}
                onChange={(lo, hi) => { onSnapshotStartChange(lo); onSnapshotEndChange(hi); }}
              />
              {yearMarkers.length > 0 && (
                <div className="snap-year-track">
                  {yearMarkers.map(({ year, pct }) => (
                    <span key={year} className="snap-year-chip" style={{ left: `${pct}%` }}>
                      {year}
                    </span>
                  ))}
                </div>
              )}
            </div>

            <div className="field" style={{ marginBottom: 8 }}>
              {(() => {
                const windowSize = snapshotEnd - snapshotStart;
                const modeledSnapshots = Math.ceil(windowSize / snapshotWeight);
                return (
                  <>
                    <span style={{ color: 'var(--muted)', fontSize: '0.88rem' }}>
                      Time resolution — <strong>every {snapshotWeight}h</strong>
                      {' '}({modeledSnapshots} snapshots of {windowSize} hourly steps)
                    </span>
                    <div style={{ display: 'flex', gap: 6, marginTop: 6, flexWrap: 'wrap' }}>
                      {[1, 2, 3, 4, 6, 8, 12, 24].map((n) => (
                        <button
                          key={n}
                          className={`tb-btn${snapshotWeight === n ? '' : ' tb-btn--muted'}`}
                          style={{ minWidth: 40 }}
                          onClick={() => onSnapshotWeightChange(n)}
                        >
                          {n}h
                        </button>
                      ))}
                    </div>
                  </>
                );
              })()}
            </div>

            <p className="status-text" style={{ marginBottom: 12 }}>
              Resolution selects every Nth step — <code>snapshots[::N]</code> with{' '}
              <code>snapshot_weightings = N</code>. Higher N = coarser resolution, faster solve.
            </p>
          </>
        )}

        {/* Force LP — override all committable=True generators to LP (faster) */}
        <label style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 12, marginBottom: 8, cursor: 'pointer' }}>
          <input
            type="checkbox"
            checked={forceLp}
            onChange={(e) => onForceLpChange(e.target.checked)}
            style={{ width: 16, height: 16, cursor: 'pointer' }}
          />
          <span style={{ fontSize: '0.9rem' }}>
            <strong>Force LP</strong> — ignore <code>committable</code> flags; solve as linear programme (faster)
          </span>
        </label>

        <label style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 16, cursor: 'pointer' }}>
          <input
            type="checkbox"
            checked={dryRun}
            onChange={(e) => onDryRunChange(e.target.checked)}
            style={{ width: 16, height: 16, cursor: 'pointer' }}
          />
          <span style={{ fontSize: '0.9rem' }}>
            <strong>Dry run</strong> — validate model structure without optimising
          </span>
        </label>

        <div className="modal-actions">
          <button className="secondary-button" onClick={onClose}>Cancel</button>
          <button className="run-button" onClick={onRun}>
            {dryRun ? 'Validate' : 'Run model'}
          </button>
        </div>
      </div>
    </div>
  );
}
