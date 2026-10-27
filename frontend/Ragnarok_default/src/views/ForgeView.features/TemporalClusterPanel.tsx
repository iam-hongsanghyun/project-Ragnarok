/**
 * Forge — temporal clustering (PyPSA `n.cluster.temporal`, P35).
 *
 * resample (pandas offset), downsample (every n-th snapshot) or segment (TSAM-style;
 * the backend answers 400 when `tsam` is not installed and that message is shown).
 * Snapshot weightings are carried through so annual energy and cost stay correct.
 * Preview reduces the session copy; Apply replaces the working model, like the
 * network-reduction tool.
 */
import React, { useState } from 'react';
import type { TemporalMethod, TemporalOptions, TemporalResult } from 'lib/api/temporal';
import type { WorkbookModel } from 'lib/types';

interface Props {
  onTemporalPreview?: (opts: TemporalOptions) => Promise<TemporalResult>;
  onTemporalApply?: (model: WorkbookModel) => void;
  onStatus: (msg: string) => void;
}

/** Why the form cannot run yet, or null when it can. */
export function temporalInputError(o: TemporalOptions): string | null {
  if (o.method === 'resample' && !(o.offset ?? '').trim()) return "Enter an offset such as '3h' or '1D'.";
  if (o.method === 'downsample' && !(Number.isInteger(o.stride) && (o.stride as number) >= 2)) return 'Stride must be a whole number of at least 2.';
  if (o.method === 'segment' && !(Number.isInteger(o.numSegments) && (o.numSegments as number) >= 1)) return 'Segments must be a whole number of at least 1.';
  return null;
}

export function TemporalClusterPanel({ onTemporalPreview, onTemporalApply, onStatus }: Props) {
  const [method, setMethod] = useState<TemporalMethod>('resample');
  const [offset, setOffset] = useState('3h');
  const [dropLeapDay, setDropLeapDay] = useState(false);
  const [stride, setStride] = useState('2');
  const [segments, setSegments] = useState('24');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<TemporalResult | null>(null);

  const options: TemporalOptions = {
    method,
    offset,
    dropLeapDay,
    stride: Number(stride),
    numSegments: Number(segments),
  };
  const inputError = temporalInputError(options);

  const preview = async () => {
    if (!onTemporalPreview || inputError) return;
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      setResult(await onTemporalPreview(options));
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Temporal clustering failed.');
    } finally {
      setBusy(false);
    }
  };

  const apply = () => {
    if (!result || !onTemporalApply) return;
    onTemporalApply(result.model);
    onStatus(`Temporal ${result.method}: ${result.before.snapshots} → ${result.after.snapshots} snapshots; working model replaced.`);
    setResult(null);
  };

  return (
    <section className="forge-section">
      <header className="forge-section-header">
        <h3>Temporal clustering</h3>
        <p>
          Reduce the time axis with PyPSA's native clustering. Snapshot weightings are kept energy-correct
          (a 3-hour resample weights each kept snapshot 3). <b>Segment</b> needs the optional <code>tsam</code> package.
        </p>
      </header>

      <div className="sg-setting-row">
        <label className="sg-setting-label">Method</label>
        <select className="forge-adjust-select" value={method} onChange={(e) => { setMethod(e.target.value as TemporalMethod); setResult(null); setError(null); }} aria-label="Method">
          <option value="resample">Resample (offset)</option>
          <option value="downsample">Downsample (every n-th)</option>
          <option value="segment">Segment (TSAM)</option>
        </select>
      </div>

      {method === 'resample' && (
        <>
          <div className="sg-setting-row">
            <label className="sg-setting-label">Offset</label>
            <input type="text" className="forge-number" style={{ width: 120 }} value={offset} onChange={(e) => setOffset(e.target.value)} aria-label="Offset" />
            <span className="sg-setting-hint" style={{ margin: 0 }}>pandas offset, e.g. 3h, 6h, 1D</span>
          </div>
          <div className="sg-setting-row">
            <label className="sg-setting-label">Drop 29 Feb</label>
            <input type="checkbox" checked={dropLeapDay} onChange={(e) => setDropLeapDay(e.target.checked)} aria-label="Drop leap day" />
          </div>
        </>
      )}
      {method === 'downsample' && (
        <div className="sg-setting-row">
          <label className="sg-setting-label">Stride</label>
          <input type="number" className="forge-number" min={2} step={1} style={{ width: 100 }} value={stride} onChange={(e) => setStride(e.target.value)} aria-label="Stride" />
          <span className="sg-setting-hint" style={{ margin: 0 }}>keep every n-th snapshot, weight x n</span>
        </div>
      )}
      {method === 'segment' && (
        <div className="sg-setting-row">
          <label className="sg-setting-label">Segments</label>
          <input type="number" className="forge-number" min={1} step={1} style={{ width: 100 }} value={segments} onChange={(e) => setSegments(e.target.value)} aria-label="Segments" />
          <span className="sg-setting-hint" style={{ margin: 0 }}>number of segments over the horizon</span>
        </div>
      )}

      <div className="forge-adjust-actions">
        <button type="button" className="secondary-button" onClick={preview} disabled={busy || !onTemporalPreview || !!inputError}>
          {busy ? 'Reducing…' : 'Preview'}
        </button>
        {result && (
          <button type="button" className="primary-button" onClick={apply} disabled={!onTemporalApply}>
            Apply to working model
          </button>
        )}
      </div>
      {inputError && <p className="sg-setting-hint">{inputError}</p>}
      {error && <p className="sg-setting-hint" role="alert">{error}</p>}
      {result && (
        <p className="sg-setting-hint">
          {result.before.snapshots} → {result.after.snapshots} snapshots; weighted hours {result.before.weightedHours} → {result.after.weightedHours}.
        </p>
      )}
    </section>
  );
}
