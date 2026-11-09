import { useCallback, useEffect, useRef, useState } from 'react';
import { errorMessage } from '../lib/api';

export interface Resource<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
  updatedAt: number | null;
  refresh: () => Promise<void>;
}

/**
 * Minimal data loader: fetch on mount / when `key` changes, optional polling
 * that pauses while the tab is hidden. Keeps the last good data on error.
 */
export function useResource<T>(fetcher: () => Promise<T>, key: string, opts: { intervalMs?: number; onError?: (msg: string) => void } = {}): Resource<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [updatedAt, setUpdatedAt] = useState<number | null>(null);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;
  const onErrorRef = useRef(opts.onError);
  onErrorRef.current = opts.onError;
  const seq = useRef(0);
  const lastError = useRef<string | null>(null);

  const load = useCallback(async () => {
    const mine = ++seq.current;
    try {
      const d = await fetcherRef.current();
      if (mine !== seq.current) return;
      setData(d);
      setError(null);
      lastError.current = null;
      setUpdatedAt(Date.now());
    } catch (err) {
      if (mine !== seq.current) return;
      const msg = errorMessage(err);
      setError(msg);
      if (lastError.current !== msg) onErrorRef.current?.(msg); // don't toast the same failure every poll
      lastError.current = msg;
    } finally {
      if (mine === seq.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    setLoading(true);
    void load();
  }, [key, load]);

  useEffect(() => {
    if (!opts.intervalMs) return;
    const id = setInterval(() => {
      if (document.visibilityState === 'visible') void load();
    }, opts.intervalMs);
    const onVis = () => document.visibilityState === 'visible' && void load();
    document.addEventListener('visibilitychange', onVis);
    return () => {
      clearInterval(id);
      document.removeEventListener('visibilitychange', onVis);
    };
  }, [opts.intervalMs, load]);

  return { data, error, loading, updatedAt, refresh: load };
}
