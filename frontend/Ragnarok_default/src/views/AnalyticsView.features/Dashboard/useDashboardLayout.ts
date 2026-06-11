/**
 * Dashboard layout state hook with localStorage persistence.
 *
 * Owns the active layout plus a list of named saved layouts. Writes
 * back to localStorage on every change so the user gets autosave; named
 * layouts give them recall slots when they want to switch.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { DashboardLayout, NamedLayout, STORAGE_KEY } from 'lib/dashboard/types';

interface Stored {
  active: DashboardLayout;
  saved: NamedLayout[];
}

interface UseDashboardLayout {
  layout: DashboardLayout;
  setLayout: (next: DashboardLayout) => void;
  /** Edit-mode toggle (drag handles, resize bars, +/- buttons). */
  editing: boolean;
  setEditing: (v: boolean) => void;
  /** Named layouts the user has saved. */
  savedLayouts: NamedLayout[];
  saveAs: (name: string) => void;
  load: (name: string) => void;
  remove: (name: string) => void;
  resetToDefault: () => void;
}

function readStored(key: string): Stored | null {
  try {
    const raw = window.localStorage.getItem(key);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Stored;
    if (!parsed?.active?.rows || !Array.isArray(parsed.saved)) return null;
    return parsed;
  } catch {
    return null;
  }
}

function writeStored(key: string, value: Stored): void {
  try {
    window.localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* quota or privacy mode — silently drop */
  }
}

export function useDashboardLayout(
  defaultLayout: DashboardLayout,
  /** Pass `null` to disable persistence entirely — the layout is rebuilt from
   *  `defaultLayout` on every mount (used by the Result tab, whose curated
   *  preset must always reflect the current code, never a stale cache). */
  storageKey: string | null = STORAGE_KEY,
): UseDashboardLayout {
  const stored = useMemo(() => (storageKey ? readStored(storageKey) : null), [storageKey]);
  const [layout, setLayoutState] = useState<DashboardLayout>(stored?.active ?? defaultLayout);
  const [savedLayouts, setSavedLayouts] = useState<NamedLayout[]>(stored?.saved ?? []);
  const [editing, setEditing] = useState(false);

  // Autosave: debounce writes to localStorage so resize-drag doesn't write 60x/s.
  const writeTimer = useRef<number | null>(null);
  useEffect(() => {
    if (!storageKey) return;
    if (writeTimer.current !== null) window.clearTimeout(writeTimer.current);
    writeTimer.current = window.setTimeout(() => {
      writeStored(storageKey, { active: layout, saved: savedLayouts });
    }, 200);
    return () => {
      if (writeTimer.current !== null) window.clearTimeout(writeTimer.current);
    };
  }, [layout, savedLayouts, storageKey]);

  const setLayout = useCallback((next: DashboardLayout) => setLayoutState(next), []);

  const saveAs = useCallback((name: string) => {
    const trimmed = name.trim();
    if (!trimmed) return;
    setSavedLayouts((prev) => {
      const without = prev.filter((s) => s.name !== trimmed);
      return [...without, { name: trimmed, layout, updatedAt: Date.now() }];
    });
  }, [layout]);

  const load = useCallback((name: string) => {
    // Read savedLayouts directly — calling setLayoutState inside a
    // setSavedLayouts updater is a nested-update anti-pattern that React
    // can drop, which is why "Load" did nothing.
    const found = savedLayouts.find((s) => s.name === name);
    if (found) setLayoutState(found.layout);
  }, [savedLayouts]);

  const remove = useCallback((name: string) => {
    setSavedLayouts((prev) => prev.filter((s) => s.name !== name));
  }, []);

  const resetToDefault = useCallback(() => setLayoutState(defaultLayout), [defaultLayout]);

  return { layout, setLayout, editing, setEditing, savedLayouts, saveAs, load, remove, resetToDefault };
}
