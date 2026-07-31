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
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { WorkspaceTab } from 'lib/types';
import { Spotlight, Tutorial, TutorialProgress, TutorialStep } from 'lib/training/types';
import {
  completeAndAdvance,
  isStepComplete,
  isTutorialComplete,
  entriesDoneFor,
  guideStopFor,
  isEntryDone,
  moveBy,
  percentComplete,
  resolveCurrentStepId,
  stepIndex,
  toggleEntry,
  toggleStep,
} from 'lib/training/progress';
import { ViewPaneHeader } from 'shared/components/primitives';
import { ModelSummary, StartStateBanner } from './StartStateBanner';

interface Props {
  tutorial: Tutorial;
  progress: TutorialProgress;
  onProgressChange: (next: TutorialProgress) => void;
  /** Switch the workspace to a view. The only app mutation a tutorial may do. */
  onNavigate: (tab: WorkspaceTab) => void;
  /** Start this step's spotlight walkthrough of the real UI. */
  onStartGuide: (stops: Spotlight[], stepId?: string, startIndex?: number) => void;
  /** Return to the tutorial picker. */
  onExit: () => void;
  onReset: () => void;
  /** What the session currently holds, for the start-state banner. */
  modelSummary: ModelSummary;
  onClearModel: () => void | Promise<void>;
  onLoadExample: (id: string) => void | Promise<void>;
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

function StepBody({ step, onNavigate, onStartGuide, guideStop, isDone, onToggleEntry }: {
  step: TutorialStep;
  onNavigate: (t: WorkspaceTab) => void;
  onStartGuide: (stops: Spotlight[], stepId?: string, startIndex?: number) => void;
  /** Walkthrough stop previously reached on this step (0 = untouched). */
  guideStop: number;
  /** Has this value already been entered? */
  isDone: (field: string) => boolean;
  onToggleEntry: (field: string) => void;
}) {
  const entries = step.entries ?? [];
  const doneCount = entries.filter((e) => isDone(e.field)).length;
  return (
    <>
      {step.concept && step.concept.length > 0 && (
        // The modelling idea comes first and reads as its own thing: the theory
        // has to survive being read without the tool in front of you.
        <section className="training-concept">
          <h4 className="training-block__title">The idea</h4>
          {step.concept.map((paragraph, i) => (
            // eslint-disable-next-line react/no-array-index-key
            <p key={i} className="training-explain">{paragraph}</p>
          ))}
        </section>
      )}

      <div className="training-where">
        <div>
          <span className="training-where__label">Where</span>
          <span className="training-where__value">{step.where}</span>
        </div>
        <div className="training-where__actions">
          {step.spotlights && step.spotlights.length > 0 && (
            // A walkthrough closed mid-way resumes at the stage it was on, so
            // going off to do the work does not cost the stops already seen.
            <button
              type="button"
              className="primary-button"
              onClick={() => onStartGuide(step.spotlights!, step.id, guideStop)}
            >
              {guideStop > 0 && guideStop < step.spotlights.length
                ? `Resume tour (${guideStop + 1}/${step.spotlights.length})`
                : `Show me (${step.spotlights.length})`}
            </button>
          )}
          <button type="button" className="tb-btn" onClick={() => onNavigate(step.tab)}>
            Open {TAB_LABEL[step.tab] ?? step.tab}
          </button>
        </div>
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
          <h4 className="training-block__title">
            Values to enter
            <span className="training-block__count">{doneCount} of {entries.length} entered</span>
          </h4>
          <p className="training-block__note">
            Ragnarok does not enter these for you — type them in yourself so you learn where they live.
            Tick each one off as you go; leaving this view and coming back returns you to the first you
            have not ticked.
          </p>
          <table className="training-table">
            <thead>
              <tr>
                <th aria-label="Entered" />
                <th>Field</th>
                <th>Value</th>
                <th>Why</th>
              </tr>
            </thead>
            <tbody>
              {step.entries.map((entry) => (
                <tr
                  key={`${entry.field}|${entry.value}`}
                  className={isDone(entry.field) ? 'is-entered' : ''}
                  data-entry-pending={isDone(entry.field) ? undefined : '1'}
                >
                  <td className="training-entry-check">
                    <input
                      type="checkbox"
                      checked={isDone(entry.field)}
                      onChange={() => onToggleEntry(entry.field)}
                      aria-label={`Entered ${entry.field}`}
                    />
                  </td>
                  <td>
                    <code className="training-field">{entry.field}</code>
                    {entry.label && <span className="training-field-label">{entry.label}</span>}
                  </td>
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

export function TutorialRunner({
  tutorial, progress, onProgressChange, onNavigate, onStartGuide, onExit, onReset,
  modelSummary, onClearModel, onLoadExample,
}: Props) {
  const currentId = resolveCurrentStepId(tutorial, progress);
  const index = stepIndex(tutorial, currentId);
  const step = index >= 0 ? tutorial.steps[index] : null;
  const percent = percentComplete(tutorial, progress);
  const finished = isTutorialComplete(tutorial, progress);
  const done = step ? isStepComplete(progress, step.id) : false;

  // Where to start reading when the shown step changes.
  //
  // A step is ALWAYS opened at the top — that is where the idea and the "where"
  // strip are, and a learner arriving at a step needs to read them. Only once
  // they have ticked at least one value does this become a resume: then, and only
  // then, jump to the first value still outstanding so a twenty-row step does not
  // have to be re-found. Scrolling an untouched step into its middle just hides
  // the explanation.
  //
  // Keyed on the shown step, not on every tick, so ticking a box does not move
  // the page under the cursor.
  const bodyRef = useRef<HTMLDivElement>(null);
  const shownStepId = step?.id ?? null;
  const resumeCount = shownStepId ? entriesDoneFor(progress, shownStepId).length : 0;
  useEffect(() => {
    const body = bodyRef.current;
    if (!body || !shownStepId) return;
    const pending = resumeCount > 0 ? body.querySelector('[data-entry-pending="1"]') : null;
    if (pending) pending.scrollIntoView({ block: 'center' });
    else body.scrollTop = 0;
    // resumeCount is read at step-change time only — adding it as a dependency
    // would re-scroll on every tick.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [shownStepId]);

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

      <div className="training-runner__body" ref={bodyRef}>
        {finished && (
          <div className="training-done" role="status">
            <b>Tutorial complete.</b> Every step is ticked. Reset progress to run through it again,
            or go back to the list for the next one.
          </div>
        )}

        {/* Starting state matters on the first step only. */}
        {step && index === 0 && tutorial.startState && (
          <StartStateBanner
            startState={tutorial.startState}
            model={modelSummary}
            onClearModel={onClearModel}
            onLoadExample={onLoadExample}
            prebuiltLoaded={progress.prebuiltLoaded ?? false}
            onPrebuiltLoadedChange={(v) => onProgressChange({ ...progress, prebuiltLoaded: v })}
          />
        )}

        {step ? (
          <article className="training-step">
            {step.section && <div className="training-step__section">{step.section}</div>}
            <h3 className="training-step__title">
              <span className="training-step__number">{index + 1}</span>
              {step.title}
            </h3>
            <StepBody
              step={step}
              onNavigate={onNavigate}
              onStartGuide={onStartGuide}
              guideStop={guideStopFor(progress, step.id)}
              isDone={(field) => isEntryDone(progress, step.id, field)}
              onToggleEntry={(field) => onProgressChange(toggleEntry(progress, step.id, field))}
            />
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
