import { useCallback, useEffect, useRef, useState } from 'react';

export type FetchState<T> = {
  loading: boolean;
  error: string | null;
  data: T | null;
  reload: () => void;
};

/**
 * Region-scoped fetch hook. Re-fetches when `name` changes, and provides a
 * `reload()` callback that re-runs the fetcher with the current name.
 *
 * - When `name === null`, the hook is idle: no fetch runs and state is reset
 *   to `{loading: false, error: null, data: null}`.
 * - In-flight fetches are cancelled when `name` changes or the component
 *   unmounts (via a closure `cancelled` flag plus a `mountedRef`). Late
 *   resolutions are dropped — no `setState` after unmount.
 */
export function useRegionFetch<T>(
  name: string | null,
  fetcher: (name: string) => Promise<T>,
): FetchState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [reloadTick, setReloadTick] = useState(0);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  useEffect(() => {
    if (name == null) {
      // Idle: clear state, do not fetch.
      setData(null);
      setError(null);
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetcher(name)
      .then((d) => {
        if (cancelled || !mountedRef.current) return;
        setData(d);
        setLoading(false);
      })
      .catch((e: unknown) => {
        if (cancelled || !mountedRef.current) return;
        const msg = e instanceof Error ? e.message : String(e);
        setError(msg);
        setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [name, fetcher, reloadTick]);

  const reload = useCallback(() => setReloadTick((n) => n + 1), []);
  return { loading, error, data, reload };
}
