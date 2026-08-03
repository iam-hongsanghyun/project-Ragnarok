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
import React, { useCallback, useState } from 'react';
import { WorkspaceTab } from 'lib/types';
import { Spotlight, TutorialProgress } from 'lib/training/types';
import { TUTORIALS, findTutorial, modulesByLevel, modulesWithSteps } from 'lib/training/catalog';
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
  onStartGuide: (stops: Spotlight[], stepId?: string, startIndex?: number) => void;
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
  // The module the learner is in, by its `section` string. Null means the rail
  // is showing the level → module picker rather than a module's steps.
  const [openSection, setOpenSection] = useState<string | null>(null);
  const setProgressById = onProgressByIdChange;

  const active = findTutorial(activeId);
  const progressFor = useCallback(
    (id: string): TutorialProgress => progressById[id] ?? emptyProgress(),
    [progressById],
  );

  const setProgressFor = useCallback((id: string, next: TutorialProgress) => {
    setProgressById({ ...progressById, [id]: next });
  }, [progressById, setProgressById]);

  /**
   * Open a tutorial and RECORD which step it is on.
   *
   * Without the record, `currentStepId` stays null until the learner presses
   * Next, and resuming falls back to inferring the step from what is ticked. A
   * learner who read step 1, went off to Build, and came back would be inferred
   * back to step 1 correctly — but anyone who ticked steps out of order would
   * not. Storing it makes "where was I" a fact rather than a guess.
   */
  const openTutorial = useCallback((id: string) => {
    setActiveId(id);
    const tutorial = findTutorial(id);
    const current = progressById[id] ?? emptyProgress();
    if (tutorial && !current.currentStepId) {
      const resolved = resolveCurrentStepId(tutorial, current);
      if (resolved) setProgressById({ ...progressById, [id]: { ...current, currentStepId: resolved } });
    }
  }, [setActiveId, progressById, setProgressById]);

  const modules = active ? modulesWithSteps(active) : [];
  const openModule = modules.find((m) => m.module.section === openSection) ?? null;

  // Rail, in the Settings idiom: a group title with plain items under it, no
  // nesting and nothing collapsible. Two states — pick a module, or work
  // through one — because a nine-module course does not fit as one list.
  const rail = active && openModule ? (
    <LeftRail
      title={openModule.module.title}
      ariaLabel={`${openModule.module.title} steps`}
      className="settings-section-nav"
      headerAction={
        <button type="button" className="training-rail-back" onClick={() => setOpenSection(null)}>
          Modules
        </button>
      }
    >
      <div className="settings-nav-group">
        <div className="settings-nav-group-title">{openModule.module.section}</div>
        {/* Numbered within the module, matching the runner's "Step N of M" —
            the module is the unit a learner navigates, so a rail counting
            7…16 against a body counting 1…10 would just be two answers to the
            same question. */}
        {openModule.items.map(({ step }, i) => {
          const number = i + 1;
          const done = isStepComplete(progressFor(active.id), step.id);
          const current = resolveCurrentStepId(active, progressFor(active.id)) === step.id;
          return (
            <button
              key={step.id}
              type="button"
              className={`settings-nav-item training-step-item${current ? ' settings-nav-item--active' : ''}${done ? ' is-done' : ''}`}
              onClick={() => setProgressFor(active.id, { ...progressFor(active.id), currentStepId: step.id })}
              aria-current={current ? 'step' : undefined}
            >
              <span className="training-step-item__num">{done ? '✓' : number}</span>
              <span className="training-step-item__label">{step.title}</span>
            </button>
          );
        })}
      </div>
    </LeftRail>
  ) : active ? (
    <LeftRail
      title="Modules"
      ariaLabel={`${active.title} modules`}
      className="settings-section-nav"
      headerAction={
        <button type="button" className="training-rail-back" onClick={() => setActiveId(null)}>
          All
        </button>
      }
    >
      {modulesByLevel(active).map((group) => (
        <div key={group.level} className="settings-nav-group">
          <div className="settings-nav-group-title">{group.level}</div>
          {group.items.map(({ module, items }) => {
            const done = items.filter(({ step }) => isStepComplete(progressFor(active.id), step.id)).length;
            return (
              <button
                key={module.section}
                type="button"
                className="settings-nav-item training-module-item"
                onClick={() => {
                  setOpenSection(module.section);
                  // Land on the module's first step rather than wherever the
                  // learner last was elsewhere in the course.
                  setProgressFor(active.id, { ...progressFor(active.id), currentStepId: items[0].step.id });
                }}
              >
                <span className="training-module-item__name">{module.section}</span>
                <span className="training-module-item__meta">
                  {items.length} steps · {module.minutes} min{done > 0 ? ` · ${done}/${items.length} done` : ''}
                </span>
              </button>
            );
          })}
        </div>
      ))}
    </LeftRail>
  ) : (
    <LeftRail title="Training" ariaLabel="Tutorials" className="settings-section-nav">
      {TUTORIALS.length === 0 ? (
        <p className="training-rail-empty">No tutorials yet.</p>
      ) : (
        <div className="settings-nav-group">
          <div className="settings-nav-group-title">Courses</div>
          {TUTORIALS.map((t) => (
            <button
              key={t.id}
              type="button"
              className="settings-nav-item training-module-item"
              onClick={() => openTutorial(t.id)}
            >
              <span className="training-module-item__name">{t.title}</span>
              <span className="training-module-item__meta">
                {modulesWithSteps(t).length} modules · {percentComplete(t, progressFor(t.id))}%
              </span>
            </button>
          ))}
        </div>
      )}
    </LeftRail>
  );

  return (
    <ViewPanel name="training">
      <ResizablePanels id="training" direction="horizontal" initialSizes={[24, 76]} minSize={200}>
        {rail}
        <main className="view-main training-main">
          {active && openModule ? (
            // The runner is scoped to ONE module: its step count, its Previous
            // and Next, its completion panel. Progress stays keyed by step id,
            // so finishing a module leaves the rest of the course untouched.
            <TutorialRunner
              tutorial={{ ...active, title: `${active.title} — ${openModule.module.title}`, steps: openModule.items.map((i) => i.step) }}
              progress={progressFor(active.id)}
              onProgressChange={(next) => setProgressFor(active.id, next)}
              onNavigate={onNavigate}
              onStartGuide={onStartGuide}
              modelSummary={modelSummary}
              onClearModel={onClearModel}
              onLoadExample={onLoadExample}
              onExit={() => setOpenSection(null)}
              onReset={() => setProgressFor(active.id, emptyProgress())}
            />
          ) : (
            <TutorialCatalog
              tutorials={TUTORIALS}
              progressById={progressFor}
              onStart={openTutorial}
            />
          )}
        </main>
      </ResizablePanels>
    </ViewPanel>
  );
}
