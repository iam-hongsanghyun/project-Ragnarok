/** "Take the tour" entry: starts, restarts, or resumes the guided tour. */
import React, { useSyncExternalStore } from 'react';
import { indexOfStep } from './engine';
import { TOUR_STEPS } from './steps';
import { tourStore } from './store';

export function TourButton({ className = 'tb-btn tb-btn--muted' }: { className?: string }) {
  const persisted = useSyncExternalStore(tourStore.subscribe, tourStore.get);
  if (persisted.status === 'active') return null;
  const resumeAt = persisted.status === 'paused' && persisted.stepId ? indexOfStep(TOUR_STEPS, persisted.stepId) : 0;
  const resuming = resumeAt > 0;
  return (
    <button
      type="button"
      className={className}
      data-tour="tour-button"
      onClick={() => tourStore.begin(TOUR_STEPS[resuming ? resumeAt : 0].id)}
      title={resuming
        ? 'Continue the guided tour where you left it'
        : 'A guided walkthrough of the core loop: build, edit, run, analyse'}
    >
      {resuming ? `Resume tour (${resumeAt + 1}/${TOUR_STEPS.length})` : 'Take the tour'}
    </button>
  );
}
