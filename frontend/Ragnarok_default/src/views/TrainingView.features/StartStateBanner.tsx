/**
 * The banner every module opens with: how the learner wants to start it.
 *
 * One control, one meaning, wherever it is met in the course — module 1 offers
 * empty or the finished module-1 model; every later module also offers the
 * model it starts from.
 */
import React, { useState } from 'react';
import { StepStartOptions, TutorialStartChoice } from 'lib/training/types';
import { useDialog } from '../../shared/components/Dialog';

export interface ModelSummary {
  filename: string;
  /** Component counts, for reporting what the session holds. */
  buses: number;
  generators: number;
  loads: number;
  snapshots: number;
}

/** True when the session holds no model worth worrying about. */
export function isSessionEmpty(m: ModelSummary): boolean {
  return m.buses === 0 && m.generators === 0 && m.loads === 0 && m.snapshots === 0;
}

/**
 * StartOptionsBanner — how a learner opens a module.
 *
 * Three mutually exclusive ways in, shown on the first step of every module:
 *
 *   empty     build it yourself, from nothing
 *   prebuilt  the model this module STARTS from — what the previous module
 *             finished with, so you carry on rather than rebuild
 *   complete  the model this module ENDS with, for reading and running rather
 *             than building, or for checking your own work against
 *
 * A radio group rather than a checkbox because the three are exclusive and the
 * learner is choosing a starting state, not toggling a feature. Nothing loads
 * on its own and every choice confirms first: someone may be resuming work they
 * deliberately left half done, and silently replacing it would be the worst
 * thing this could do.
 */
export function StartOptionsBanner({ options, model, choice, onChoiceChange, onClearModel, onLoadExample }: {
  options: StepStartOptions;
  model: ModelSummary;
  choice: TutorialStartChoice;
  onChoiceChange: (c: TutorialStartChoice) => void;
  onClearModel: () => void | Promise<void>;
  onLoadExample: (id: string) => void | Promise<void>;
}) {
  const { confirm } = useDialog();
  const [busy, setBusy] = useState(false);
  const empty = isSessionEmpty(model);

  /** Replacing whatever is loaded needs saying out loud, once, in one place. */
  const confirmReplace = async (what: string): Promise<boolean> => {
    if (empty) return true;
    return confirm(
      `Loading ${what} replaces the current model (${model.filename}) and every unsaved edit.`,
      { title: 'Replace the current model?', confirmText: 'Load it', danger: true },
    );
  };

  const choose = async (next: TutorialStartChoice) => {
    if (next === choice) return;
    setBusy(true);
    try {
      if (next === 'empty') {
        const ok = empty || await confirm(
          `This removes the loaded model (${model.filename}) and every unsaved edit, on both the `
          + 'frontend and the backend session.\n\nYour settings, run history and installed plugins are kept.',
          { title: 'Clear the model?', confirmText: 'Clear model', danger: true },
        );
        if (!ok) return;
        await onClearModel();
      } else {
        const id = next === 'prebuilt' ? options.prebuiltExampleId : options.completeExampleId;
        if (!id) return;
        if (!await confirmReplace(next === 'prebuilt' ? 'this module\'s starting model' : 'the finished model')) return;
        await onLoadExample(id);
      }
      onChoiceChange(next);
    } finally {
      setBusy(false);
    }
  };

  const choices: Array<{ value: TutorialStartChoice; label: string; detail: string }> = [
    {
      value: 'empty',
      label: 'Empty',
      detail: 'Nothing loaded — build this module\'s model yourself, which is how it sticks.',
    },
    ...(options.prebuiltExampleId ? [{
      value: 'prebuilt' as const,
      label: 'Prebuilt data',
      detail: 'The model this module starts from, exactly as the previous module left it. '
        + 'Carry on from there instead of rebuilding everything before it.',
    }] : []),
    ...(options.completeExampleId ? [{
      value: 'complete' as const,
      label: 'Complete data',
      detail: 'The model this module ends with. For reading and running rather than building — '
        + 'or for checking your own against the finished article.',
    }] : []),
  ];

  return (
    <section className="training-start-state">
      <div className="training-start-state__head">
        <span className="training-start-state__label">Start this module with</span>
        <span className="training-start-state__now">
          Session holds <b>{model.filename}</b>
          {empty ? ' — no model loaded' : ` — ${model.buses} buses, ${model.generators} generators, `
            + `${model.loads} loads, ${model.snapshots} snapshots`}
        </span>
      </div>

      <p className="training-start-state__note">{options.note}</p>

      <div className="training-start-choices">
        {choices.map((c) => (
          <label key={c.value} className={`training-start-choice${choice === c.value ? ' is-active' : ''}`}>
            <input
              type="radio"
              name="training-start-choice"
              checked={choice === c.value}
              disabled={busy}
              onChange={() => void choose(c.value)}
            />
            <span>
              <b>{c.label}</b>
              <span className="training-start-choice__detail">{c.detail}</span>
            </span>
          </label>
        ))}
        {busy && <p className="training-start-state__alt">Working…</p>}
      </div>
    </section>
  );
}
