import { useState, useCallback } from 'react';
import type { AppSettings } from 'lib/settings/types';
import { SETTINGS_CONFIG, SETTINGS_DEFAULTS } from 'lib/constants';

export type { DateFormat, SolverType, AppSettings } from 'lib/settings/types';

const STORAGE_KEY = SETTINGS_CONFIG.storageKey;

function loadSettings(): AppSettings {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw) as Partial<AppSettings>;
      return {
        dateFormat: parsed.dateFormat ?? SETTINGS_DEFAULTS.dateFormat,
        solverThreads: parsed.solverThreads ?? SETTINGS_DEFAULTS.solverThreads,
        solverType: parsed.solverType ?? SETTINGS_DEFAULTS.solverType,
        currencyCode: parsed.currencyCode ?? SETTINGS_DEFAULTS.currencyCode,
        currencySymbol: parsed.currencySymbol ?? SETTINGS_DEFAULTS.currencySymbol,
        enableLoadShedding: parsed.enableLoadShedding ?? SETTINGS_DEFAULTS.enableLoadShedding,
        loadSheddingCost: parsed.loadSheddingCost ?? SETTINGS_DEFAULTS.loadSheddingCost,
        discountRate: parsed.discountRate ?? SETTINGS_DEFAULTS.discountRate,
      };
    }
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
