/**
 * Forge -> Write sample (`POST /api/transform/sample`).
 *
 * Test-run sampling written into the workbook: the sampled snapshots, their weightings and the averaged series
 * become the model, so the reduction is visible and editable rather than applied silently at run time. Preview
 * returns the reduced workbook's size, the representation factor and the backend's notes; Apply replaces the working
 * model. Sample a workbook that already has the resolution you want (resolution is Temporal clustering's job).
 */
import React, { useState } from 'react';
import { defaultSamplingConfig, normalizeSamplingConfig } from 'lib/results/sampling';
import { postSample, type SampleResult } from 'lib/api/networkOps';
import type { SamplingConfig, WorkbookModel } from 'lib/types';

interface Props {
  onSessionSync?: () => Promise<void>;
  onReplaceModel?: (model: WorkbookModel, message: string) => void;
  onStatus: (msg: string) => void;
}

/** Why the form cannot run yet, or null when it can. */
export function sampleInputError(cfg: SamplingConfig, start: string, count: string): string | null {
  if (cfg.mode === 'count' && !(Number(cfg.blockCount) >= 1)) return 'Block count must be at least 1.';
  if (!(Number(cfg.blockSize) >= 1)) return 'Block size must be at least 1.';
  if (start.trim() !== '' && !(Number.isInteger(Number(start)) && Number(start) >= 0)) return 'Window start must be a whole number of 0 or more.';
  if (count.trim() !== '' && !(Number.isInteger(Number(count)) && Number(count) >= 1)) return 'Window length must be a whole number of at least 1.';
  return null;
}

export function WriteSamplePanel({ onSessionSync, onReplaceModel, onStatus }: Props) {
  const [cfg, setCfg] = useState<SamplingConfig>({ ...defaultSamplingConfig(), enabled: true });
  const [windowStart, setWindowStart] = useState('');
  const [windowCount, setWindowCount] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<SampleResult | null>(null);

  const inputError = sampleInputError(cfg, windowStart, windowCount);
  const patch = (p: Partial<SamplingConfig>) => { setCfg({ ...cfg, ...p }); setResult(null); setError(null); };

  const preview = async () => {
    if (inputError || !onSessionSync) return;
    setBusy(true);
    setResult(null);
    setError(null);
    try {
      await onSessionSync();
      setResult(await postSample({
        sampling: normalizeSamplingConfig(cfg),
        snapshotStart: windowStart.trim() === '' ? undefined : Number(windowStart),
        snapshotCount: windowCount.trim() === '' ? undefined : Number(windowCount),
      }));
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Sampling failed.');
    } finally {
      setBusy(false);
    }
  };

  const apply = () => {
    if (!result || !onReplaceModel) return;
    const message = `Sample written: ${result.before.snapshots} to ${result.after.snapshots} snapshots (factor ${result.factor}); working model replaced.`;
    onReplaceModel(result.model, message);
    onStatus(message);
    setResult(null);
  };

  return (
    <section className="forge-section">
      <header className="forge-section-header">
        <h3>Write sample</h3>
        <p>
          Write a test-run sample into the workbook: fewer snapshots whose weightings are scaled so energy, cost and emissions still
          represent the whole window. <b>Count</b> takes equally spaced blocks, <b>Gap</b> repeats a block then skips, <b>Average</b> writes one averaged block.
        </p>
      </header>

      <div className="sg-setting-row">
        <label className="sg-setting-label" htmlFor="sample-mode">Mode</label>
        <select id="sample-mode" className="forge-adjust-select" value={cfg.mode} onChange={(e) => patch({ mode: e.target.value as SamplingConfig['mode'] })}>
          <option value="count">Count (equally spaced blocks)</option>
          <option value="gap">Gap (block, then skip)</option>
          <option value="average">Average (one averaged block)</option>
        </select>
      </div>
      <div className="sg-setting-row">
        <label className="sg-setting-label" htmlFor="sample-size">Block size (snapshots)</label>
        <input id="sample-size" type="number" min={1} step={1} className="forge-number" value={cfg.blockSize} onChange={(e) => patch({ blockSize: Number(e.target.value) })} />
      </div>
      {cfg.mode === 'count' && (
        <div className="sg-setting-row">
          <label className="sg-setting-label" htmlFor="sample-count">Block count</label>
          <input id="sample-count" type="number" min={1} step={1} className="forge-number" value={cfg.blockCount} onChange={(e) => patch({ blockCount: Number(e.target.value) })} />
        </div>
      )}
      {cfg.mode === 'gap' && (
        <div className="sg-setting-row">
          <label className="sg-setting-label" htmlFor="sample-gap">Gap (snapshots skipped)</label>
          <input id="sample-gap" type="number" min={0} step={1} className="forge-number" value={cfg.gapSnapshots} onChange={(e) => patch({ gapSnapshots: Number(e.target.value) })} />
        </div>
      )}
      <div className="sg-setting-row">
        <label className="sg-setting-label" htmlFor="sample-wstart">Window start (position)</label>
        <input id="sample-wstart" type="number" min={0} step={1} className="forge-number" value={windowStart} placeholder="first snapshot" onChange={(e) => { setWindowStart(e.target.value); setResult(null); }} />
      </div>
      <div className="sg-setting-row">
        <label className="sg-setting-label" htmlFor="sample-wcount">Window length (snapshots)</label>
        <input id="sample-wcount" type="number" min={1} step={1} className="forge-number" value={windowCount} placeholder="to the end" onChange={(e) => { setWindowCount(e.target.value); setResult(null); }} />
      </div>
      <label className="modal-check-row">
        <input type="checkbox" checked={cfg.scaleStartUpCosts !== false} onChange={(e) => patch({ scaleStartUpCosts: e.target.checked })} />
        <span>Scale start-up and shut-down costs by the representation factor</span>
      </label>

      <div className="forge-adjust-actions">
        <button type="button" className="secondary-button" onClick={() => void preview()} disabled={busy || !!inputError || !onSessionSync}>
          {busy ? 'Sampling' : 'Preview'}
        </button>
        {result && (
          <button type="button" className="primary-button" onClick={apply} disabled={!onReplaceModel}>
            Write sample to working model
          </button>
        )}
      </div>
      {inputError && <p className="sg-setting-hint">{inputError}</p>}
      {error && <p className="sg-setting-hint" role="alert">{error}</p>}
      {result && (
        <>
          <p className="sg-setting-hint">
            {result.before.snapshots} to {result.after.snapshots} snapshots; each kept snapshot represents a factor of {result.factor}.
          </p>
          {result.notes.length > 0 && <ul className="validation-list validation-list--notes">{result.notes.map((n, i) => <li key={i}>{n}</li>)}</ul>}
        </>
      )}
    </section>
  );
}
