import { useEffect, useState } from 'react';

export interface AsyncState<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
}

/**
 * Run `load` whenever `key` changes and expose {data, loading, error}. A stale
 * response (the key changed while it was in flight) is dropped. `key = null`
 * means "nothing to load" (idle, no error). Callers put everything `load` reads
 * into `key`, so the effect depends on the key only.
 */
export function useAsync<T>(key: string | null, load: () => Promise<T>): AsyncState<T> {
  const [state, setState] = useState<AsyncState<T>>({ data: null, loading: key !== null, error: null });
  useEffect(() => {
    if (key === null) {
      setState({ data: null, loading: false, error: null });
      return;
    }
    let cancelled = false;
    setState((s) => ({ data: s.data, loading: true, error: null }));
    load().then(
      (data) => { if (!cancelled) setState({ data, loading: false, error: null }); },
      (e: unknown) => { if (!cancelled) setState({ data: null, loading: false, error: e instanceof Error ? e.message : String(e) }); },
    );
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `key` identifies the request
  }, [key]);
  return state;
}
