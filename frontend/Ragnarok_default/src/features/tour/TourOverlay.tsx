/**
 * TourOverlay - the spotlight ring and the step card.
 *
 * Reuses the Training walkthrough's `.spotlight-*` styles. It is a separate component
 * because the tour needs what that overlay does not: waiting on app state, persisted
 * progress, and a card that survives its target being absent or off-screen.
 *
 * The dimming is one pointer-transparent box-shadow, so the ringed control stays
 * clickable; only the card takes pointer events.
 */
import React, { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import type { TourStep } from './engine';
import { placeCard, type Box } from './placement';

interface Props {
  step: TourStep;
  /** Re-run the scroll-into-view when the step changes, even to the same target. */
  seq: number;
  /** "3 / 11". */
  progress: string;
  canGoBack: boolean;
  isLast: boolean;
  /** The step's action is satisfied (or it has none): primary button reads Next. */
  satisfied: boolean;
  onNext: () => void;
  onBack: () => void;
  onSkip: () => void;
}

const PAD = 6;
const CARD_W = 340;
const FALLBACK_CARD_H = 200;

const sameBox = (a: Box | null, b: Box | null): boolean => {
  if (!a || !b) return a === b;
  return Math.abs(a.top - b.top) < 0.5 && Math.abs(a.left - b.left) < 0.5
    && Math.abs(a.width - b.width) < 0.5 && Math.abs(a.height - b.height) < 0.5;
};

const inView = (r: DOMRect): boolean =>
  r.width > 0 && r.height > 0 && r.top >= 0 && r.left >= 0
  && r.bottom <= window.innerHeight && r.right <= window.innerWidth;

export function TourOverlay({ step, seq, progress, canGoBack, isLast, satisfied, onNext, onBack, onSkip }: Props) {
  const [box, setBox] = useState<Box | null>(null);
  const [cardH, setCardH] = useState(FALLBACK_CARD_H);
  const [, setViewportTick] = useState(0);
  const boxRef = useRef<Box | null>(null);
  const cardRef = useRef<HTMLDivElement | null>(null);

  // Track the target every frame: its view re-lays out for reasons the tour cannot
  // subscribe to (panel drags, data arriving, a dialog opening). State is set only when
  // the rectangle actually moved. A target that has not mounted yet (a view still
  // switching) is simply retried on the next frame.
  useLayoutEffect(() => {
    let raf = 0;
    let scrolledFor: Element | null = null;
    const measure = () => {
      const el = step.target ? document.querySelector(`[data-tour="${step.target}"]`) : null;
      if (!el) {
        scrolledFor = null;
        if (boxRef.current !== null) { boxRef.current = null; setBox(null); }
      } else {
        let r = el.getBoundingClientRect();
        // Bring an off-screen target into view once per appearance; a target taller than
        // the viewport is aligned to its top instead of centred.
        if (scrolledFor !== el && !inView(r)) {
          el.scrollIntoView({ block: r.height > window.innerHeight ? 'start' : 'center', inline: 'nearest' });
          r = el.getBoundingClientRect();
        }
        scrolledFor = el;
        const next: Box = { top: r.top, left: r.left, width: r.width, height: r.height };
        if (!sameBox(boxRef.current, next)) { boxRef.current = next; setBox(next); }
      }
      raf = window.requestAnimationFrame(measure);
    };
    measure();
    return () => window.cancelAnimationFrame(raf);
  }, [step.target, seq]);

  // The card is placed from the viewport size, so a window resize must re-render it.
  useEffect(() => {
    const onResize = () => setViewportTick((n) => n + 1);
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);

  useLayoutEffect(() => {
    const h = cardRef.current?.offsetHeight;
    if (h && Math.abs(h - cardH) > 1) setCardH(h);
  }, [cardH, step.id, step.action, satisfied, canGoBack]);

  const vp = { width: window.innerWidth, height: window.innerHeight };
  const width = Math.min(CARD_W, vp.width - 24);
  const pos = placeCard(box, { width, height: cardH }, vp);
  // Steps with no control to ring (intro, finish) dim the page; a step whose control is
  // not on screen yet leaves the page undimmed so the user can still navigate to it.
  const dimAll = !step.target;

  return createPortal(
    <div className="spotlight-layer tour-layer" role="dialog" aria-label="Guided tour" aria-live="polite">
      {dimAll && <div className="tour-dim" />}
      {box && (
        <div
          className="spotlight-ring"
          style={{ top: box.top - PAD, left: box.left - PAD, width: box.width + PAD * 2, height: box.height + PAD * 2 }}
        />
      )}
      <div ref={cardRef} className="spotlight-callout tour-card" style={{ top: pos.top, left: pos.left, width }}>
        <div className="spotlight-callout__head">
          <span className="spotlight-callout__count">{progress}</span>
          <button type="button" className="spotlight-callout__close" onClick={onSkip} aria-label="Leave the tour (Esc)">
            Skip tour
          </button>
        </div>
        <h4 className="spotlight-callout__title">{step.title}</h4>
        <p className="spotlight-callout__note">{step.body}</p>
        {step.action && (
          <p className={`tour-action${satisfied ? ' tour-action--done' : ''}`}>
            {satisfied ? 'Done. ' : 'Your turn: '}{step.action}
          </p>
        )}
        <div className="spotlight-callout__foot">
          {canGoBack && (
            <button type="button" className="tb-btn tb-btn--muted" onClick={onBack}>Back</button>
          )}
          <button type="button" className="tb-btn tb-btn--primary" onClick={onNext}>
            {isLast ? 'Finish' : satisfied ? 'Next' : 'Skip step'}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
