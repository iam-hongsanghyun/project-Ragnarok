import { useEffect, useState } from 'react';

/**
 * Returns a debounced copy of `value` that only updates after `ms` of quiet.
 * Use to keep expensive work (network fetches, localStorage writes, heavy
 * re-derivations) off the per-keystroke hot path while typing.
 */
export function useDebouncedValue<T>(value: T, ms: number): T {
  const [debounced, setDebounced] = useState<T>(value);
  useEffect(() => {
    const id = window.setTimeout(() => setDebounced(value), ms);
    return () => window.clearTimeout(id);
  }, [value, ms]);
  return debounced;
}
