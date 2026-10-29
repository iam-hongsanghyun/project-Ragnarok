/**
 * Demand response rows: preview, then apply.
 *
 * The run builds demand response from the `dr_*` rows in the workbook (buses, links, stores, loads). This panel sends the
 * section's config to `POST /api/demand-response/preview`, shows the rows the module would write per sheet, and only the
 * Apply button writes them (`POST /api/demand-response/apply`; a disabled config removes the module's rows). The server
 * computes every row; the browser lists them.
 */
import React, { useState } from 'react';
import type { DemandResponseConfig } from 'lib/types';
import {
  applyDemandResponse,
  previewDemandResponse,
  type DemandResponsePreview,
} from 'lib/api/operationsModules';

export interface DemandResponseApplyProps {
  config: DemandResponseConfig;
  /** Push the browser's working model to the session (the server reads the session). */
  onSessionSync: () => Promise<void>;
  /** Pull the session model back after the server wrote sheets. */
  onSessionReload: () => Promise<void>;
}

const SHOWN_ROWS = 6;
const countRows = (by: Record<string, unknown[]>): number => Object.values(by).reduce((n, rows) => n + rows.length, 0);
const cell = (v: unknown): string => (typeof v === 'number' ? String(Math.round(v * 1000) / 1000) : String(v ?? ''));

function SheetRows({ title, rows }: { title: string; rows: Record<string, Record<string, unknown>[]> }) {
  const sheets = Object.entries(rows).filter(([, r]) => r.length > 0);
  if (sheets.length === 0) return null;
  return (
    <>
      <p className="sg-setting-hint"><b>{title}</b></p>
      {sheets.map(([sheet, sheetRows]) => {
        const columns = Object.keys(sheetRows[0]);
        return (
          <div key={sheet}>
            <p className="sg-setting-hint">{sheet}: {sheetRows.length} row(s)</p>
            <table className="sg-table">
              <thead><tr>{columns.map((c) => <th key={c}>{c}</th>)}</tr></thead>
              <tbody>
                {sheetRows.slice(0, SHOWN_ROWS).map((r, i) => (
                  <tr key={i}>{columns.map((c) => <td key={c}>{cell(r[c])}</td>)}</tr>
                ))}
              </tbody>
            </table>
            {sheetRows.length > SHOWN_ROWS && <p className="sg-setting-hint">+ {sheetRows.length - SHOWN_ROWS} more row(s)</p>}
          </div>
        );
      })}
    </>
  );
}

export function DemandResponseApply({ config, onSessionSync, onSessionReload }: DemandResponseApplyProps) {
  const [preview, setPreview] = useState<DemandResponsePreview | null>(null);
  const [previewOf, setPreviewOf] = useState<string>('');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const configKey = JSON.stringify(config);
  // A preview of an older config is stale: Apply stays off until the current config is previewed.
  const current = preview !== null && previewOf === configKey;
  const nothing = current && preview !== null && preview.sheets.length === 0;

  const run = async (apply: boolean) => {
    setBusy(true);
    setError(null);
    try {
      await onSessionSync();
      if (apply) {
        const out = await applyDemandResponse(config);
        await onSessionReload();
        setPreview(null);
        setMessage(`Written to ${out.sheetsWritten.join(', ') || 'no sheet'}: ${countRows(out.rows)} row(s) added, ${countRows(out.removed)} removed. ${out.notes.join(' ')}`);
      } else {
        const next = await previewDemandResponse(config);
        setPreview(next);
        setPreviewOf(configKey);
        setMessage(null);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Demand response failed');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="demand-response-apply" data-tour="demand-response-apply">
      <div className="sg-setting-divider" />
      <header className="constraints-workspace-section-header">
        <h3>Workbook rows</h3>
        <p>
          The run builds demand response from dr_* rows in the workbook. Preview shows what the settings above would write;
          Apply writes them (previous dr_* rows are replaced; with the mode off and elastic demand off, they are removed).
        </p>
      </header>
      <div className="forge-actions">
        <button type="button" className="tb-btn" disabled={busy} onClick={() => void run(false)}>Preview rows</button>
        <button type="button" className="run-button" disabled={busy || !current || nothing} onClick={() => void run(true)}>Apply rows</button>
      </div>
      {error && <p className="sg-setting-hint" role="alert">{error}</p>}
      {message && <p className="sg-setting-hint" role="status">{message}</p>}
      {preview && !current && <p className="sg-setting-hint">The settings changed since this preview; preview again to apply.</p>}
      {preview && (
        <>
          {preview.notes.map((n) => <p key={n} className="sg-setting-hint">{n}</p>)}
          {nothing && <p className="sg-setting-hint">The workbook already holds exactly these rows; nothing to write.</p>}
          <SheetRows title="Rows to write" rows={preview.rows} />
          {Object.entries(preview.removed).filter(([, names]) => names.length > 0).map(([sheet, names]) => (
            <p key={sheet} className="sg-setting-hint">Remove from {sheet}: {names.join(', ')}</p>
          ))}
          {countRows(preview.existing) > 0 && (
            <p className="sg-setting-hint">The workbook already holds {countRows(preview.existing)} dr_* row(s); Apply replaces them.</p>
          )}
        </>
      )}
    </div>
  );
}
