/**
 * Forge -> Slice window / buses (`POST /api/transform/slice`, PyPSA `n.slice_network`).
 *
 * Keep a snapshot window (labels, both ends inclusive) and/or a set of buses together with every component fully
 * attached to them. Preview reports the effect on the session copy; Apply replaces the working model.
 */
import React, { useMemo, useState } from 'react';
import { SearchableMultiSelect } from 'shared/components/SearchableMultiSelect';
import { describeChange, postSlice, type TransformResult } from 'lib/api/networkOps';
import type { GridRow, WorkbookModel } from 'lib/types';

interface Props {
  model: WorkbookModel;
  onSessionSync?: () => Promise<void>;
  onReplaceModel?: (model: WorkbookModel, message: string) => void;
  onStatus: (msg: string) => void;
}

function column(model: WorkbookModel, sheet: string, key: string): string[] {
  return ((model as Record<string, GridRow[]>)[sheet] ?? []).map((r) => String(r[key] ?? '')).filter(Boolean);
}

export function SliceNetworkPanel({ model, onSessionSync, onReplaceModel, onStatus }: Props) {
  const snapshots = useMemo(() => column(model, 'snapshots', 'snapshot'), [model]);
  const busNames = useMemo(() => column(model, 'buses', 'name'), [model]);
  const [start, setStart] = useState('');
  const [end, setEnd] = useState('');
  const [buses, setBuses] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<TransformResult | null>(null);

  const nothingChosen = !start.trim() && !end.trim() && buses.length === 0;
  const reset = () => { setResult(null); setError(null); };

  const preview = async () => {
    if (nothingChosen || !onSessionSync) return;
    setBusy(true);
    reset();
    try {
      await onSessionSync();
      setResult(await postSlice({ start, end, buses }));
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Slice failed.');
    } finally {
      setBusy(false);
    }
  };

  const apply = () => {
    if (!result || !onReplaceModel) return;
    const message = `Slice: ${describeChange(result.before, result.after)}; working model replaced.`;
    onReplaceModel(result.model, message);
    onStatus(message);
    setResult(null);
  };

  return (
    <section className="forge-section">
      <header className="forge-section-header">
        <h3>Slice window and buses</h3>
        <p>
          Keep a time window and/or a set of buses; components attached only to dropped buses go with them.
          Window ends are snapshot labels as they appear in the snapshots sheet and both are inclusive. Leave a side empty to keep it open.
        </p>
      </header>

      <div className="sg-setting-row">
        <label className="sg-setting-label" htmlFor="slice-start">First snapshot</label>
        <input id="slice-start" type="text" className="forge-number net-tool-text" value={start} placeholder={snapshots[0] ?? ''} onChange={(e) => { setStart(e.target.value); reset(); }} />
      </div>
      <div className="sg-setting-row">
        <label className="sg-setting-label" htmlFor="slice-end">Last snapshot</label>
        <input id="slice-end" type="text" className="forge-number net-tool-text" value={end} placeholder={snapshots[snapshots.length - 1] ?? ''} onChange={(e) => { setEnd(e.target.value); reset(); }} />
      </div>
      <div className="sg-setting-row">
        <span className="sg-setting-label">Keep buses</span>
        <SearchableMultiSelect values={buses} options={busNames} onChange={(v) => { setBuses(v); reset(); }} placeholder="All buses" />
      </div>

      <div className="forge-adjust-actions">
        <button type="button" className="secondary-button" onClick={() => void preview()} disabled={busy || nothingChosen || !onSessionSync}>
          {busy ? 'Slicing' : 'Preview'}
        </button>
        {result && (
          <button type="button" className="primary-button" onClick={apply} disabled={!onReplaceModel}>
            Apply to working model
          </button>
        )}
      </div>
      {nothingChosen && <p className="sg-setting-hint">Give a window end or pick buses to keep.</p>}
      {error && <p className="sg-setting-hint" role="alert">{error}</p>}
      {result && <p className="sg-setting-hint">{describeChange(result.before, result.after)}.</p>}
    </section>
  );
}
