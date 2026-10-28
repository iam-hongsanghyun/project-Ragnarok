/** Where the tour card goes relative to the ringed control — pure, so it is testable. */
export interface Box { top: number; left: number; width: number; height: number }

export interface Viewport { width: number; height: number }

const MARGIN = 12;

/**
 * Place a `card` beside `target`: below, above, right of, then left of it, whichever fits
 * the viewport first; when none does (a target that fills the screen) pin the card to the
 * bottom-right inside the viewport. Without a target the card is centred.
 */
export function placeCard(target: Box | null, card: { width: number; height: number }, vp: Viewport, gap = 14): { top: number; left: number } {
  const maxLeft = Math.max(MARGIN, vp.width - card.width - MARGIN);
  const maxTop = Math.max(MARGIN, vp.height - card.height - MARGIN);
  const clampLeft = (x: number) => Math.min(Math.max(MARGIN, x), maxLeft);
  const clampTop = (y: number) => Math.min(Math.max(MARGIN, y), maxTop);
  if (!target) {
    return { top: clampTop((vp.height - card.height) / 2), left: clampLeft((vp.width - card.width) / 2) };
  }
  const centreX = target.left + target.width / 2 - card.width / 2;
  const centreY = target.top + target.height / 2 - card.height / 2;
  const below = target.top + target.height + gap;
  if (below + card.height + MARGIN <= vp.height) return { top: below, left: clampLeft(centreX) };
  const above = target.top - gap - card.height;
  if (above >= MARGIN) return { top: above, left: clampLeft(centreX) };
  const right = target.left + target.width + gap;
  if (right + card.width + MARGIN <= vp.width) return { top: clampTop(centreY), left: right };
  const left = target.left - gap - card.width;
  if (left >= MARGIN) return { top: clampTop(centreY), left };
  return { top: maxTop, left: maxLeft };
}
