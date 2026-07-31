/**
 * Training view — guided, step-by-step walkthroughs of Ragnarok workflows.
 *
 * Layout: a rail that lists the tutorials, or — once one is running — that
 * tutorial's steps as a checklist you can jump around in; and a main pane
 * holding either the picker or the runner.
 *
 * The view is read-only with respect to the model. It tells the user what to
 * type, which file to import and when to run, and the only thing it does to the
 * app itself is switch the active view so they are looking at the right place.
 * See `lib/training/catalog.ts` for the authoring rules that keep it that way.
 */
import React, { useCallback } from 'react';
import { WorkspaceTab } from 'lib/types';
import { Spotlight, TutorialProgress } from 'lib/training/types';
import { TUTORIALS, findTutorial, stepsBySection, tutorialsByLevel } from 'lib/training/catalog';
import {
  emptyProgress,
  isStepComplete,
  percentComplete,
  resolveCurrentStepId,
} from 'lib/training/progress';
import { LeftRail, ViewPanel } from 'shared/components/primitives';
import { ResizablePanels } from '../layout/ResizablePanels';
import { TutorialCatalog } from './TrainingView.features/TutorialCatalog';
import { TutorialRunner } from './TrainingView.features/TutorialRunner';
import type { ModelSummary } from './TrainingView.features/StartStateBanner';

interface Props {
  /** Switch the workspace to a view, so a step can put the user in the right place. */
  onNavigate: (tab: WorkspaceTab) => void;
  /** Start a spotlight walkthrough. Owned by App so it survives a view switch. */
  onStartGuide: (stops: Spotlight[]) => void;
  /**
   * Which tutorial is running, and how far through each one the learner is.
   *
   * Owned by App, not this view: the top bar shows a "resume tutorial" affordance
   * while a tutorial is open, and this view is unmounted for most of the time a
   * learner spends actually doing the steps.
   */
  activeId: string | null;
  onActiveIdChange: (id: string | null) => void;
  progressById: Record<string, TutorialProgress>;
  onProgressByIdChange: (next: Record<string, TutorialProgress>) => void;
  /** What the session holds, and the actions to change it — for the start-state banner. */
  modelSummary: ModelSummary;
  onClearModel: () => void | Promise<void>;
  onLoadExample: (id: string) => void | Promise<void>;
}

export function TrainingView({
  onNavigate, onStartGuide, activeId, onActiveIdChange, progressById, onProgressByIdChange,
  modelSummary, onClearModel, onLoadExample,
}: Props) {
  const setActiveId = onActiveIdChange;
  const setProgressById = onProgressByIdChange;

  const active = findTutorial(activeId);
  const progressFor = useCallback(
    (id: string): TutorialProgress => progressById[id] ?? emptyProgress(),
    [progressById],
  );

  const setProgressFor = useCallback((id: string, next: TutorialProgress) => {
    setProgressById({ ...progressById, [id]: next });
  }, [progressById, setProgressById]);

  const rail = active ? (
    <LeftRail
      title="Steps"
      ariaLabel={`${active.title} steps`}
      headerAction={
        <button type="button" className="training-rail-back" onClick={() => setActiveId(null)}>
          All
        </button>
      }
    >
      {stepsBySection(active.steps).map((group, gi) => (
        // Section runs are positional, so the index is the stable identity.
        // eslint-disable-next-line react/no-array-index-key
        <div key={`${group.section ?? 'ungrouped'}-${gi}`} className="training-rail-group">
          {group.section && <div className="training-rail-group__title">{group.section}</div>}
          <ol className="training-rail-steps">
            {group.items.map(({ step, number }) => {
              const done = isStepComplete(progressFor(active.id), step.id);
              const current = resolveCurrentStepId(active, progressFor(active.id)) === step.id;
              return (
                <li key={step.id}>
                  <button
                    type="button"
                    className={`training-rail-step${current ? ' is-current' : ''}${done ? ' is-done' : ''}`}
                    onClick={() => setProgressFor(active.id, { ...progressFor(active.id), currentStepId: step.id })}
                    aria-current={current ? 'step' : undefined}
                  >
                    <span className="training-rail-step__num">{done ? '✓' : number}</span>
                    <span className="training-rail-step__label">{step.title}</span>
                  </button>
                </li>
              );
            })}
          </ol>
        </div>
      ))}
    </LeftRail>
  ) : (
    <LeftRail title="Training" ariaLabel="Tutorials">
      {TUTORIALS.length === 0 ? (
        <p className="training-rail-empty">No tutorials yet.</p>
      ) : (
        tutorialsByLevel(TUTORIALS).map((group) => (
          <div key={group.level} className="training-rail-group">
            <div className="training-rail-group__title">{group.level}</div>
            {group.items.map((t) => {
              const percent = percentComplete(t, progressFor(t.id));
              return (
                <button
                  key={t.id}
                  type="button"
                  className="training-rail-item"
                  onClick={() => setActiveId(t.id)}
                >
                  <span className="training-rail-item__label">{t.title}</span>
                  <span className="training-rail-item__meta">
                    {t.minutes} min{percent > 0 ? ` · ${percent}%` : ''}
                  </span>
                </button>
              );
            })}
          </div>
        ))
      )}
    </LeftRail>
  );

  return (
    <ViewPanel name="training">
      <ResizablePanels id="training" direction="horizontal" initialSizes={[24, 76]} minSize={200}>
        {rail}
        <main className="view-main training-main">
          {active ? (
            <TutorialRunner
              tutorial={active}
              progress={progressFor(active.id)}
              onProgressChange={(next) => setProgressFor(active.id, next)}
              onNavigate={onNavigate}
              onStartGuide={onStartGuide}
              modelSummary={modelSummary}
              onClearModel={onClearModel}
              onLoadExample={onLoadExample}
              onExit={() => setActiveId(null)}
              onReset={() => setProgressFor(active.id, emptyProgress())}
            />
          ) : (
            <TutorialCatalog
              tutorials={TUTORIALS}
              progressById={progressFor}
              onStart={setActiveId}
            />
          )}
        </main>
      </ResizablePanels>
    </ViewPanel>
  );
}
