/**
 * TourHost - mounts once at the app root and drives the guided tour.
 *
 * Owns no step logic (see `engine.ts`): it feeds the engine the app state, applies the
 * view switch a step asks for, listens for keys, and persists progress. First run: when
 * nothing has been loaded and the Welcome page is showing, it OFFERS the tour once.
 */
import React, { useCallback, useEffect, useRef, useState, useSyncExternalStore } from 'react';
import { TourOverlay } from './TourOverlay';
import {
  back, enter, indexOfStep, isDone, next, progressLabel, settle,
  type TourContext, type TourRun,
} from './engine';
import { TOUR_STEPS } from './steps';
import { tourStore } from './store';

interface Props {
  ctx: TourContext;
  /** The boot check of the server session finished, so `ctx.hasModel` can be trusted. */
  ready: boolean;
  onNavigate: (tab: string) => void;
}

const isTyping = (t: EventTarget | null): boolean => {
  const el = t as HTMLElement | null;
  if (!el || !el.tagName) return false;
  return el.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName);
};

export function TourHost({ ctx, ready, onNavigate }: Props) {
  const persisted = useSyncExternalStore(tourStore.subscribe, tourStore.get);
  const [run, setRun] = useState<TourRun | null>(null);
  const ctxRef = useRef(ctx);
  ctxRef.current = ctx;
  const navigatedSeq = useRef(0);

  const active = persisted.status === 'active';

  // Commit a move: keep the run in state and the step id in storage.
  const commit = useCallback((target: TourRun | null) => {
    if (!target) {
      setRun(null);
      tourStore.set({ status: 'done', stepId: null });
      return;
    }
    setRun(target);
    tourStore.set({ status: 'active', stepId: TOUR_STEPS[target.index].id });
  }, []);

  // Started (or restored after a reload): enter the stored step.
  useEffect(() => {
    if (!active) { if (run) setRun(null); return; }
    if (!run) {
      const start = enter(TOUR_STEPS, indexOfStep(TOUR_STEPS, persisted.stepId), ctxRef.current, 'forward', null);
      commit(settle(TOUR_STEPS, start, ctxRef.current));
    }
  }, [active, run, persisted.stepId, commit]);

  // The app changed: an action step the user just completed advances the tour.
  useEffect(() => {
    if (!active || !run) return;
    const settled = settle(TOUR_STEPS, run, ctx);
    if (settled !== run) commit(settled);
  }, [active, run, ctx, commit]);

  // Show the view a step belongs to, once per arrival (never fight the user afterwards).
  const step = run ? TOUR_STEPS[run.index] : null;
  useEffect(() => {
    if (!run || !step || navigatedSeq.current === run.seq) return;
    navigatedSeq.current = run.seq;
    if (step.tab && step.tab !== ctxRef.current.tab) onNavigate(step.tab);
  }, [run, step, onNavigate]);

  const goNext = useCallback(() => {
    if (!run) return;
    commit(next(TOUR_STEPS, run, ctxRef.current));
  }, [run, commit]);
  const goBack = useCallback(() => {
    if (run && run.index > 0) commit(back(TOUR_STEPS, run, ctxRef.current));
  }, [run, commit]);
  const pause = useCallback(() => {
    setRun(null);
    tourStore.set({ status: 'paused', stepId: run ? TOUR_STEPS[run.index].id : persisted.stepId });
  }, [run, persisted.stepId]);

  useEffect(() => {
    if (!active) return undefined;
    const onKey = (e: KeyboardEvent) => {
      if (e.defaultPrevented) return;
      if (e.key === 'Escape') { pause(); return; }
      if (e.altKey || e.ctrlKey || e.metaKey || isTyping(e.target)) return;
      if (e.key === 'ArrowRight') goNext();
      else if (e.key === 'ArrowLeft') goBack();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [active, goNext, goBack, pause]);

  // First-run offer: only on the Welcome page of an empty editor, once the session check ran.
  const offer = !active && persisted.status === 'unseen' && ready && ctx.tab === 'Welcome' && !ctx.hasModel;
  useEffect(() => {
    if (!offer) return undefined;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !e.defaultPrevented) tourStore.set({ status: 'declined', stepId: null });
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [offer]);

  if (active && run && step) {
    return (
      <TourOverlay
        step={step}
        seq={run.seq}
        progress={progressLabel(TOUR_STEPS, run)}
        canGoBack={run.index > 0}
        isLast={run.index === TOUR_STEPS.length - 1}
        satisfied={isDone(step, ctx, run)}
        onNext={goNext}
        onBack={goBack}
        onSkip={pause}
      />
    );
  }
  if (offer) {
    return (
      <div className="tour-offer" role="dialog" aria-label="Take the tour">
        <h4 className="tour-offer__title">New to Ragnarok?</h4>
        <p className="tour-offer__body">
          A two-minute tour shows the core loop on an example network: build, edit, run, analyse.
          You can leave at any point and pick it up again from the top bar.
        </p>
        <div className="tour-offer__actions">
          <button type="button" className="tb-btn tb-btn--muted" onClick={() => tourStore.set({ status: 'declined', stepId: null })}>
            Not now
          </button>
          <button type="button" className="tb-btn tb-btn--primary" onClick={() => tourStore.begin(TOUR_STEPS[0].id)}>
            Start the tour
          </button>
        </div>
      </div>
    );
  }
  return null;
}
