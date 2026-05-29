import React, { useCallback, useEffect, useRef, useState } from 'react';

type Direction = 'horizontal' | 'vertical';

interface ResizablePanelsProps {
  /** Stable key used to persist panel sizes in localStorage. */
  id: string;
  direction: Direction;
  /** One element per panel. Falsy children (e.g. a conditional panel) are dropped. */
  children: React.ReactNode;
  /** Default sizes as percentages summing to 100; falls back to equal split. */
  initialSizes?: number[];
  /** Minimum panel size in px, enforced while dragging. */
  minSize?: number;
  className?: string;
}

const STORAGE_PREFIX = 'pypsa.panelSizes.';

function normalize(sizes: number[]): number[] {
  const total = sizes.reduce((s, v) => s + v, 0);
  if (total <= 0) return sizes.map(() => 100 / sizes.length);
  return sizes.map((v) => (v / total) * 100);
}

function loadSizes(id: string, count: number): number[] | null {
  try {
    const raw = localStorage.getItem(STORAGE_PREFIX + id);
    if (!raw) return null;
    const arr = JSON.parse(raw);
    if (Array.isArray(arr) && arr.length === count && arr.every((n) => typeof n === 'number' && Number.isFinite(n))) {
      return normalize(arr);
    }
  } catch {
    /* ignore malformed storage */
  }
  return null;
}

/**
 * Flexbox split container with draggable gutters between panels. Widths
 * (horizontal) or heights (vertical) are stored as percentages and persisted
 * to localStorage under `id`, so a user's layout survives view switches and
 * full reloads. Nest two instances (one of each direction) for 2-D layouts.
 */
export function ResizablePanels({
  id,
  direction,
  children,
  initialSizes,
  minSize = 140,
  className,
}: ResizablePanelsProps) {
  const horizontal = direction === 'horizontal';
  const panels = React.Children.toArray(children).filter(Boolean);
  const n = panels.length;

  const containerRef = useRef<HTMLDivElement>(null);
  const sizesRef = useRef<number[]>([]);
  const dragRef = useRef<{ index: number; startPos: number; startSizes: number[]; total: number } | null>(null);

  const computeDefault = useCallback((): number[] => {
    const saved = loadSizes(id, n);
    if (saved) return saved;
    if (initialSizes && initialSizes.length === n) return normalize(initialSizes);
    return Array(n).fill(100 / n);
  }, [id, n, initialSizes]);

  const [sizes, setSizes] = useState<number[]>(computeDefault);

  // Re-seed when the panel count changes (e.g. a conditional panel appears).
  useEffect(() => {
    if (sizes.length !== n) setSizes(computeDefault());
  }, [n, sizes.length, computeDefault]);

  useEffect(() => { sizesRef.current = sizes; }, [sizes]);

  const persist = useCallback((s: number[]) => {
    try { localStorage.setItem(STORAGE_PREFIX + id, JSON.stringify(s)); } catch { /* ignore */ }
  }, [id]);

  const onPointerDown = (index: number) => (e: React.PointerEvent) => {
    if (!containerRef.current) return;
    e.preventDefault();
    const rect = containerRef.current.getBoundingClientRect();
    const total = horizontal ? rect.width : rect.height;
    dragRef.current = {
      index,
      startPos: horizontal ? e.clientX : e.clientY,
      startSizes: [...sizesRef.current],
      total,
    };
    (e.currentTarget as Element).setPointerCapture(e.pointerId);
  };

  const onPointerMove = (e: React.PointerEvent) => {
    const d = dragRef.current;
    if (!d || d.total <= 0) return;
    const pos = horizontal ? e.clientX : e.clientY;
    const deltaPct = ((pos - d.startPos) / d.total) * 100;
    const minPct = (minSize / d.total) * 100;
    let a = d.startSizes[d.index] + deltaPct;
    let b = d.startSizes[d.index + 1] - deltaPct;
    if (a < minPct) { b -= minPct - a; a = minPct; }
    if (b < minPct) { a -= minPct - b; b = minPct; }
    const next = [...d.startSizes];
    next[d.index] = a;
    next[d.index + 1] = b;
    setSizes(next);
  };

  const endDrag = () => {
    if (dragRef.current) {
      dragRef.current = null;
      persist(sizesRef.current);
    }
  };

  // Double-click a gutter to reset to the default split.
  const resetSizes = () => {
    try { localStorage.removeItem(STORAGE_PREFIX + id); } catch { /* ignore */ }
    const def = initialSizes && initialSizes.length === n ? normalize(initialSizes) : Array(n).fill(100 / n);
    setSizes(def);
  };

  if (n === 0) return null;
  if (n === 1) return <>{panels[0]}</>;

  return (
    <div ref={containerRef} className={`rzp ${horizontal ? 'rzp-h' : 'rzp-v'}${className ? ' ' + className : ''}`}>
      {panels.map((panel, i) => (
        <React.Fragment key={i}>
          <div className="rzp-panel" style={{ flexBasis: `${sizes[i] ?? 100 / n}%` }}>
            {panel}
          </div>
          {i < n - 1 && (
            <div
              className="rzp-gutter"
              role="separator"
              aria-orientation={horizontal ? 'vertical' : 'horizontal'}
              onPointerDown={onPointerDown(i)}
              onPointerMove={onPointerMove}
              onPointerUp={endDrag}
              onPointerCancel={endDrag}
              onDoubleClick={resetSizes}
              title="Drag to resize · double-click to reset"
            />
          )}
        </React.Fragment>
      ))}
    </div>
  );
}
