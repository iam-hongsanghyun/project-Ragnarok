/**
 * Relax maintenance: preview, then apply.
 *
 * PyPSA's linearised unit commitment (Force LP) refuses units that carry maintenance windows. `POST
 * /api/model/relax-maintenance` sets `maintainable` to False on those generators / links / processes. The server decides
 * which rows; this panel previews them (`apply: false` writes nothing) and writes only when asked.
 */
import React, { useState } from 'react';
import { relaxMaintenance, type RelaxMaintenanceResult } from 'lib/api/operationsModules';

export interface RelaxMaintenancePanelProps {
  /** Push the browser's working model to the session (the server reads the session). */
  onSessionSync: () => Promise<void>;
  /** Pull the session model back after the server wrote sheets. */
  onSessionReload: () => Promise<void>;
  /** Called after the change was written. */
  onApplied?: () => void;
}

const SHOWN_ROWS = 12;

export function RelaxMaintenancePanel({ onSessionSync, onSessionReload, onApplied }: RelaxMaintenancePanelProps) {
  const [preview, setPreview] = useState<RelaxMaintenanceResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const run = async (apply: boolean) => {
    setBusy(true);
    setError(null);
    try {
      await onSessionSync();
      const result = await relaxMaintenance(apply);
      if (apply) {
        await onSessionReload();
        setPreview(null);
        setMessage(`maintainable set to false on ${result.changed.length} row(s) in ${result.sheetsWritten.join(', ') || 'no sheet'}.`);
        onApplied?.();
      } else {
        setPreview(result);
        setMessage(result.changed.length === 0 ? 'No maintainable units in the model; nothing to relax.' : null);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Relax maintenance failed');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="relax-maintenance" data-tour="relax-maintenance">
      <div className="forge-actions">
        <button type="button" className="tb-btn" disabled={busy} onClick={() => void run(false)}>
          Preview relax maintenance
        </button>
        <button
          type="button"
          className="run-button"
          disabled={busy || !preview || preview.changed.length === 0}
          onClick={() => void run(true)}
        >
          Relax maintenance
        </button>
      </div>
      {error && <p className="sg-setting-hint" role="alert">{error}</p>}
      {message && <p className="sg-setting-hint" role="status">{message}</p>}
      {preview && preview.changed.length > 0 && (
        <>
          <p className="sg-setting-hint">
            {preview.changed.length} row(s) would get maintainable = false. Nothing is written until you apply.
          </p>
          <table className="sg-table">
            <thead><tr><th>Sheet</th><th>Name</th></tr></thead>
            <tbody>
              {preview.changed.slice(0, SHOWN_ROWS).map((c) => (
                <tr key={`${c.sheet}.${c.name}`}><td>{c.sheet}</td><td>{c.name}</td></tr>
              ))}
            </tbody>
          </table>
          {preview.changed.length > SHOWN_ROWS && (
            <p className="sg-setting-hint">+ {preview.changed.length - SHOWN_ROWS} more row(s)</p>
          )}
        </>
      )}
    </div>
  );
}
