import { Dispatch, SetStateAction, useCallback, useMemo } from 'react';
import { usePersistedState } from './usePersistedState';

/**
 * A Set<string> backed by localStorage. Stored as a JSON array (a Set is not
 * JSON-serialisable) and exposed as a Set at the boundary, so call sites keep
 * the useState<Set<string>> shape, including functional updates.
 */
export function usePersistedSet(
  key: string,
  initial: Iterable<string> = [],
): [Set<string>, Dispatch<SetStateAction<Set<string>>>] {
  const [items, setItems] = usePersistedState<string[]>(key, Array.from(initial));
  const value = useMemo(() => new Set(items), [items]);
  const setValue = useCallback<Dispatch<SetStateAction<Set<string>>>>(
    (next) => {
      setItems((prev) => {
        const resolved = typeof next === 'function' ? next(new Set(prev)) : next;
        return Array.from(resolved);
      });
    },
    [setItems],
  );
  return [value, setValue];
}
