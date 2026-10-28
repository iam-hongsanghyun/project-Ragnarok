/**
 * Placeholder-bounds clean-up: preview, then apply.
 *
 * A bound cell holding a finite 1e9 or more (1e12 standing for "no limit") reaches PyPSA as written and gives the LP a
 * huge right-hand side. `POST /api/forge/clean-placeholder-bounds` blanks those cells so the row takes PyPSA's `inf`
 * default. The server decides which cells; this panel previews them and writes only when asked. It is used by the Forge
 * tool and by the model-check finding of the same name.
 */
import React, { useState } from 'react';
import { cleanPlaceholderBounds, type CleanPlaceholderBoundsResult } from 'lib/api/forgeBuild';

export interface PlaceholderBoundsPanelProps {
  /** Push the browser's working model to the session (the server reads the session). */
  onSessionSync: () => Promise<void>;
  /** Pull the session model back after the server wrote sheets. */
  onSessionReload: () => Promise<void>;
  /** Called after the clean-up was written (the model check re-runs). */
  onApplied?: () => void;
}

const SHOWN_CELLS = 12;

export function PlaceholderBoundsPanel({ onSessionSync, onSessionReload, onApplied }: PlaceholderBoundsPanelProps) {
  const [preview, setPreview] = useState<CleanPlaceholderBoundsResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const run = async (apply: boolean) => {
    setBusy(true);
    setError(null);
    try {
      await onSessionSync();
      const result = await cleanPlaceholderBounds({ apply });
      if (apply) {
        await onSessionReload();
        setPreview(null);
        setMessage(`${result.cleaned} bound cell(s) blanked in ${Object.keys(result.sheets).join(', ') || 'no sheet'}; they now take PyPSA's default (inf).`);
        onApplied?.();
      } else {
        setPreview(result);
        setMessage(result.cleaned === 0 ? 'No placeholder bounds found.' : null);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Clean-up failed');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="placeholder-bounds" data-tour="placeholder-bounds">
      <div className="forge-actions">
        <button type="button" className="tb-btn" disabled={busy} onClick={() => void run(false)}>
          Preview clean-up
        </button>
        <button
          type="button"
          className="run-button"
          disabled={busy || !preview || preview.cleaned === 0}
          onClick={() => void run(true)}
        >
          Apply clean-up
        </button>
      </div>
      {error && <p className="sg-setting-hint" role="alert">{error}</p>}
      {message && <p className="sg-setting-hint" role="status">{message}</p>}
      {preview && preview.cleaned > 0 && (
        <>
          <p className="sg-setting-hint">
            {preview.cleaned} cell(s) would be blanked
            {' '}({Object.entries(preview.sheets).map(([sheet, rows]) => `${sheet}: ${rows} row${rows === 1 ? '' : 's'}`).join('; ')}).
            Nothing is written until you apply.
          </p>
          <table className="sg-table">
            <thead><tr><th>Sheet</th><th>Name</th><th>Column</th><th>Value now</th></tr></thead>
            <tbody>
              {preview.cells.slice(0, SHOWN_CELLS).map((c) => (
                <tr key={`${c.sheet}.${c.name}.${c.column}`}>
                  <td>{c.sheet}</td><td>{c.name}</td><td>{c.column}</td><td>{c.value.toExponential(0)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {preview.cells.length > SHOWN_CELLS && (
            <p className="sg-setting-hint">+ {preview.cells.length - SHOWN_CELLS} more cell(s)</p>
          )}
        </>
      )}
    </div>
  );
}
