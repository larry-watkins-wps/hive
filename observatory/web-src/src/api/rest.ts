export async function getHealth(): Promise<{ status: string; version: string }> {
  const r = await fetch('/api/health');
  if (!r.ok) throw new Error(`GET /api/health ${r.status} ${r.statusText}`);
  return r.json();
}
export async function getRegions(): Promise<{ regions: Record<string, any> }> {
  const r = await fetch('/api/regions');
  if (!r.ok) throw new Error(`GET /api/regions ${r.status} ${r.statusText}`);
  return r.json();
}

/**
 * Error raised by the typed REST wrappers when the server returns non-2xx.
 * `body` is the parsed response body when available (the server's flat
 * {"error", "message"} shape, per §6.4 of the v2 spec).
 */
export class RestError extends Error {
  constructor(
    public status: number,
    message: string,
    public body?: unknown,
  ) {
    super(message);
    this.name = 'RestError';
  }
}

/**
 * Internal GET helper: throws a `RestError` on non-2xx.
 *
 * On error the observatory backend emits a flat body:
 *   {"error": "sandbox|parse|not_found|oversize", "message": "..."}
 * (Task 4's review-fix changed this from the pre-fix nested `{detail: {...}}`
 * shape; callers can rely on the flat shape now.)
 */
async function _get(path: string, init?: RequestInit): Promise<Response> {
  const r = await fetch(path, init);
  if (!r.ok) {
    let body: unknown;
    let msg: string;
    try {
      body = await r.json();
      const errBody = body as { error?: string; message?: string };
      msg = errBody?.message ?? `${r.status} ${r.statusText}`;
    } catch {
      msg = `${r.status} ${r.statusText}`;
    }
    throw new RestError(r.status, msg, body);
  }
  return r;
}

export async function fetchPrompt(name: string): Promise<string> {
  const r = await _get(`/api/regions/${encodeURIComponent(name)}/prompt`);
  return r.text();
}

export async function fetchStm(name: string): Promise<Record<string, unknown>> {
  const r = await _get(`/api/regions/${encodeURIComponent(name)}/stm`);
  return r.json();
}

export async function fetchSubscriptions(
  name: string,
): Promise<Record<string, unknown>> {
  const r = await _get(`/api/regions/${encodeURIComponent(name)}/subscriptions`);
  return r.json();
}

export async function fetchConfig(
  name: string,
): Promise<Record<string, unknown>> {
  const r = await _get(`/api/regions/${encodeURIComponent(name)}/config`);
  return r.json();
}

export type HandlerEntry = { path: string; size: number };

export async function fetchHandlers(name: string): Promise<HandlerEntry[]> {
  const r = await _get(`/api/regions/${encodeURIComponent(name)}/handlers`);
  return r.json();
}
