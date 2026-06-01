/**
 * Forge — data-handling workspace.
 *
 * Bulk operations that shape the imported model into solver-ready form,
 * sitting between Data (import) and Build/Model (edit):
 *
 *   1. Round / Ceil / Floor selected numeric attributes.
 *   2. Snap components to their nearest bus by great-circle distance,
 *      within a km buffer (sets bus / bus0 / bus1).
 *
 * The view is presentation + orchestration only; the numeric and spatial
 * logic lives in `lib/forge/*` so it is unit-tested independently.
 */
import React, { useMemo, useState } from 'react';
import type { GridRow, WorkbookModel } from 'lib/types';
import { usePersistedState } from 'shared/hooks/usePersistedState';
import { FORGE_CONFIG, VALIDATION_CONFIG } from 'lib/constants';
import { LeftRail, ViewPanel } from 'shared/components/primitives';
import { applyRounding, numericColumns, type RoundOp } from 'lib/forge/transforms';
import {
  buildTargets,
  sheetSnappable,
  snapSheet,
  type OutsideEntry,
  type SnapResult,
} from 'lib/forge/snap';
import { nonEmptySheets, roundFindings, snapFindings, type ForgeFinding } from 'lib/forge/validate';

interface Props {
  model: WorkbookModel;
  /** Merge transformed sheets back into the model (keeps everything else). */
  onApplySheets: (partial: Record<string, GridRow[]>) => void;
}

type Operation = 'round' | 'snap';
type OpGroup = 'Numeric' | 'Geospatial';

/** Catalog of Forge tools, grouped. Add a new tool by adding an entry here
 *  (and its panel + findings wiring) — the rail renders groups from this. */
const OPERATIONS: Array<{ id: Operation; label: string; group: OpGroup }> = [
  { id: 'round', label: 'Round / Ceil / Floor', group: 'Numeric' },
  { id: 'snap', label: 'Snap to nearest bus', group: 'Geospatial' },
];
const OP_GROUPS: OpGroup[] = ['Numeric', 'Geospatial'];

const ROUND_OPS: Array<{ value: RoundOp; label: string }> = [
  { value: 'round', label: 'Round' },
  { value: 'ceil', label: 'Ceiling' },
  { value: 'floor', label: 'Floor' },
];

const rowsOf = (model: WorkbookModel, sheet: string): GridRow[] => model[sheet] ?? [];

