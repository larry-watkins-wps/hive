import { useCallback, useEffect, useRef, useState } from 'react';
import { fetchAppendix, RestError } from '../api/rest';

type HookState = {
  loading: boolean;
  error: Error | null;
  data: string | null;   // '' = intentional empty (404); null = not loaded yet
  reload: () => void;
};

export function useRegionAppendix(name: string | null): HookState {
  const [loading, setLoading] = useState<boolean>(name != null);
  const [error, setError] = useState<Error | null>(null);
  const [data, setData] = useState<string | null>(null);
  const reqId = useRef(0);

  const load = useCallback(async () => {
    if (name == null) return;
    const id = ++reqId.current;
    setLoading(true);
    setError(null);
    try {
      const text = await fetchAppendix(name);
      if (id !== reqId.current) return;
      setData(text);
    } catch (e) {
      if (id !== reqId.current) return;
      if (e instanceof RestError && e.status === 404) {
        setData('');
      } else {
        setError(e instanceof Error ? e : new Error(String(e)));
        setData(null);
      }
    } finally {
      if (id === reqId.current) setLoading(false);
    }
  }, [name]);

  useEffect(() => { void load(); }, [load]);

  return { loading, error, data, reload: () => void load() };
}
