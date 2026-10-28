/**
 * Time-units editor (Build -> Generators / Links / Processes), a drawer opened from the step's "Time units" button.
 *
 * PyPSA counts SNAPSHOTS in its ramp limits (`ramp_limit_up`, ... a fraction of p_nom per snapshot) and unit-commitment
 * times (`min_up_time`, ... a number of snapshots), so a value typed in those columns is right for one snapshot length
 * only. The `RAGNAROK_TimeUnits` sheet keeps the value in time units (per hour / per minute, hours / minutes); the server
 * converts it at solve time with the weights the run uses. This panel edits that sheet (visible in the Model tab like any
 * other) and shows the server's converted per-snapshot table. It converts nothing itself: the vocabulary (components,
 * attributes, units) and every converted number come from the API.
 */
import React, { useEffect, useMemo, useState } from 'react';
import type { GridRow, Primitive, SheetName, WorkbookModel } from 'lib/types';
import {
  TIME_UNITS_SHEET, getTimeUnits, previewTimeUnits,
  type TimeUnitPreviewRow, type TimeUnitsVocabulary,
} from 'lib/api/timeUnits';

export interface TimeUnitsPanelProps {
  model: WorkbookModel;
  /** The component sheet of the active Build step (`generators`, `links` or `processes`). */
  sheet: string;
  onUpdateRow: (sheet: SheetName, rowIndex: number, col: string, val: Primitive) => void;
  onDeleteRow: (sheet: SheetName, rowIndex: number) => void;
  onBulkPaste: (sheet: SheetName, edits: { rowIndex: number; col: string; val: Primitive }[], extraRows: number) => void;
  /** Push the working model to the session (the preview reads the session). */
  onSessionSync: () => Promise<void>;
  onClose: () => void;
}

const text = (v: Primitive | undefined): string => (v === null || v === undefined ? '' : String(v));

