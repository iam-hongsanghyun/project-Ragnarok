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
}

/** True when the session holds no model worth worrying about. */
export function isSessionEmpty(m: ModelSummary): boolean {
  return m.buses === 0 && m.generators === 0 && m.loads === 0 && m.snapshots === 0;
}

export function StartStateBanner({ startState, model, onClearModel, onLoadExample }: Props) {
  const { confirm } = useDialog();
  const [busy, setBusy] = useState(false);
  const empty = isSessionEmpty(model);
  const wantsEmpty = startState.kind === 'empty';
  // The only combination that needs action: the tutorial builds from scratch and
  // something is already loaded. A checkpoint tutorial always offers its load.
  const satisfied = wantsEmpty ? empty : false;

  const clear = async () => {
    const ok = await confirm(
      `This removes the loaded model (${model.filename}) and every unsaved edit, on both the `
      + 'frontend and the backend session.\n\nYour settings, run history and installed plugins are kept.',
      { title: 'Clear the model?', confirmText: 'Clear model', danger: true },
    );
    if (!ok) return;
    setBusy(true);
    try { await onClearModel(); } finally { setBusy(false); }
  };

  const load = async () => {
    if (!startState.exampleId) return;
    setBusy(true);
    try { await onLoadExample(startState.exampleId); } finally { setBusy(false); }
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

      {!satisfied && (
        <div className="training-start-state__actions">
          {wantsEmpty ? (
            <>
              <button type="button" className="primary-button" disabled={busy} onClick={() => void clear()}>
                Clear the model
              </button>
              <span className="training-start-state__alt">
                — or keep what you have and read along without building.
              </span>
            </>
          ) : (
            <>
              <button
                type="button"
                className="primary-button"
                disabled={busy || !startState.exampleId}
                onClick={() => void load()}
              >
                Load the starting model
              </button>
              <span className="training-start-state__alt">
                — or keep your own model if you would rather apply the module to it.
              </span>
            </>
          )}
        </div>
      )}
    </section>
  );
}
