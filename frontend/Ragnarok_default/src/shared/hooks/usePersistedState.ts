import { useEffect, useState } from 'react';

/**
 * useState backed by localStorage. Survives view remounts (so a tab's last
 * sub-section sticks when the user navigates away and back) and full page
 * reloads. The key is a string namespace; the initial value is used on the
 * very first run and whenever the stored JSON fails to parse.
 */
export function usePersistedState<T>(key: string, initial: T): [T, (v: T) => void] {
  const [value, setValue] = useState<T>(() => {
    try {
      const raw = window.localStorage.getItem(key);
      if (raw === null) return initial;
      return JSON.parse(raw) as T;
    } catch {
      return initial;
    }
  });
  useEffect(() => {
    try {
      window.localStorage.setItem(key, JSON.stringify(value));
    } catch {
      /* quota or privacy mode — ignore */
    }
  }, [key, value]);
  return [value, setValue];
}