export function ForgeView({ model, onApplySheets }: Props) {
  // Persisted so the chosen tool + validation result survive leaving and
  // returning to the Forge tab (the view unmounts on tab switch). The findings
  // scan the whole model, so these three drivers fully restore the result.
  const [operation, setOperation] = usePersistedState<Operation>('ui:forge-operation', 'round');
  const [validated, setValidated] = usePersistedState<boolean>('ui:forge-validated', false);
  const [status, setStatus] = useState<string | null>(null);

  // Read any model that holds rows, regardless of how it was loaded (project
  // import, plugin "Send model", build editor, …) — not just a fixed sheet list.
  const sheetsWithRows = useMemo(() => nonEmptySheets(model), [model]);

  // ── Operation 1: Round / Ceil / Floor ──────────────────────────────────
  const [roundSheet, setRoundSheet] = useState<string>('');
  const [roundAttrs, setRoundAttrs] = useState<string[]>([]);
  const [roundOp, setRoundOp] = useState<RoundOp>('round');
  const [decimals, setDecimals] = usePersistedState<number>('ui:forge-decimals', FORGE_CONFIG.defaultRoundDecimals);

  const activeRoundSheet = roundSheet && sheetsWithRows.includes(roundSheet) ? roundSheet : (sheetsWithRows[0] ?? '');
  const roundCols = useMemo(
    () => numericColumns(rowsOf(model, activeRoundSheet)),
    [model, activeRoundSheet],
  );
  const selectedRoundAttrs = roundAttrs.filter((a) => roundCols.includes(a));
  const roundPreview = useMemo(() => {
    if (!activeRoundSheet || selectedRoundAttrs.length === 0) return 0;
    return applyRounding(rowsOf(model, activeRoundSheet), selectedRoundAttrs, roundOp, decimals).changed;
  }, [model, activeRoundSheet, selectedRoundAttrs, roundOp, decimals]);

  const toggleRoundAttr = (col: string) =>
    setRoundAttrs((prev) => (prev.includes(col) ? prev.filter((c) => c !== col) : [...prev, col]));

  const applyRound = () => {
    const { rows, changed } = applyRounding(rowsOf(model, activeRoundSheet), selectedRoundAttrs, roundOp, decimals);
    onApplySheets({ [activeRoundSheet]: rows });
    const opLabel = ROUND_OPS.find((o) => o.value === roundOp)?.label ?? roundOp;
    setStatus(`${opLabel}: changed ${changed} cell${changed === 1 ? '' : 's'} across ${selectedRoundAttrs.length} attribute${selectedRoundAttrs.length === 1 ? '' : 's'} in ${activeRoundSheet}.`);
  };

  // ── Operation 2: Snap to nearest bus ────────────────────────────────────
  const [overlaySel, setOverlaySel] = useState<string[]>([]);
  const [bufferKm, setBufferKm] = useState<number>(FORGE_CONFIG.defaultBufferKm);
  const [snapReport, setSnapReport] = useState<
    { assigned: number; outside: OutsideEntry[]; noCoords: number; perSheet: Array<{ sheet: string; anchors: string[]; assigned: number }> } | null
  >(null);

  const targets = useMemo(() => buildTargets(rowsOf(model, 'buses')), [model]);
  const overlayCandidates = useMemo(
    () => sheetsWithRows.filter((sheet) => sheet !== 'buses' && sheetSnappable(rowsOf(model, sheet))),
    [model, sheetsWithRows],
  );
  const selectedOverlays = overlaySel.filter((s) => overlayCandidates.includes(s));

  const toggleOverlay = (sheet: string) =>
    setOverlaySel((prev) => (prev.includes(sheet) ? prev.filter((s) => s !== sheet) : [...prev, sheet]));

  const applySnap = () => {
    const partial: Record<string, GridRow[]> = {};
    const outside: OutsideEntry[] = [];
    const perSheet: Array<{ sheet: string; anchors: string[]; assigned: number }> = [];
    let assigned = 0;
    let noCoords = 0;
    for (const sheet of selectedOverlays) {
      const result: SnapResult = snapSheet(rowsOf(model, sheet), targets, bufferKm);
      partial[sheet] = result.rows;
      assigned += result.assigned;
      noCoords += result.noCoords;
      outside.push(...result.outside.map((o) => ({ ...o, name: `${sheet}: ${o.name}` })));
      perSheet.push({ sheet, anchors: result.anchors, assigned: result.assigned });
    }
    onApplySheets(partial);
    setSnapReport({ assigned, outside, noCoords, perSheet });
    setStatus(`Snapped ${assigned} connection${assigned === 1 ? '' : 's'} to nearest bus${outside.length ? `, ${outside.length} beyond ${bufferKm} km` : ''}.`);
  };

  // Context-aware "what needs handling" for the active tool. Recomputes when
  // the tool or model changes, so switching tools re-reports automatically.
  const findings = useMemo<ForgeFinding[] | null>(() => {
    if (!validated) return null;
    return operation === 'round'
      ? roundFindings(model, decimals, VALIDATION_CONFIG.magnitudeMax, VALIDATION_CONFIG.magnitudeMin)
      : snapFindings(model);
  }, [validated, operation, model, decimals]);

  const activeOpLabel = OPERATIONS.find((op) => op.id === operation)?.label ?? operation;

  return (
    <ViewPanel name="forge">
      <LeftRail title="Forge">
        <button
          type="button"
          className="tb-btn forge-validate-btn"
          aria-pressed={validated}
          onClick={() => setValidated(!validated)}
        >
          {validated ? 'Validation on' : 'Validate'}
        </button>
        <div className="forge-rail-divider" />
        {OP_GROUPS.map((group) => (
          <div key={group} className="forge-group">
            <div className="forge-group-title">{group}</div>
            {OPERATIONS.filter((op) => op.group === group).map((op) => (
              <button
                key={op.id}
                className={`settings-nav-item${operation === op.id ? ' settings-nav-item--active' : ''}`}
                onClick={() => setOperation(op.id)}
              >
                {op.label}
              </button>
            ))}
          </div>
        ))}
      </LeftRail>

      <main className="view-main forge-main">
        {sheetsWithRows.length > 0 && findings && (
          <div className="forge-findings">
            <p className="forge-findings-title">
              {activeOpLabel} —{' '}
              {findings.length === 0
                ? 'nothing needs handling for this tool'
                : `${findings.length} item${findings.length === 1 ? '' : 's'} need attention`}
            </p>
            {findings.length > 0 && (
              <ul className="forge-findings-list">
                {findings.map((f, i) => (
                  <li key={i}><b>{f.sheet}</b> — {f.message}</li>
                ))}
              </ul>
            )}
          </div>
        )}
        {sheetsWithRows.length === 0 ? (
          <div className="view-empty">
            <p>No model loaded. Import data first, then return to Forge to clean it up.</p>
          </div>
        ) : operation === 'round' ? (
          <section className="forge-section">
            <header className="forge-section-header">
              <h3>Round / Ceiling / Floor</h3>
              <p>Apply a rounding operation to selected numeric attributes. Empty and non-numeric cells are left untouched.</p>
            </header>

            <div className="sg-setting-row">
              <label className="sg-setting-label">Sheet</label>
              <select
                className="forge-select"
                value={activeRoundSheet}
                onChange={(e) => { setRoundSheet(e.target.value); setRoundAttrs([]); }}
              >
                {sheetsWithRows.map((sheet) => (
                  <option key={sheet} value={sheet}>{sheet} ({rowsOf(model, sheet).length})</option>
                ))}
              </select>
            </div>

            <div className="sg-setting-row">
              <label className="sg-setting-label">Attributes</label>
              {roundCols.length === 0 ? (
                <p className="sg-setting-hint">No numeric attributes in this sheet.</p>
              ) : (
                <div className="forge-checklist">
                  {roundCols.map((col) => (
                    <label key={col} className="forge-check">
                      <input
                        type="checkbox"
                        checked={selectedRoundAttrs.includes(col)}
                        onChange={() => toggleRoundAttr(col)}
                      />
                      {col}
                    </label>
                  ))}
                </div>
              )}
            </div>

            <div className="sg-setting-row">
              <label className="sg-setting-label">Operation</label>
              <div className="sg-btn-row">
                {ROUND_OPS.map(({ value, label }) => (
                  <button
                    key={value}
                    className={`tb-btn sg-solver-btn${roundOp === value ? '' : ' tb-btn--muted'}`}
                    onClick={() => setRoundOp(value)}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>

            <div className="sg-setting-row">
              <label className="sg-setting-label">Decimals</label>
              <input
                type="number"
                className="forge-number"
                min={0}
                max={12}
                value={decimals}
                onChange={(e) => setDecimals(Math.max(0, Math.trunc(Number(e.target.value) || 0)))}
              />
              <p className="sg-setting-hint">0 = whole numbers. Applies to all three operations.</p>
            </div>

            <div className="forge-actions">
              <button
                className="run-button"
                disabled={selectedRoundAttrs.length === 0}
                onClick={applyRound}
              >
                Apply
              </button>
              <span className="sg-setting-hint">
                {selectedRoundAttrs.length === 0
                  ? 'Select at least one attribute.'
                  : `${roundPreview} cell${roundPreview === 1 ? '' : 's'} will change.`}
              </span>
            </div>
          </section>
        ) : (
          <section className="forge-section">
            <header className="forge-section-header">
              <h3>Snap to nearest bus</h3>
              <p>Connect each selected component to the nearest bus by great-circle distance. Sets <code>bus</code> (point components) or <code>bus0</code>/<code>bus1</code> (branch endpoints). Components beyond the buffer are left unchanged and reported.</p>
            </header>

            <div className="sg-setting-row">
              <label className="sg-setting-label">Target</label>
              <p className="sg-setting-hint">
                buses — <b>{targets.length}</b> of {rowsOf(model, 'buses').length} have coordinates.
                {targets.length === 0 && ' No buses carry x/y, so there is nothing to snap to.'}
              </p>
            </div>

            <div className="sg-setting-row">
              <label className="sg-setting-label">Connect</label>
              {overlayCandidates.length === 0 ? (
                <p className="sg-setting-hint">No other components carry coordinates (x/y, x0/y0, x1/y1) to snap.</p>
              ) : (
                <div className="forge-checklist">
                  {overlayCandidates.map((sheet) => (
                    <label key={sheet} className="forge-check">
                      <input
                        type="checkbox"
                        checked={selectedOverlays.includes(sheet)}
                        onChange={() => toggleOverlay(sheet)}
                      />
                      {sheet} ({rowsOf(model, sheet).length})
                    </label>
                  ))}
                </div>
              )}
            </div>

            <div className="sg-setting-row">
              <label className="sg-setting-label">Buffer (km)</label>
              <input
                type="number"
                className="forge-number"
                min={0}
                value={bufferKm}
                onChange={(e) => setBufferKm(Math.max(0, Number(e.target.value) || 0))}
              />
              <p className="sg-setting-hint">A component whose nearest bus is farther than this is left unchanged and warned.</p>
            </div>

            <div className="forge-actions">
              <button
                className="run-button"
                disabled={selectedOverlays.length === 0 || targets.length === 0}
                onClick={applySnap}
              >
                Connect to nearest
              </button>
            </div>

            {snapReport && (
              <div className="forge-report">
                <p className="forge-report-line">
                  Connected <b>{snapReport.assigned}</b>
                  {snapReport.outside.length > 0 && <> · <span className="forge-warn">{snapReport.outside.length} beyond buffer</span></>}
                  {snapReport.noCoords > 0 && <> · {snapReport.noCoords} without coordinates</>}
                </p>
                {snapReport.outside.length > 0 && (
                  <ul className="forge-outside">
                    {snapReport.outside.slice(0, 30).map((o, i) => (
                      <li key={i}>
                        {o.name} → nearest <b>{o.nearest}</b> ({o.field}) is {o.km.toFixed(1)} km away
                      </li>
                    ))}
                    {snapReport.outside.length > 30 && <li>… and {snapReport.outside.length - 30} more</li>}
                  </ul>
                )}
              </div>
            )}
          </section>
        )}

        {status && <p className="forge-status">{status}</p>}
      </main>
    </ViewPanel>
  );
}
