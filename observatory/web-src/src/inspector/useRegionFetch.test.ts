import { describe, it, expect, vi } from 'vitest';
import { act, renderHook, waitFor } from '@testing-library/react';
import { useRegionFetch } from './useRegionFetch';

describe('useRegionFetch', () => {
  it('returns data on success', async () => {
    const fetcher = vi.fn(async (n: string) => `data for ${n}`);
    const { result } = renderHook(() => useRegionFetch('foo', fetcher));
    await waitFor(() => expect(result.current.data).toBe('data for foo'));
    expect(result.current.loading).toBe(false);
    expect(result.current.error).toBeNull();
    expect(fetcher).toHaveBeenCalledWith('foo');
  });

  it('captures error message on fetcher rejection', async () => {
    const fetcher = vi.fn(async () => {
      throw new Error('boom');
    });
    const { result } = renderHook(() => useRegionFetch('foo', fetcher));
    await waitFor(() => expect(result.current.error).toBe('boom'));
    expect(result.current.loading).toBe(false);
    expect(result.current.data).toBeNull();
  });

  it('coerces non-Error rejections to strings', async () => {
    const fetcher = vi.fn(async () => {
      // eslint-disable-next-line @typescript-eslint/no-throw-literal
      throw 'plain string';
    });
    const { result } = renderHook(() => useRegionFetch('foo', fetcher));
    await waitFor(() => expect(result.current.error).toBe('plain string'));
  });

  it('stays idle when name is null', async () => {
    const fetcher = vi.fn(async () => 'x');
    const { result } = renderHook(() => useRegionFetch<string>(null, fetcher));
    // A microtask to let any mis-wired effect fire.
    await Promise.resolve();
    expect(fetcher).not.toHaveBeenCalled();
    expect(result.current.loading).toBe(false);
    expect(result.current.data).toBeNull();
    expect(result.current.error).toBeNull();
  });

  it('clears data/error when name flips to null', async () => {
    const fetcher = vi.fn(async (n: string) => `d-${n}`);
    const { result, rerender } = renderHook(
      ({ name }: { name: string | null }) => useRegionFetch(name, fetcher),
      { initialProps: { name: 'foo' as string | null } },
    );
    await waitFor(() => expect(result.current.data).toBe('d-foo'));
    rerender({ name: null });
    expect(result.current.data).toBeNull();
    expect(result.current.error).toBeNull();
    expect(result.current.loading).toBe(false);
  });

  it('re-fetches when name changes', async () => {
    const fetcher = vi.fn(async (n: string) => `d-${n}`);
    const { result, rerender } = renderHook(
      ({ name }: { name: string | null }) => useRegionFetch(name, fetcher),
      { initialProps: { name: 'foo' as string | null } },
    );
    await waitFor(() => expect(result.current.data).toBe('d-foo'));
    rerender({ name: 'bar' });
    await waitFor(() => expect(result.current.data).toBe('d-bar'));
    expect(fetcher).toHaveBeenCalledTimes(2);
    expect(fetcher).toHaveBeenNthCalledWith(1, 'foo');
    expect(fetcher).toHaveBeenNthCalledWith(2, 'bar');
  });

  it('reload() refetches with the current name', async () => {
    let callCount = 0;
    const fetcher = vi.fn(async () => ++callCount);
    const { result } = renderHook(() => useRegionFetch('foo', fetcher));
    await waitFor(() => expect(result.current.data).toBe(1));
    act(() => result.current.reload());
    await waitFor(() => expect(result.current.data).toBe(2));
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it('does not setState after unmount', async () => {
    let resolveFetch: ((v: string) => void) | null = null;
    const fetcher = vi.fn(
      () =>
        new Promise<string>((resolve) => {
          resolveFetch = resolve;
        }),
    );
    const { unmount } = renderHook(() => useRegionFetch('foo', fetcher));
    // Unmount before the fetch resolves.
    unmount();
    // Resolving after unmount must not throw a React "setState on unmounted" warning.
    const errSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    resolveFetch!('late');
    await Promise.resolve();
    await Promise.resolve();
    expect(errSpy).not.toHaveBeenCalled();
    errSpy.mockRestore();
  });

  it('ignores stale fetch results when name changes mid-flight', async () => {
    // First call is slow; second is fast. Result should reflect the second call.
    const gates: Record<string, (v: string) => void> = {};
    const fetcher = vi.fn(
      (n: string) =>
        new Promise<string>((resolve) => {
          gates[n] = resolve;
        }),
    );
    const { result, rerender } = renderHook(
      ({ name }: { name: string | null }) => useRegionFetch(name, fetcher),
      { initialProps: { name: 'foo' as string | null } },
    );
    // Kick off a second fetch (for 'bar') before 'foo' resolves.
    rerender({ name: 'bar' });
    // Resolve 'foo' LATE — its result must be ignored.
    gates['foo']!('stale-foo');
    // Resolve 'bar' — this should win.
    gates['bar']!('fresh-bar');
    await waitFor(() => expect(result.current.data).toBe('fresh-bar'));
    // And it must stay 'fresh-bar' (stale 'foo' didn't sneak in).
    expect(result.current.data).toBe('fresh-bar');
  });
});
