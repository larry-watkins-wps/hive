import { describe, it, expect, vi, afterEach } from 'vitest';
import {
  fetchPrompt,
  fetchStm,
  fetchSubscriptions,
  fetchConfig,
  fetchHandlers,
  fetchAppendix,
  RestError,
} from './rest';

// Backend emits the FLAT error body shape (Task 4 review-fix):
//   {"error": "sandbox|parse|not_found|oversize", "message": "..."}
// NOT nested under `detail`. Mock responses here match that shape.
function mockFetchOnce(
  status: number,
  body: unknown,
  contentType = 'application/json',
) {
  const headers = new Headers({ 'content-type': contentType });
  const statusText =
    status === 200
      ? 'OK'
      : status === 404
        ? 'Not Found'
        : status === 403
          ? 'Forbidden'
          : status === 413
            ? 'Payload Too Large'
            : status === 502
              ? 'Bad Gateway'
              : 'Error';
  const init = { status, statusText, headers };
  const blob = contentType.startsWith('application/json')
    ? JSON.stringify(body)
    : String(body);
  vi.stubGlobal('fetch', vi.fn(async () => new Response(blob, init)));
}

function mockFetchNonJsonError(status: number, text: string) {
  const headers = new Headers({ 'content-type': 'text/plain; charset=utf-8' });
  const init = { status, statusText: 'Server Error', headers };
  vi.stubGlobal('fetch', vi.fn(async () => new Response(text, init)));
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('fetchPrompt', () => {
  it('returns text on 200', async () => {
    mockFetchOnce(200, 'hello', 'text/plain; charset=utf-8');
    expect(await fetchPrompt('foo')).toBe('hello');
  });

  it('url-encodes the region name', async () => {
    const fetchSpy = vi.fn(
      async () =>
        new Response('ok', {
          status: 200,
          statusText: 'OK',
          headers: new Headers({ 'content-type': 'text/plain' }),
        }),
    );
    vi.stubGlobal('fetch', fetchSpy);
    await fetchPrompt('has space/%plus');
    expect(fetchSpy).toHaveBeenCalledWith(
      '/api/regions/has%20space%2F%25plus/prompt',
      undefined,
    );
  });

  it('throws RestError with server message on 404', async () => {
    mockFetchOnce(404, { error: 'not_found', message: 'region not registered' });
    await expect(fetchPrompt('nosuch')).rejects.toMatchObject({
      status: 404,
      message: 'region not registered',
    });
    await expect(fetchPrompt('nosuch')).rejects.toBeInstanceOf(RestError);
  });

  it('throws RestError on 403 sandbox with message', async () => {
    mockFetchOnce(403, { error: 'sandbox', message: 'symlink rejected' });
    await expect(fetchPrompt('foo')).rejects.toMatchObject({
      status: 403,
      message: 'symlink rejected',
    });
  });

  it('falls back to status+statusText when body is not JSON', async () => {
    mockFetchNonJsonError(500, '<html>internal</html>');
    await expect(fetchPrompt('foo')).rejects.toMatchObject({
      status: 500,
      message: '500 Server Error',
    });
  });

  it('falls back to status+statusText when JSON lacks message', async () => {
    mockFetchOnce(404, { error: 'not_found' });
    await expect(fetchPrompt('foo')).rejects.toMatchObject({
      status: 404,
      message: '404 Not Found',
    });
  });
});

describe('fetchStm', () => {
  it('returns parsed JSON', async () => {
    mockFetchOnce(200, { note: 'ok', n: 3 });
    expect(await fetchStm('foo')).toEqual({ note: 'ok', n: 3 });
  });

  it('throws on 502 parse error (flat body)', async () => {
    mockFetchOnce(502, { error: 'parse', message: 'bad json' });
    await expect(fetchStm('foo')).rejects.toMatchObject({
      status: 502,
      message: 'bad json',
    });
  });

  it('throws on 413 oversize (flat body)', async () => {
    mockFetchOnce(413, { error: 'oversize', message: 'file too large' });
    await expect(fetchStm('foo')).rejects.toMatchObject({
      status: 413,
      message: 'file too large',
    });
  });
});

describe('fetchSubscriptions', () => {
  it('returns parsed JSON', async () => {
    mockFetchOnce(200, { subs: ['topic/a', 'topic/b'] });
    expect(await fetchSubscriptions('foo')).toEqual({ subs: ['topic/a', 'topic/b'] });
  });
});

describe('fetchConfig', () => {
  it('returns parsed JSON (redacted by server)', async () => {
    mockFetchOnce(200, { api_key: '***', model: 'claude' });
    expect(await fetchConfig('foo')).toEqual({ api_key: '***', model: 'claude' });
  });
});

describe('fetchHandlers', () => {
  it('returns array of entries', async () => {
    mockFetchOnce(200, [{ path: 'handlers/a.py', size: 123 }]);
    expect(await fetchHandlers('foo')).toEqual([
      { path: 'handlers/a.py', size: 123 },
    ]);
  });

  it('throws RestError with flat-body message on 404', async () => {
    mockFetchOnce(404, { error: 'not_found', message: 'no handlers dir' });
    await expect(fetchHandlers('foo')).rejects.toMatchObject({
      status: 404,
      message: 'no handlers dir',
    });
  });
});

describe('fetchAppendix', () => {
  it('returns text on 200', async () => {
    mockFetchOnce(200, '## 2026-04-22T10:00:00Z — sleep\n\nbody', 'text/plain; charset=utf-8');
    expect(await fetchAppendix('good_region')).toBe('## 2026-04-22T10:00:00Z — sleep\n\nbody');
  });

  it('throws RestError with status 404 on missing appendix', async () => {
    mockFetchOnce(404, { error: 'appendix_missing', message: 'No appendix file for region' });
    await expect(fetchAppendix('good_region')).rejects.toMatchObject({
      name: 'RestError',
      status: 404,
      message: 'No appendix file for region',
    });
  });
});

describe('RestError', () => {
  it('carries status, message, and body', async () => {
    mockFetchOnce(403, { error: 'sandbox', message: 'escape' });
    try {
      await fetchPrompt('foo');
      expect.unreachable('should have thrown');
    } catch (e) {
      expect(e).toBeInstanceOf(RestError);
      expect((e as RestError).status).toBe(403);
      expect((e as RestError).message).toBe('escape');
      expect((e as RestError).body).toEqual({ error: 'sandbox', message: 'escape' });
      expect((e as RestError).name).toBe('RestError');
    }
  });
});
