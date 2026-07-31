/**
 * TutorialCatalog — the picker shown when no tutorial is running.
 *
 * One card per tutorial: what it teaches, what it assumes, how long it takes,
 * and how far through it you already are. Selecting a card starts the runner.
 */
import React from 'react';
import { Tutorial, TutorialProgress } from 'lib/training/types';
import { tutorialsByLevel } from 'lib/training/catalog';
import { percentComplete } from 'lib/training/progress';

interface Props {
  tutorials: Tutorial[];
  /** Progress per tutorial id, for the completion badge on each card. */
  progressById: (id: string) => TutorialProgress;
  onStart: (id: string) => void;
}

function TutorialCard({ tutorial, progress, onStart }: {
  tutorial: Tutorial;
  progress: TutorialProgress;
  onStart: () => void;
}) {
  const percent = percentComplete(tutorial, progress);
  const started = percent > 0;
  return (
    <article className="training-card">
      <header className="training-card__head">
        <h3 className="training-card__title">{tutorial.title}</h3>
        <div className="training-card__tags">
          <span className={`training-level training-level--${tutorial.level.toLowerCase()}`}>{tutorial.level}</span>
          <span className="training-card__minutes">{tutorial.minutes} min</span>
        </div>
      </header>

      <p className="training-card__summary">{tutorial.summary}</p>

      {tutorial.outcomes.length > 0 && (
        <div className="training-card__section">
          <h4>You will be able to</h4>
          <ul className="training-list">
            {tutorial.outcomes.map((o) => <li key={o}>{o}</li>)}
          </ul>
        </div>
      )}

      {tutorial.prerequisites.length > 0 && (
        <div className="training-card__section">
          <h4>Before you start</h4>
          <ul className="training-list">
            {tutorial.prerequisites.map((p) => <li key={p}>{p}</li>)}
          </ul>
        </div>
      )}

      <footer className="training-card__foot">
        <span className="training-card__steps">
          {tutorial.steps.length} steps{started ? ` · ${percent}% done` : ''}
        </span>
        <button type="button" className="primary-button" onClick={onStart}>
          {percent === 100 ? 'Review' : started ? 'Continue' : 'Start'}
        </button>
      </footer>
    </article>
  );
}

export function TutorialCatalog({ tutorials, progressById, onStart }: Props) {
  const groups = tutorialsByLevel(tutorials);

  return (
    <div className="training-catalog">
      <header className="training-catalog__intro">
        <h2>Training</h2>
        <p>
          Step-by-step walkthroughs of real Ragnarok workflows. Each step says where to be, explains
          what it is for, and lists the exact values to type, the files to import, and the run to start.
        </p>
        <p className="training-catalog__rule">
          Ragnarok never enters a value, imports a file, or starts a run on your behalf. The only thing
          a tutorial does to the app is open the view a step happens in — the work is yours, which is
          how it sticks.
        </p>
      </header>

      {groups.length === 0 ? (
        <div className="view-empty">
          <h3>No tutorials yet</h3>
          <p>Training sessions are being written and will appear here as they land.</p>
        </div>
      ) : (
        groups.map((group) => (
          <section key={group.level} className="training-catalog__group">
            <h3 className="training-catalog__level">{group.level}</h3>
            <div className="training-cards">
              {group.items.map((t) => (
                <TutorialCard
                  key={t.id}
                  tutorial={t}
                  progress={progressById(t.id)}
                  onStart={() => onStart(t.id)}
                />
              ))}
            </div>
          </section>
        ))
      )}
    </div>
  );
}
