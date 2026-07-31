/**
 * TutorialRunner — plays one tutorial, one step at a time.
 *
 * The runner is deliberately inert with respect to the model. It shows WHERE to
 * be, WHAT to type, WHICH file to import and WHEN to run; the only thing it
 * does to the app is switch the active view via `onNavigate`, so the user is
 * looking at the right place. It never writes a cell, never imports a file and
 * never submits a run — a learner who watches values appear has not learnt
 * where those values live.
 */
import React, { useCallback, useState } from 'react';
import { WorkspaceTab } from 'lib/types';
import { Tutorial, TutorialProgress, TutorialStep } from 'lib/training/types';
import {
  completeAndAdvance,
  isStepComplete,
  isTutorialComplete,
  moveBy,
  percentComplete,
  resolveCurrentStepId,
  stepIndex,
  toggleStep,
} from 'lib/training/progress';
import { ViewPaneHeader } from 'shared/components/primitives';

interface Props {
  tutorial: Tutorial;
  progress: TutorialProgress;
  onProgressChange: (next: TutorialProgress) => void;
  /** Switch the workspace to a view. The only app mutation a tutorial may do. */
  onNavigate: (tab: WorkspaceTab) => void;
  /** Return to the tutorial picker. */
  onExit: () => void;
  onReset: () => void;
}

/** Human label for a workspace tab, matching the activity-bar wording. */
const TAB_LABEL: Partial<Record<WorkspaceTab, string>> = {
  Welcome: 'Welcome',
  Data: 'Data',
  Build: 'Build',
  Model: 'Model',
  Forge: 'Forge',
  Market: 'Market & Policy',
  Settings: 'Settings',
  Analytics: 'Analytics',
  PhysicalRisk: 'Physical Risk',
  Siting: 'Siting',
  PostAnalysis: 'Post-analysis',
  History: 'History',
  Plugins: 'Plugins',
  Training: 'Training',
};

/** Copy-to-clipboard button. Copying is not entering — the user still pastes. */
function CopyValue({ value }: { value: string }) {
  const [copied, setCopied] = useState(false);
  const copy = useCallback(() => {
    void navigator.clipboard?.writeText(value)
      .then(() => {
        setCopied(true);
        window.setTimeout(() => setCopied(false), 1200);
      })
      .catch(() => { /* clipboard blocked — the value is on screen to type anyway */ });
  }, [value]);
  return (
    <button type="button" className="training-copy" onClick={copy} title="Copy the value — you still paste it yourself">
      {copied ? 'Copied' : 'Copy'}
    </button>
  );
}

