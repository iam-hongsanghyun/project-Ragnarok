/**
 * Model-check findings with their visible actions.
 *
 * Runs `POST /api/model-check` on the session's workbook and lists what is very likely not what the modeller meant.
 * A finding that carries an `action` offers it as a button; nothing is changed until the button is pressed.
 *
 *  - `weighting_spacing`: the snapshot weighting disagrees with the timestamp spacing, so PyPSA books the wrong energy.
 *    Action: set the weightings from the spacing (`POST /api/model/set-weightings-from-spacing`).
 *  - `placeholder_bounds`: a finite 1e9+ bound stands for "no limit". Action: the preview-then-apply clean-up.
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { runModelCheck, type ModelCheckFinding, type ModelCheckResult } from 'lib/api/modelCheck';
import { PlaceholderBoundsPanel } from './PlaceholderBoundsPanel';

export interface ModelCheckPanelProps {
  /** Any value that changes when the model changed; the check re-runs (debounced) on change. */
  refreshKey: unknown;
  onSessionSync: () => Promise<void>;
  onSessionReload: () => Promise<void>;
  /** The visible weightings step (App's handler; it syncs, calls the route and reloads the model itself). */
  onSetWeightingsFromSpacing?: () => Promise<void> | void;
  /** Show notes as well as warnings. Default: warnings only. */
  includeNotes?: boolean;
}

const DEBOUNCE_MS = 1200;

export function ModelCheckPanel({
  refreshKey, onSessionSync, onSessionReload, onSetWeightingsFromSpacing, includeNotes = false,
}: ModelCheckPanelProps) {
  const [result, setResult] = useState<ModelCheckResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState<string | null>(null);
  const seq = useRef(0);

  const check = useCallback(async () => {
    const mine = ++seq.current;
    setBusy(true);
    try {
      const next = await runModelCheck();
      if (mine === seq.current) { setResult(next); setError(null); }
    } catch (e) {
      // "No model loaded" is the normal state before an import: nothing to check yet.
      if (mine === seq.current) { setResult(null); setError(e instanceof Error ? e.message : 'Model check failed'); }
    } finally {
      if (mine === seq.current) setBusy(false);
    }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => void check(), DEBOUNCE_MS);
    return () => window.clearTimeout(timer);
  }, [refreshKey, check]);

  const findings: ModelCheckFinding[] = (result?.findings ?? []).filter((f) => includeNotes || f.level === 'warn');
  if (!result && !error) return null;
  if (error && !result) {
    return /No model loaded/i.test(error) ? null : (
      <div className="model-check-panel" role="status"><p className="sg-setting-hint">Model check unavailable: {error}</p></div>
    );
  }
  if (findings.length === 0) return null;

  return (
    <div className="model-check-panel" data-tour="model-check" role="region" aria-label="Model check">
      <div className="model-check-panel__head">
        <b>Model check</b>
        <span className="sg-setting-hint">{result?.verdict}</span>
        <button type="button" className="tb-btn" disabled={busy} onClick={() => void check()}>Check again</button>
      </div>
      <ul className="model-check-panel__list">
        {findings.map((f) => (
          <li key={f.code} className={`model-check-finding model-check-finding--${f.level}`}>
            <div><b>{f.level === 'warn' ? 'Warning' : 'Note'}</b> — {f.message}</div>
            {f.fix && <div className="sg-setting-hint">{f.fix}</div>}
            {f.code === 'weighting_spacing' && f.action && onSetWeightingsFromSpacing && (
              <button
                type="button"
                className="tb-btn"
                disabled={busy}
                onClick={async () => {
                  setBusy(true);
                  try { await onSetWeightingsFromSpacing(); } finally { setBusy(false); }
                  void check();
                }}
              >
                {f.action.label}
              </button>
            )}
            {f.code === 'placeholder_bounds' && f.action && (
              <>
                <button type="button" className="tb-btn" onClick={() => setOpen(open === f.code ? null : f.code)}>
                  {open === f.code ? 'Hide clean-up' : f.action.label}
                </button>
                {open === f.code && (
                  <PlaceholderBoundsPanel
                    onSessionSync={onSessionSync}
                    onSessionReload={onSessionReload}
                    onApplied={() => void check()}
                  />
                )}
              </>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
