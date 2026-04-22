import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, waitFor, cleanup } from '@testing-library/react';
import { useRegionAppendix } from './useRegionAppendix';
import * as rest from '../api/rest';

describe('useRegionAppendix', () => {
  beforeEach(() => { vi.restoreAllMocks(); });
  afterEach(() => { cleanup(); });

  it('loads data on mount', async () => {
    vi.spyOn(rest, 'fetchAppendix').mockResolvedValue('## 2026-04-22T10:00:00Z — sleep\n\nhi');
    const { result } = renderHook(() => useRegionAppendix('r'));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.data).toContain('## 2026-04-22');
    expect(result.current.error).toBeNull();
  });

  it('maps 404 to empty data (not error)', async () => {
    const err = new rest.RestError(404, 'not found');
    vi.spyOn(rest, 'fetchAppendix').mockRejectedValue(err);
    const { result } = renderHook(() => useRegionAppendix('r'));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.data).toBe('');
    expect(result.current.error).toBeNull();
  });

  it('surfaces non-404 errors', async () => {
    const err = new rest.RestError(403, 'sandbox');
    vi.spyOn(rest, 'fetchAppendix').mockRejectedValue(err);
    const { result } = renderHook(() => useRegionAppendix('r'));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.data).toBeNull();
    expect(result.current.error?.message).toBe('sandbox');
  });

  it('reload refetches', async () => {
    const spy = vi.spyOn(rest, 'fetchAppendix').mockResolvedValue('first');
    const { result } = renderHook(() => useRegionAppendix('r'));
    await waitFor(() => expect(result.current.data).toBe('first'));
    spy.mockResolvedValue('second');
    result.current.reload();
    await waitFor(() => expect(result.current.data).toBe('second'));
  });
});
