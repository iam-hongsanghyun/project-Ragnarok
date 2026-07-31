/**
 * SpotlightOverlay — rings a real element in the running app and annotates it.
 *
 * Rendered at the application root (not inside the Training view) so a
 * walkthrough survives switching views: a stop can carry a `tab`, the overlay
 * switches to it, and the ring follows the target into the new view.
 *
 * Two rules the implementation exists to keep:
 *
 *   • Never block input. The dimming is one `pointer-events: none` layer, so
 *     the highlighted control stays clickable and the user can do the thing
 *     they are being shown. Only the callout itself takes pointer events.
 *   • Never lie about the target. If a selector resolves to nothing the overlay
 *     says so instead of showing an empty ring somewhere plausible — a stale
 *     selector is a content bug and should be visible as one.
 */
import React, { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Spotlight } from 'lib/training/types';

interface Props {
  stops: Spotlight[];
  index: number;
  onIndexChange: (i: number) => void;
  onClose: () => void;
}

interface Rect { top: number; left: number; width: number; height: number }

const PAD = 6;          // ring inset around the target, px
const CALLOUT_W = 320;  // callout width, px — keep in sync with the stylesheet
const GAP = 12;         // gap between ring and callout, px

const sameRect = (a: Rect | null, b: Rect | null): boolean => {
  if (!a || !b) return a === b;
  return Math.abs(a.top - b.top) < 0.5 && Math.abs(a.left - b.left) < 0.5
    && Math.abs(a.width - b.width) < 0.5 && Math.abs(a.height - b.height) < 0.5;
};

export function SpotlightOverlay({ stops, index, onIndexChange, onClose }: Props) {
  const stop = stops[index];
  const [rect, setRect] = useState<Rect | null>(null);
  const [missing, setMissing] = useState(false);
  const rectRef = useRef<Rect | null>(null);

  // Track the target every frame rather than on scroll/resize events: targets
  // live in views that re-layout for reasons the overlay cannot subscribe to
  // (panel drags, async data landing, the rail expanding). A rAF loop that only
  // sets state when the rect actually moves is cheaper than getting this wrong.
  useLayoutEffect(() => {
    if (!stop) return undefined;
    let raf = 0;
    let firstScrollDone = false;

    const measure = () => {
      const el = document.querySelector(stop.selector);
      if (!el) {
        setMissing(true);
        if (rectRef.current !== null) { rectRef.current = null; setRect(null); }
      } else {
        setMissing(false);
        if (!firstScrollDone) {
          el.scrollIntoView({ block: 'nearest', inline: 'nearest' });
          firstScrollDone = true;
        }
        const r = el.getBoundingClientRect();
        const next: Rect = { top: r.top, left: r.left, width: r.width, height: r.height };
        if (!sameRect(rectRef.current, next)) { rectRef.current = next; setRect(next); }
      }
      raf = window.requestAnimationFrame(measure);
    };

    // Measure once synchronously before entering the loop: browsers pause rAF
    // in a background tab, so a walkthrough started while the tab is not
    // frontmost would otherwise render a callout with no ring at all.
    measure();
    return () => window.cancelAnimationFrame(raf);
  }, [stop]);

  const next = useCallback(() => {
    if (index + 1 < stops.length) onIndexChange(index + 1);
    else onClose();
  }, [index, stops.length, onIndexChange, onClose]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
      else if (e.key === 'ArrowRight') next();
      else if (e.key === 'ArrowLeft' && index > 0) onIndexChange(index - 1);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [next, onClose, onIndexChange, index]);

  if (!stop) return null;

  // Prefer below the target; flip above when there is no room. Clamp so the
  // callout never leaves the viewport on a narrow window.
  let calloutTop = 16;
  let calloutLeft = 16;
  if (rect) {
    const below = rect.top + rect.height + GAP;
    const wantsAbove = below + 190 > window.innerHeight;
    calloutTop = wantsAbove ? Math.max(12, rect.top - GAP - 190) : below;
    calloutLeft = Math.min(
      Math.max(12, rect.left + rect.width / 2 - CALLOUT_W / 2),
      Math.max(12, window.innerWidth - CALLOUT_W - 12),
    );
  }

  return createPortal(
    <div className="spotlight-layer" role="dialog" aria-label="Guided walkthrough">
      {rect && (
        <div
          className="spotlight-ring"
          style={{
            top: rect.top - PAD,
            left: rect.left - PAD,
            width: rect.width + PAD * 2,
            height: rect.height + PAD * 2,
          }}
        />
      )}

      <div className="spotlight-callout" style={{ top: calloutTop, left: calloutLeft }}>
        <div className="spotlight-callout__head">
          <span className="spotlight-callout__count">{index + 1} / {stops.length}</span>
          <button type="button" className="spotlight-callout__close" onClick={onClose} aria-label="End walkthrough">
            Close
          </button>
        </div>
        <h4 className="spotlight-callout__title">{stop.title}</h4>
        {stop.note && <p className="spotlight-callout__note">{stop.note}</p>}
        {missing && (
          // A target can be legitimately absent — a stop that rings something
          // inside a dialog needs that dialog open, and the overlay deliberately
          // does not open it. Say what is missing either way; a genuinely stale
          // selector then looks like what it is.
          <p className="spotlight-callout__missing">
            Not on screen right now (<code>{stop.selector}</code>). If this stop points inside a
            dialog or panel, open it first — the walkthrough never clicks for you — and the ring
            will appear.
          </p>
        )}
        <div className="spotlight-callout__foot">
          <button
            type="button"
            className="tb-btn"
            disabled={index === 0}
            onClick={() => onIndexChange(index - 1)}
          >
            Back
          </button>
          <button type="button" className="primary-button" onClick={next}>
            {index + 1 < stops.length ? 'Next' : 'Done'}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
