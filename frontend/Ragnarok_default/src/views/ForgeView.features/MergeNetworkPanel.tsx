/**
 * Forge -> Merge another network (`POST /api/transform/merge`, PyPSA `n.merge`).
 *
 * Adds the components of a stored run's model, or of another session's model, to the working model. Component names
 * must be unique across the two (the backend answers 400 with the collision otherwise). Preview shows the merged
 * totals; Apply replaces the working model.
 */
import React, { useState } from 'react';
import { describeChange, postMerge, type MergeRequest, type TransformResult } from 'lib/api/networkOps';
import type { BackendRunMeta, WorkbookModel } from 'lib/types';

interface Props {
  runs: BackendRunMeta[];
  onSessionSync?: () => Promise<void>;
  onReplaceModel?: (model: WorkbookModel, message: string) => void;
  onStatus: (msg: string) => void;
}

type SourceKind = 'run' | 'session';

/** "Carrier, generators" -> ["Carrier", "generators"]. */
export function parseSkipList(text: string): string[] {
  return text.split(',').map((s) => s.trim()).filter(Boolean);
}

export function MergeNetworkPanel({ runs, onSessionSync, onReplaceModel, onStatus }: Props) {
  const [sourceKind, setSourceKind] = useState<SourceKind>('run');
  const [runName, setRunName] = useState('');
  const [sessionId, setSessionId] = useState('');
  const [skip, setSkip] = useState('');
  const [withTime, setWithTime] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<TransformResult | null>(null);

  const chosen = sourceKind === 'run' ? runName : sessionId.trim();
  const reset = () => { setResult(null); setError(null); };

  const preview = async () => {
    if (!chosen || !onSessionSync) return;
    const request: MergeRequest = {
      source: sourceKind === 'run' ? { otherRun: runName } : { otherSessionId: sessionId.trim() },
      componentsToSkip: parseSkipList(skip),
      withTime,
    };
    setBusy(true);
    reset();
    try {
      await onSessionSync();
      setResult(await postMerge(request));
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Merge failed.');
    } finally {
      setBusy(false);
    }
  };

  const apply = () => {
    if (!result || !onReplaceModel) return;
    const message = `Merge: ${describeChange(result.before, result.after)}; working model replaced.`;
    onReplaceModel(result.model, message);
    onStatus(message);
    setResult(null);
  };

  return (
    <section className="forge-section">
      <header className="forge-section-header">
        <h3>Merge another network</h3>
        <p>
          Add the components of a stored run's model, or of another session's model, to the working model.
          Component names must not collide between the two.
        </p>
      </header>

      <div className="sg-setting-row">
        <label className="sg-setting-label" htmlFor="merge-source">Merge from</label>
        <select id="merge-source" className="forge-adjust-select" value={sourceKind} onChange={(e) => { setSourceKind(e.target.value as SourceKind); reset(); }}>
          <option value="run">A stored run (History)</option>
          <option value="session">Another session</option>
        </select>
      </div>
      {sourceKind === 'run' ? (
        <div className="sg-setting-row">
          <label className="sg-setting-label" htmlFor="merge-run">Run</label>
          <select id="merge-run" className="forge-adjust-select" value={runName} onChange={(e) => { setRunName(e.target.value); reset(); }}>
            <option value="">Choose a run</option>
            {runs.map((r) => <option key={r.name} value={r.name}>{r.label || r.name}</option>)}
          </select>
          {runs.length === 0 && <p className="sg-setting-hint">No stored runs yet.</p>}
        </div>
      ) : (
        <div className="sg-setting-row">
          <label className="sg-setting-label" htmlFor="merge-session">Session id</label>
          <input id="merge-session" type="text" className="forge-number net-tool-text" value={sessionId} onChange={(e) => { setSessionId(e.target.value); reset(); }} />
        </div>
      )}
      <div className="sg-setting-row">
        <label className="sg-setting-label" htmlFor="merge-skip">Components to skip</label>
        <input id="merge-skip" type="text" className="forge-number net-tool-text" value={skip} placeholder="PyPSA names, e.g. Carrier" onChange={(e) => { setSkip(e.target.value); reset(); }} />
      </div>
      <label className="modal-check-row">
        <input type="checkbox" checked={withTime} onChange={(e) => { setWithTime(e.target.checked); reset(); }} />
        <span>Merge time series as well</span>
      </label>

      <div className="forge-adjust-actions">
        <button type="button" className="secondary-button" onClick={() => void preview()} disabled={busy || !chosen || !onSessionSync}>
          {busy ? 'Merging' : 'Preview'}
        </button>
        {result && (
          <button type="button" className="primary-button" onClick={apply} disabled={!onReplaceModel}>
            Apply to working model
          </button>
        )}
      </div>
      {error && <p className="sg-setting-hint" role="alert">{error}</p>}
      {result && (
        <p className="sg-setting-hint">
          {describeChange(result.before, result.after)}.
          {result.merged ? ` The merged-in network has ${result.merged.buses} buses and ${result.merged.snapshots} snapshots.` : ''}
        </p>
      )}
    </section>
  );
}
