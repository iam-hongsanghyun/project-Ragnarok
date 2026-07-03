/**
 * Abstract-bus placement (M1 remainder) — put coordinate-less buses on the map.
 *
 * Sector-coupled models carry non-geographic buses (H₂, CO₂, heat) with no
 * x/y. Template-created carrier buses inherit their anchor's coordinates, but
 * hand-made or imported ones don't — and a bus without coordinates used to
 * vanish from the map, taking its conversion Links with it.
 *
 * Deterministic placement, no layout algorithm:
 *   1. A bus linked (via Links — the conversion edges) to a positioned bus is
 *      placed at a small NE offset from that anchor; several abstract buses on
 *      one anchor fan out in steps so they don't overlap.
 *   2. Chains (abstract → abstract → positioned) resolve over a few passes.
 *   3. Anything still unplaced lands in a tidy column just east of the
 *      network's bounding box (or a column from the origin when nothing has
 *      coordinates at all).
 *
 * Pure over row dicts; unit-tested directly. The maps mark placed buses with
 * `__abstract` so they can style them distinctly.
 */
import type { GridRow } from 'lib/types';

const ANCHOR_OFFSET = 0.15;   // degrees NE of the anchor for the first bus
const STACK_STEP = 0.12;      // extra step per additional bus on the same anchor
const EDGE_GAP = 0.6;         // column distance east of the bounding box
const EDGE_STEP = 0.25;       // vertical step within the edge column
const MAX_PASSES = 4;         // chain-resolution depth

interface Point { x: number; y: number }

function finite(v: unknown): number | null {
  if (v === null || v === undefined || v === '') return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

function coords(row: GridRow): Point | null {
  const x = finite(row.x);
  const y = finite(row.y);
  return x !== null && y !== null ? { x, y } : null;
}

/** Synthetic positions for every coordinate-less bus. */
export function placeAbstractBuses(
  buses: GridRow[],
  links: GridRow[],
): { placed: Record<string, Point>; abstract: string[] } {
  const positioned: Record<string, Point> = {};
  const pending: string[] = [];
  for (const bus of buses) {
    const name = String(bus.name ?? '');
    if (!name) continue;
    const c = coords(bus);
    if (c) positioned[name] = c;
    else pending.push(name);
  }
  if (pending.length === 0) return { placed: {}, abstract: [] };

  // Neighbour map from Links (conversion edges are Links, not Lines).
  const neighbours: Record<string, string[]> = {};
  for (const link of links) {
    const a = String(link.bus0 ?? '');
    const b = String(link.bus1 ?? '');
    if (!a || !b) continue;
    (neighbours[a] ??= []).push(b);
    (neighbours[b] ??= []).push(a);
  }

  const placed: Record<string, Point> = {};
  const anchorCount: Record<string, number> = {};
  const resolved = (name: string): Point | undefined => positioned[name] ?? placed[name];

  let remaining = [...pending];
  for (let pass = 0; pass < MAX_PASSES && remaining.length; pass++) {
    const next: string[] = [];
    for (const name of remaining) {
      const anchorName = (neighbours[name] ?? []).find((n) => resolved(n));
      const anchor = anchorName ? resolved(anchorName) : undefined;
      if (anchor && anchorName) {
        const k = anchorCount[anchorName] ?? 0;
        anchorCount[anchorName] = k + 1;
        placed[name] = { x: anchor.x + ANCHOR_OFFSET + k * STACK_STEP, y: anchor.y + ANCHOR_OFFSET + k * STACK_STEP };
      } else {
        next.push(name);
      }
    }
    if (next.length === remaining.length) { remaining = next; break; }
    remaining = next;
  }

  // Unanchored leftovers: a column east of the bounding box (or from origin).
  if (remaining.length) {
    const all = Object.values(positioned).concat(Object.values(placed));
    const maxX = all.length ? Math.max(...all.map((p) => p.x)) : 0;
    const maxY = all.length ? Math.max(...all.map((p) => p.y)) : 0;
    remaining.forEach((name, i) => {
      placed[name] = { x: maxX + EDGE_GAP, y: maxY - i * EDGE_STEP };
    });
  }
  return { placed, abstract: Object.keys(placed) };
}
