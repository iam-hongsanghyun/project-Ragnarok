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
  guideStopFor,
  moveBy,
  percentComplete,
  resolveCurrentStepId,
  setStartChoice,
  startChoiceFor,
  stepIndex,
  toggleStep,
} from 'lib/training/progress';
import { ViewPaneHeader } from 'shared/components/primitives';
import { ModelSummary, StartOptionsBanner } from './StartStateBanner';

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

function StepBody({ step, onNavigate, onStartGuide, guideStop }: {
  step: TutorialStep;
  onNavigate: (t: WorkspaceTab) => void;
  onStartGuide: (stops: Spotlight[], stepId?: string, startIndex?: number) => void;
  /** Walkthrough stop previously reached on this step (0 = untouched). */
  guideStop: number;
}) {
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

      {step.entries && step.entries.length > 0 && (
        <section className="training-block">
          <h4 className="training-block__title">What each value means</h4>
          <p className="training-block__note">
            Every value this step uses, what it controls, and why it is set to this. Read it after doing
            the step — it is the reference you come back to, not a list to work through.
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
                  <td>
                    <code className="training-field">{entry.field}</code>
                    {entry.label && <span className="training-field-label">{entry.label}</span>}
                  </td>
                  <td className="training-value-cell">
                    <span className="training-value">{entry.value}</span>
                    {entry.unit && <span className="training-unit">{entry.unit}</span>}
                  </td>
                  <td className="training-why">{entry.why}</td>
                </tr>
              ))}
            </tbody>
          </table>
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

  // A step ALWAYS opens at the top — that is where the idea and the "where"
  // strip are, and a learner arriving at a step needs to read them before the
  // table of values.
  const bodyRef = useRef<HTMLDivElement>(null);
  const shownStepId = step?.id ?? null;
  useEffect(() => {
    if (bodyRef.current) bodyRef.current.scrollTop = 0;
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

        {/* Every module opens with the same three-way choice of starting model. */}
        {step?.startOptions && (
          <StartOptionsBanner
            options={step.startOptions}
            model={modelSummary}
            choice={startChoiceFor(progress, step.id)}
            onChoiceChange={(c) => onProgressChange(setStartChoice(progress, step.id, c))}
            onClearModel={onClearModel}
            onLoadExample={onLoadExample}
          />
        )}

        {step ? (
          <article className="training-step">
            {/* No section line and no step number: the rail header already names
                the module, and the steps are a sequence you walk rather than a
                numbered list to cross-reference. */}
            <h3 className="training-step__title">{step.title}</h3>
            <StepBody
              step={step}
              onNavigate={onNavigate}
              onStartGuide={onStartGuide}
              guideStop={guideStopFor(progress, step.id)}
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