export function TimeUnitsPanel({ model, sheet, onUpdateRow, onDeleteRow, onBulkPaste, onSessionSync, onClose }: TimeUnitsPanelProps) {
  const [vocab, setVocab] = useState<TimeUnitsVocabulary | null>(null);
  const [vocabError, setVocabError] = useState<string | null>(null);
  const [preview, setPreview] = useState<TimeUnitPreviewRow[] | null>(null);
  const [stepHours, setStepHours] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState<{ name: string; attribute: string; value: string; unit: string }>({
    name: '', attribute: '', value: '', unit: '',
  });

  useEffect(() => {
    getTimeUnits().then(setVocab).catch((e: Error) => setVocabError(e.message));
  }, []);

  const sheetRows = model[TIME_UNITS_SHEET];
  const allRows: GridRow[] = useMemo(() => sheetRows ?? [], [sheetRows]);
  // Keep the sheet index of each row: edits address the sheet, not the filtered list.
  const rows = useMemo(
    () => allRows.map((row, index) => ({ row, index })).filter(({ row }) => text(row.component) === sheet),
    [allRows, sheet],
  );
  const names = useMemo(
    () => (model[sheet] ?? []).map((r) => text(r.name)).filter(Boolean),
    [model, sheet],
  );
  // The server's table is stale as soon as a row changes.
  useEffect(() => { setPreview(null); }, [allRows]);

  const attributes = vocab ? [...vocab.attributes.ramps, ...vocab.attributes.times] : [];
  const unitsFor = (attribute: string): string[] =>
    !vocab ? [] : vocab.attributes.ramps.includes(attribute) ? vocab.units.ramps : vocab.units.times;
  const dimension = (attribute: string): string =>
    vocab?.attributes.ramps.includes(attribute) ? 'fraction of p_nom per time unit' : 'duration';

  const draftAttribute = draft.attribute || attributes[0] || '';
  const draftUnit = unitsFor(draftAttribute).includes(draft.unit) ? draft.unit : unitsFor(draftAttribute)[0] ?? '';
  const draftName = draft.name || names[0] || '';
  const draftValue = Number(draft.value);
  const draftValid = draft.value.trim() !== '' && Number.isFinite(draftValue) && draftValue >= 0 && !!draftName && !!draftAttribute;
  const duplicate = rows.some(({ row }) => text(row.name) === draftName && text(row.attribute) === draftAttribute);

  const addRow = () => {
    if (!draftValid || duplicate) return;
    const index = allRows.length;
    onBulkPaste(TIME_UNITS_SHEET, [
      { rowIndex: index, col: 'component', val: sheet },
      { rowIndex: index, col: 'name', val: draftName },
      { rowIndex: index, col: 'attribute', val: draftAttribute },
      { rowIndex: index, col: 'value', val: draftValue },
      { rowIndex: index, col: 'unit', val: draftUnit },
    ], 1);
    setDraft({ ...draft, value: '' });
  };

  const runPreview = async () => {
    setBusy(true);
    setError(null);
    try {
      await onSessionSync();
      const out = await previewTimeUnits();
      setPreview(out.table.filter((r) => r.component === sheet));
      setStepHours(out.stepHours);
    } catch (e) {
      setPreview(null);
      setError(e instanceof Error ? e.message : 'Preview failed');
    } finally {
      setBusy(false);
    }
  };

  const previewFor = (row: GridRow): TimeUnitPreviewRow | undefined =>
    preview?.find((p) => p.name === text(row.name) && p.attribute === text(row.attribute));

  return (
    <aside className="time-units-drawer" data-tour="time-units" aria-label="Time units">
      <div className="time-units-drawer__head">
        <span className="eyebrow">Time units — ramps and minimum times ({sheet})</span>
        <button type="button" className="tb-btn" onClick={onClose}>Close</button>
      </div>
      <div className="time-units">
        <p className="sg-setting-hint">
          PyPSA's ramp limits are a fraction of p_nom per <b>snapshot</b> and its minimum up / down times a number of
          <b> snapshots</b>. State them here in hours or per hour; the run converts them with the weights it uses
          (ramp = min(1, rate × step), times = ceil(hours / step)). A row replaces the value typed in the component column.
        </p>
        {vocabError && <p className="sg-setting-hint" role="alert">{vocabError}</p>}
        {!vocab && !vocabError && <p className="sg-setting-hint">Loading…</p>}
        {vocab && (
          <>
            {rows.length > 0 && (
              <table className="sg-table time-units__table">
                <thead>
                  <tr><th>Name</th><th>Attribute</th><th>Value</th><th>Unit</th><th>Step (h)</th><th>PyPSA per snapshot</th><th /></tr>
                </thead>
                <tbody>
                  {rows.map(({ row, index }) => {
                    const attribute = text(row.attribute);
                    const converted = previewFor(row);
                    return (
                      <tr key={index}>
                        <td>{text(row.name)}</td>
                        <td>{attribute}</td>
                        <td>
                          <input
                            aria-label={`${text(row.name)} ${attribute} value`}
                            type="number" min={0} className="sg-num-input"
                            defaultValue={text(row.value)}
                            key={`${index}-${text(row.value)}`}
                            onBlur={(e) => {
                              const v = Number(e.target.value);
                              if (e.target.value.trim() !== '' && Number.isFinite(v) && v >= 0 && v !== Number(row.value)) {
                                onUpdateRow(TIME_UNITS_SHEET, index, 'value', v);
                              } else {
                                e.target.value = text(row.value);
                              }
                            }}
                          />
                        </td>
                        <td>
                          <select
                            aria-label={`${text(row.name)} ${attribute} unit`}
                            value={text(row.unit)}
                            onChange={(e) => onUpdateRow(TIME_UNITS_SHEET, index, 'unit', e.target.value)}
                          >
                            {unitsFor(attribute).map((u) => <option key={u} value={u}>{u}</option>)}
                          </select>
                        </td>
                        <td>{converted ? converted.stepHours : ''}</td>
                        <td title={converted?.note || undefined}>
                          {converted ? (converted.blank ? 'blank (no limit)' : converted.pypsaValue) : ''}
                          {converted?.note ? ' *' : ''}
                        </td>
                        <td>
                          <button type="button" className="tb-btn" onClick={() => onDeleteRow(TIME_UNITS_SHEET, index)}>Remove</button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
            {preview && preview.some((p) => p.note) && (
              <ul className="time-units__notes">
                {preview.filter((p) => p.note).map((p) => <li key={`${p.name}.${p.attribute}`} className="sg-setting-hint">* {p.note}</li>)}
              </ul>
            )}
            <div className="time-units__add">
              <select aria-label="Component name" value={draftName} onChange={(e) => setDraft({ ...draft, name: e.target.value })}>
                {names.length === 0 && <option value="">no {sheet} yet</option>}
                {names.map((n) => <option key={n} value={n}>{n}</option>)}
              </select>
              <select
                aria-label="Attribute" value={draftAttribute}
                onChange={(e) => setDraft({ ...draft, attribute: e.target.value, unit: '' })}
              >
                {attributes.map((a) => <option key={a} value={a}>{a}</option>)}
              </select>
              <input
                aria-label="Value" type="number" min={0} className="sg-num-input" placeholder={dimension(draftAttribute)}
                value={draft.value} onChange={(e) => setDraft({ ...draft, value: e.target.value })}
                onKeyDown={(e) => { if (e.key === 'Enter') addRow(); }}
              />
              <select aria-label="Unit" value={draftUnit} onChange={(e) => setDraft({ ...draft, unit: e.target.value })}>
                {unitsFor(draftAttribute).map((u) => <option key={u} value={u}>{u}</option>)}
              </select>
              <button type="button" className="tb-btn" disabled={!draftValid || duplicate} onClick={addRow}>Add row</button>
            </div>
            {duplicate && <p className="sg-setting-hint">{draftName} already has a {draftAttribute} row; edit it above.</p>}
            <div className="time-units__preview">
              <button type="button" className="tb-btn" disabled={busy || rows.length === 0} onClick={() => void runPreview()}>
                Preview per-snapshot values
              </button>
              {stepHours !== null && preview && (
                <span className="sg-setting-hint">
                  At the workbook's own weightings ({stepHours} h per snapshot). A run with another resolution, window or sampling converts at its own step.
                </span>
              )}
            </div>
            {error && <p className="sg-setting-hint" role="alert">{error}</p>}
          </>
        )}
      </div>
    </aside>
  );
}
