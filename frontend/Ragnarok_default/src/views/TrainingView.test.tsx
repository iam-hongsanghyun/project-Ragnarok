/**
 * Leaving Training mid-step and pressing "Back to tutorial" returns to the same
 * module and step — not the Training front page.
 *
 * The harness mirrors how App wires Training: the view is mounted only while
 * the Training tab is showing, its state lives in `ragnarok:training:*`
 * persisted keys, and the top-bar chip resolves where to go with `resumeTarget`.
 */
import React, { useState } from 'react';
import { afterEach, beforeEach, describe, expect, it } from '@jest/globals';
import { TrainingView } from './TrainingView';
import { button, click, mount, type Mounted } from '../shared/testing/dom';
import { usePersistedState } from '../shared/hooks/usePersistedState';
import { TUTORIALS, modulesWithSteps, resumeTarget } from 'lib/training/catalog';
import { emptyProgress } from 'lib/training/progress';
import type { TutorialProgress } from 'lib/training/types';

const course = TUTORIALS[0];
const modules = modulesWithSteps(course);
// A module with enough steps to stop part-way through, and not the first one,
// so landing on the right module is not a coincidence of order.
const target = modules.find((m, i) => i > 0 && m.items.length >= 4)!;

function Harness() {
  const [tab, setTab] = useState<string>('Training');
  const [activeId, setActiveId] = usePersistedState<string | null>('ragnarok:training:active', null);
  const [progress, setProgress] = usePersistedState<Record<string, TutorialProgress>>('ragnarok:training:progress', {});
  const [section, setSection] = usePersistedState<string | null>('ragnarok:training:section', null);
  return (
    <>
      {/* Stands in for the activity bar: leave Training from anywhere. */}
      <button type="button" onClick={() => setTab('Build')}>Activity: Build</button>
      {tab !== 'Training' && activeId && (
        <button
          type="button"
          onClick={() => {
            setSection(resumeTarget(course, progress[course.id] ?? emptyProgress()).section);
            setTab('Training');
          }}
        >
          Back to tutorial
        </button>
      )}
      {tab === 'Training' && (
        <TrainingView
          onNavigate={(t) => setTab(t)}
          onStartGuide={() => undefined}
          activeId={activeId}
          onActiveIdChange={setActiveId}
          progressById={progress}
          onProgressByIdChange={setProgress}
          openSection={section}
          onOpenSectionChange={setSection}
          modelSummary={{ filename: 'x.xlsx', buses: 0, generators: 0, loads: 0, snapshots: 0 }}
          onClearModel={() => undefined}
          onLoadExample={() => undefined}
        />
      )}
    </>
  );
}

const stepTitle = (c: HTMLElement) => c.querySelector('.training-step__title')?.textContent;
const stepCounter = (c: HTMLElement) => c.querySelector('.training-progress__text')?.textContent ?? '';
const moduleButton = (c: HTMLElement, title: string) => Array.from(c.querySelectorAll('button.training-module-item'))
  .find((b) => b.querySelector('.training-module-item__name')?.textContent === title) ?? null;

let mounted: Mounted | null = null;
beforeEach(() => window.localStorage.clear());
afterEach(async () => { await mounted?.unmount(); mounted = null; });

/** Open the target module and walk to its third step. */
async function goToThirdStep(c: HTMLElement) {
  await click(moduleButton(c, target.module.title));
  await click(button(c, 'Next'));
  await click(button(c, 'Next'));
  expect(stepTitle(c)).toBe(target.items[2].step.title);
  expect(stepCounter(c)).toContain(`Step 3 of ${target.items.length}`);
}

describe('Training: leave a step, then Back to tutorial', () => {
  it('returns to the same module and step', async () => {
    mounted = await mount(<Harness />);
    const c = mounted.container;
    await goToThirdStep(c);

    // Leave Training to do the work — the view unmounts.
    await click(button(c, /^Open /));
    expect(c.querySelector('.training-main')).toBeNull();

    await click(button(c, 'Back to tutorial'));
    expect(c.querySelector('.training-catalog')).toBeNull();
    expect(stepTitle(c)).toBe(target.items[2].step.title);
    expect(stepCounter(c)).toContain(`Step 3 of ${target.items.length}`);
  });

  it('returns to the step even after going back to the module list first', async () => {
    mounted = await mount(<Harness />);
    const c = mounted.container;
    await goToThirdStep(c);
    await click(button(c, '← All modules'));
    await click(button(c, 'Activity: Build'));
    await click(button(c, 'Back to tutorial'));
    expect(stepTitle(c)).toBe(target.items[2].step.title);
  });

  it('re-entering a module from the list resumes its step rather than restarting it', async () => {
    mounted = await mount(<Harness />);
    const c = mounted.container;
    await goToThirdStep(c);
    await click(button(c, '← All modules'));
    await click(moduleButton(c, target.module.title));
    expect(stepTitle(c)).toBe(target.items[2].step.title);
  });

  it('survives a full reload: the module and step come back from storage', async () => {
    mounted = await mount(<Harness />);
    await goToThirdStep(mounted.container);
    await mounted.unmount();
    mounted = await mount(<Harness />);
    expect(stepTitle(mounted.container)).toBe(target.items[2].step.title);
  });
});