function StepBody({ step, onNavigate }: { step: TutorialStep; onNavigate: (t: WorkspaceTab) => void }) {
  return (
    <>
      <div className="training-where">
        <div>
          <span className="training-where__label">Where</span>
          <span className="training-where__value">{step.where}</span>
        </div>
        <button type="button" className="tb-btn" onClick={() => onNavigate(step.tab)}>
          Open {TAB_LABEL[step.tab] ?? step.tab}
        </button>
      </div>

      <section className="training-block">
        {step.explain.map((paragraph, i) => (
          // Paragraphs are static authored content; index keys are stable.
          // eslint-disable-next-line react/no-array-index-key
          <p key={i} className="training-explain">{paragraph}</p>
        ))}
      </section>

      {step.entries && step.entries.length > 0 && (
        <section className="training-block">
          <h4 className="training-block__title">Values to enter</h4>
          <p className="training-block__note">
            Ragnarok does not enter these for you — type them in yourself so you learn where they live.
          </p>
          <table className="training-table">
            <thead>
              <tr>
                <th>Field</th>
                <th>Value</th>
                <th>Why</th>
              </tr>
            </thead>
            <tbody>
              {step.entries.map((entry) => (
                <tr key={`${entry.field}|${entry.value}`}>
                  <td><code className="training-field">{entry.field}</code></td>
                  <td className="training-value-cell">
                    <span className="training-value">{entry.value}</span>
                    {entry.unit && <span className="training-unit">{entry.unit}</span>}
                    <CopyValue value={entry.value} />
                  </td>
                  <td className="training-why">{entry.why}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      {step.files && step.files.length > 0 && (
        <section className="training-block">
          <h4 className="training-block__title">Files to import</h4>
          <p className="training-block__note">
            Ragnarok does not fetch or open these for you — import them yourself using the control named below.
          </p>
          {step.files.map((file) => (
            <div key={`${file.what}|${file.via}`} className="training-file">
              <div className="training-file__what">{file.what}</div>
              <dl className="training-file__meta">
                <dt>Import via</dt>
                <dd><code className="training-field">{file.via}</code></dd>
                <dt>Must contain</dt>
                <dd>{file.requires}</dd>
                {file.source && (<><dt>Where to get it</dt><dd>{file.source}</dd></>)}
              </dl>
            </div>
          ))}
        </section>
      )}

      {step.run && (
        <section className="training-block training-run">
          <h4 className="training-block__title">Run to start</h4>
          <p className="training-block__note">
            You start the run. Ragnarok will not submit it for you.
          </p>
          <div className="training-run__label"><code className="training-field">{step.run.label}</code></div>
          {step.run.detail.map((paragraph, i) => (
            // eslint-disable-next-line react/no-array-index-key
            <p key={i} className="training-explain">{paragraph}</p>
          ))}
          <p className="training-run__expect"><b>Expect:</b> {step.run.expect}</p>
        </section>
      )}

      <section className="training-block">
        <h4 className="training-block__title">How you know it worked</h4>
        <ul className="training-list training-list--verify">
          {step.verify.map((item) => <li key={item}>{item}</li>)}
        </ul>
      </section>

      {step.pitfalls && step.pitfalls.length > 0 && (
        <section className="training-block">
          <h4 className="training-block__title">What commonly goes wrong</h4>
          <ul className="training-list training-list--pitfall">
            {step.pitfalls.map((item) => <li key={item}>{item}</li>)}
          </ul>
        </section>
      )}
    </>
  );
}

export function TutorialRunner({ tutorial, progress, onProgressChange, onNavigate, onExit, onReset }: Props) {
  const currentId = resolveCurrentStepId(tutorial, progress);
  const index = stepIndex(tutorial, currentId);
  const step = index >= 0 ? tutorial.steps[index] : null;
  const percent = percentComplete(tutorial, progress);
  const finished = isTutorialComplete(tutorial, progress);
  const done = step ? isStepComplete(progress, step.id) : false;

  return (
    <div className="training-runner">
      <ViewPaneHeader>
        <div className="training-runner__head">
          <div className="training-runner__title">
            <button type="button" className="training-back" onClick={onExit}>All tutorials</button>
            <h2>{tutorial.title}</h2>
            <span className={`training-level training-level--${tutorial.level.toLowerCase()}`}>{tutorial.level}</span>
          </div>
          <div className="training-runner__meta">
            <div className="training-progress" role="img" aria-label={`${percent}% complete`}>
              <div className="training-progress__fill" style={{ width: `${percent}%` }} />
            </div>
            <span className="training-progress__text">
              {step ? `Step ${index + 1} of ${tutorial.steps.length}` : `${tutorial.steps.length} steps`} · {percent}%
            </span>
            <button type="button" className="tb-btn tb-btn--muted" onClick={onReset}>Reset progress</button>
          </div>
        </div>
      </ViewPaneHeader>

      <div className="training-runner__body">
        {finished && (
          <div className="training-done" role="status">
            <b>Tutorial complete.</b> Every step is ticked. Reset progress to run through it again,
            or go back to the list for the next one.
          </div>
        )}

        {step ? (
          <article className="training-step">
            <h3 className="training-step__title">
              <span className="training-step__number">{index + 1}</span>
              {step.title}
            </h3>
            <StepBody step={step} onNavigate={onNavigate} />
          </article>
        ) : (
          <div className="view-empty"><p>This tutorial has no steps yet.</p></div>
        )}
      </div>

      {step && (
        <footer className="training-footer">
          <button
            type="button"
            className="tb-btn"
            disabled={index <= 0}
            onClick={() => onProgressChange(moveBy(tutorial, progress, -1))}
          >
            Previous
          </button>
          <label className="training-footer__check">
            <input
              type="checkbox"
              checked={done}
              onChange={() => onProgressChange(toggleStep(progress, step.id))}
            />
            Step done
          </label>
          <div className="training-footer__spacer" />
          <button
            type="button"
            className="tb-btn"
            disabled={index >= tutorial.steps.length - 1}
            onClick={() => onProgressChange(moveBy(tutorial, progress, 1))}
          >
            Next
          </button>
          <button
            type="button"
            className="primary-button"
            onClick={() => onProgressChange(completeAndAdvance(tutorial, progress, step.id))}
          >
            {index >= tutorial.steps.length - 1 ? 'Finish tutorial' : 'Done — next step'}
          </button>
        </footer>
      )}
    </div>
  );
}
