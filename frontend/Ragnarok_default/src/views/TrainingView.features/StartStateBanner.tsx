/**
 * StartStateBanner — reconciles the session against what a tutorial expects.
 *
 * Shown on a tutorial's first step only, because that is when starting state
 * matters. It states what the tutorial wants, reports what the session actually
 * holds, and offers the actions to close the gap.
 *
 * It does not act on its own. A learner may be resuming work they deliberately
 * left half finished, and silently clearing that would be the worst thing this
 * feature could do — so clearing and loading are both explicit button presses,
 * and clearing confirms first.
 */
import React, { useState } from 'react';
import { TutorialStartState } from 'lib/training/types';
import { useDialog } from '../../shared/components/Dialog';

export interface ModelSummary {
  filename: string;
  /** Component counts, for reporting what the session holds. */
  buses: number;
  generators: number;
  loads: number;
  snapshots: number;
}

interface Props {
  startState: TutorialStartState;
  model: ModelSummary;
  /** Drop the loaded model, keeping settings. */
  onClearModel: () => void | Promise<void>;
  /** Load a bundled example by id. */
  onLoadExample: (id: string) => void | Promise<void>;
  /** Persisted "prebuilt data loaded" tick — survives the remount loading causes. */
  prebuiltLoaded: boolean;
  onPrebuiltLoadedChange: (v: boolean) => void;
}

/** True when the session holds no model worth worrying about. */
export function isSessionEmpty(m: ModelSummary): boolean {
  return m.buses === 0 && m.generators === 0 && m.loads === 0 && m.snapshots === 0;
}

export function StartStateBanner({ startState, model, onClearModel, onLoadExample, prebuiltLoaded, onPrebuiltLoadedChange }: Props) {
  const { confirm } = useDialog();
  const [busy, setBusy] = useState(false);
  const empty = isSessionEmpty(model);
  const wantsEmpty = startState.kind === 'empty';
  // The only combination that needs action: the tutorial builds from scratch and
  // something is already loaded. A checkpoint tutorial always offers its load.
  const satisfied = wantsEmpty ? empty : false;

  /** Clear the model, confirm-first. Returns whether it actually happened. */
  const clear = async (): Promise<boolean> => {
    const ok = await confirm(
      `This removes the loaded model (${model.filename}) and every unsaved edit, on both the `
      + 'frontend and the backend session.\n\nYour settings, run history and installed plugins are kept.',
      { title: 'Clear the model?', confirmText: 'Clear model', danger: true },
    );
    if (!ok) return false;
    setBusy(true);
    try { await onClearModel(); return true; } finally { setBusy(false); }
  };

  const load = async () => {
    if (!startState.exampleId) return;
    if (!empty) {
      const ok = await confirm(
        `Loading the prebuilt data replaces the current model (${model.filename}) and every unsaved edit.`,
        { title: 'Replace with prebuilt data?', confirmText: 'Load prebuilt', danger: true },
      );
      if (!ok) return;
    }
    setBusy(true);
    try { await onLoadExample(startState.exampleId); onPrebuiltLoadedChange(true); } finally { setBusy(false); }
  };

  // Unticking undoes the shortcut: back to the empty session the tutorial
  // assumes. Same confirm as any other model clear; stays ticked if declined.
  const unload = async () => {
    if (await clear()) onPrebuiltLoadedChange(false);
  };

  return (
    <section className={`training-start-state${satisfied ? ' is-ready' : ''}`}>
      <div className="training-start-state__head">
        <span className="training-start-state__label">
          {satisfied ? 'Ready to start' : 'Before you start'}
        </span>
        <span className="training-start-state__now">
          Session holds <b>{model.filename}</b>
          {empty ? ' — no model loaded' : ` — ${model.buses} buses, ${model.generators} generators, `
            + `${model.loads} loads, ${model.snapshots} snapshots`}
        </span>
      </div>

      <p className="training-start-state__note">{startState.note}</p>

      {/* One checkbox: ticked loads everything the tutorial would otherwise
          have the learner type; unticking clears back to an empty session
          (confirm-first). Present whenever the tutorial ships its data. */}
      {startState.exampleId && (
        <label className="training-start-state__prebuilt">
          <input
            type="checkbox"
            checked={prebuiltLoaded}
            disabled={busy}
            onChange={(e) => { if (e.target.checked) void load(); else void unload(); }}
          />
          <span>
            <b>Start with prebuilt data</b> — load the complete model this tutorial builds, and skip
            the typing. Leave unticked to build it yourself, which is how it sticks.
            {busy && <em> Working…</em>}
          </span>
        </label>
      )}

      {!satisfied && !startState.exampleId && (
        <div className="training-start-state__actions">
          <button type="button" className="primary-button" disabled={busy} onClick={() => void clear()}>
            Clear the model
          </button>
          <span className="training-start-state__alt">
            — or keep what you have and read along without building.
          </span>
        </div>
      )}
      {!satisfied && startState.exampleId && !prebuiltLoaded && wantsEmpty && (
        <div className="training-start-state__actions">
          <button type="button" className="tb-btn" disabled={busy} onClick={() => void clear()}>
            Clear the model
          </button>
          <span className="training-start-state__alt">
            — to build from scratch as the tutorial assumes.
          </span>
        </div>
      )}
    </section>
  );
}
