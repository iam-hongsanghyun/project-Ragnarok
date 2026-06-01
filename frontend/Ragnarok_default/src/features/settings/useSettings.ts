import { useState, useCallback } from 'react';
import type { AppSettings } from 'lib/settings/types';
import { SETTINGS_CONFIG, SETTINGS_DEFAULTS } from 'lib/constants';

export type { DateFormat, SolverType, AppSettings } from 'lib/settings/types';

const STORAGE_KEY = SETTINGS_CONFIG.storageKey;

// One-time migration marker. The legacy build hard-defaulted `solverType` to
// 'simplex', which pins HiGHS to a slower LP method; the default is now 'auto'
// (HiGHS chooses the fastest path). Browsers that ran the old build still have
// 'simplex' persisted — which overrides the new default and keeps solves slow —
// so rewrite it to 'auto' exactly once. A later *deliberate* 'simplex' choice
// then sticks, because the marker is set after the migration runs.
const SOLVER_AUTO_MIGRATION_KEY = `${STORAGE_KEY}:migrated_solver_auto`;

function loadSettings(): AppSettings {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw) as Partial<AppSettings>;
      let solverType = parsed.solverType ?? SETTINGS_DEFAULTS.solverType;
      let migrated = false;
      if (!localStorage.getItem(SOLVER_AUTO_MIGRATION_KEY)) {
        if (solverType === 'simplex') {
          solverType = 'auto';
          migrated = true;
        }
        localStorage.setItem(SOLVER_AUTO_MIGRATION_KEY, '1');
      }
      const settings: AppSettings = {
        dateFormat: parsed.dateFormat ?? SETTINGS_DEFAULTS.dateFormat,
        solverThreads: parsed.solverThreads ?? SETTINGS_DEFAULTS.solverThreads,
        solverType,
        currencyCode: parsed.currencyCode ?? SETTINGS_DEFAULTS.currencyCode,
        currencySymbol: parsed.currencySymbol ?? SETTINGS_DEFAULTS.currencySymbol,
        enableLoadShedding: parsed.enableLoadShedding ?? SETTINGS_DEFAULTS.enableLoadShedding,
        loadSheddingCost: parsed.loadSheddingCost ?? SETTINGS_DEFAULTS.loadSheddingCost,
        discountRate: parsed.discountRate ?? SETTINGS_DEFAULTS.discountRate,
      };
      // Persist only when the migration actually changed the value, so the
      // run payload (which reads from here) sends 'auto' even if the user
      // never opens Settings.
      if (migrated) saveSettings(settings);
      return settings;
    }
    // Fresh install: defaults already provide 'auto'; record the migration so
    // it never runs once the user starts saving settings.
    localStorage.setItem(SOLVER_AUTO_MIGRATION_KEY, '1');
  } catch {
    // ignore
  }
  return { ...SETTINGS_DEFAULTS };
}

function saveSettings(s: AppSettings): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(s));
  } catch {
    // ignore
  }
}

export function useSettings(): [AppSettings, (patch: Partial<AppSettings>) => void] {
  const [settings, setSettings] = useState<AppSettings>(loadSettings);

  const updateSettings = useCallback((patch: Partial<AppSettings>) => {
    setSettings((prev) => {
      const next = { ...prev, ...patch };
      saveSettings(next);
      return next;
    });
  }, []);

  return [settings, updateSettings];
}
