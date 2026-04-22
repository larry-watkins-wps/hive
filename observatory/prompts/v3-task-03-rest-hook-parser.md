# Observatory v3 — Task 3 implementer prompt

You are an implementer subagent. You own **exactly one task** end-to-end: implementation, tests, verification, commit. Report with status + SHA when done.

Use `superpowers:test-driven-development`.

**Working directory:** `C:\repos\hive`.
**Node:** `cd observatory/web-src && npx vitest run`. `npx tsc -b` for typecheck.

---

## Task

Add three independent frontend pieces that together power the inspector's Appendix section (Task 8):

1. **REST wrapper** `fetchAppendix(name)` — mirrors `fetchPrompt` using the existing `_get` helper.
2. **Parser** `parseAppendix(md) -> AppendixEntry[]` — pure markdown splitter on `^## <ts> [— <trigger>]` headings, tolerates malformed inputs.
3. **Hook** `useRegionAppendix(name)` — fetcher with `{loading, error, data, reload}` shape. Critical contract: `RestError(404)` maps to `data = ''` (not `error`), so fresh regions render an empty state instead of "Failed: 404".

### Authoritative references

- **Spec §9.3 Frontend wiring** (`observatory/docs/specs/2026-04-22-observatory-v3-design.md` lines 269–274).
- **Spec §9.4 Entry parsing (minimal)** (lines 276–292).
- **Plan Task 3** (`observatory/docs/plans/2026-04-22-observatory-v3-plan.md` lines 569–866).

---

## Plan Task 3 — verbatim steps

(Copy/paste from the plan; all 12 steps are reproduced below for self-containment.)

### Files
- Modify: `observatory/web-src/src/api/rest.ts`
- Modify: `observatory/web-src/src/api/rest.test.ts`
- Create: `observatory/web-src/src/inspector/sections/parseAppendix.ts`
- Create: `observatory/web-src/src/inspector/sections/parseAppendix.test.ts`
- Create: `observatory/web-src/src/inspector/useRegionAppendix.ts`
- Create: `observatory/web-src/src/inspector/useRegionAppendix.test.ts`

### Context for implementer

Three independent pieces that together power the Appendix section in Task 8. All can be developed and tested without the section component existing yet.

**REST wrapper** mirrors `fetchPrompt`. The existing `_get` helper already raises `RestError` on non-2xx.

**Parser** is pure. Input: the raw `rolling.md` contents. Output: list of `AppendixEntry`. Format (from `region_template/appendix.py`): entries framed with `## <ISO-timestamp> — <trigger>` H2 headings. Tolerate external hand-edits.

**Hook** follows the v2 `useRegionFetch` pattern. The key difference: map `RestError(404)` to `data === ''` (empty), so the section renders an empty state instead of `Failed: 404`.

### Step 1 — Write failing parser tests

Create `observatory/web-src/src/inspector/sections/parseAppendix.test.ts`:

```typescript
import { describe, it, expect } from 'vitest';
import { parseAppendix } from './parseAppendix';

describe('parseAppendix', () => {
  it('returns [] for empty input', () => {
    expect(parseAppendix('')).toEqual([]);
  });

  it('parses a single entry', () => {
    const md = '## 2026-04-22T10:00:00Z — sleep\n\nbody line one\nbody line two\n';
    expect(parseAppendix(md)).toEqual([
      { ts: '2026-04-22T10:00:00Z', trigger: 'sleep', body: 'body line one\nbody line two' },
    ]);
  });

  it('parses multiple entries in file order', () => {
    const md = [
      '## 2026-04-22T10:00:00Z — sleep', '',
      'entry one', '',
      '## 2026-04-22T12:00:00Z — sleep', '',
      'entry two',
    ].join('\n');
    const entries = parseAppendix(md);
    expect(entries).toHaveLength(2);
    expect(entries[0].ts).toBe('2026-04-22T10:00:00Z');
    expect(entries[0].body).toBe('entry one');
    expect(entries[1].ts).toBe('2026-04-22T12:00:00Z');
    expect(entries[1].body).toBe('entry two');
  });

  it('tolerates missing trigger (no em-dash)', () => {
    const md = '## 2026-04-22T10:00:00Z\n\nbody';
    expect(parseAppendix(md)).toEqual([
      { ts: '2026-04-22T10:00:00Z', trigger: '', body: 'body' },
    ]);
  });

  it('tolerates trailing whitespace', () => {
    const md = '## 2026-04-22T10:00:00Z — sleep   \n\nbody\n\n';
    const [entry] = parseAppendix(md);
    expect(entry.ts).toBe('2026-04-22T10:00:00Z');
    expect(entry.trigger).toBe('sleep');
    expect(entry.body).toBe('body');
  });

  it('returns single implicit entry when file has no ## headings', () => {
    const md = 'hand-written preamble with no ## sections\nline two';
    expect(parseAppendix(md)).toEqual([
      { ts: '', trigger: '', body: 'hand-written preamble with no ## sections\nline two' },
    ]);
  });
});
```

### Step 2 — Run parser tests. Expect: module-missing failure.

### Step 3 — Implement parser

Create `observatory/web-src/src/inspector/sections/parseAppendix.ts`:

```typescript
export type AppendixEntry = {
  ts: string;       // ISO timestamp from the "## <ts> — <trigger>" line (may be empty)
  trigger: string;  // word after "— " (may be empty)
  body: string;     // everything between this heading and the next (trimmed)
};

export function parseAppendix(md: string): AppendixEntry[] {
  if (md.trim() === '') return [];

  const lines = md.split('\n');
  const headings: Array<{ lineIdx: number; ts: string; trigger: string }> = [];
  for (let i = 0; i < lines.length; i++) {
    const m = lines[i].match(/^## (.+)$/);
    if (m) {
      const inner = m[1].trim();
      const split = inner.match(/^([^—]+?)\s*(?:—\s*(.*))?$/);
      const ts = (split?.[1] ?? inner).trim();
      const trigger = (split?.[2] ?? '').trim();
      headings.push({ lineIdx: i, ts, trigger });
    }
  }

  if (headings.length === 0) {
    return [{ ts: '', trigger: '', body: md.trim() }];
  }

  const entries: AppendixEntry[] = [];
  for (let i = 0; i < headings.length; i++) {
    const start = headings[i].lineIdx + 1;
    const end = i + 1 < headings.length ? headings[i + 1].lineIdx : lines.length;
    const body = lines.slice(start, end).join('\n').trim();
    entries.push({ ts: headings[i].ts, trigger: headings[i].trigger, body });
  }
  return entries;
}
```

### Step 4 — Run parser tests. Expected: 6 PASS.

### Step 5 — Write failing REST fetcher test

Open `observatory/web-src/src/api/rest.test.ts`. Append **using the existing `mockFetchOnce` helper** (see fidelity note below) — do NOT introduce `globalThis.fetch = vi.fn().mockResolvedValue(...)` as the plan's sample shows, because the existing test file has its own `mockFetchOnce(status, body, contentType?)` helper + `afterEach(() => vi.unstubAllGlobals())` setup. Write:

```typescript
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
```

Add `fetchAppendix` to the imports at the top of the file.

### Step 6 — Implement `fetchAppendix`

Open `observatory/web-src/src/api/rest.ts`. Append:

```typescript
export async function fetchAppendix(name: string): Promise<string> {
  const r = await _get(`/api/regions/${encodeURIComponent(name)}/appendix`);
  return r.text();
}
```

### Step 7 — Run REST tests. Expected: pass.

### Step 8 — Write failing hook tests

Create `observatory/web-src/src/inspector/useRegionAppendix.test.ts`:

```typescript
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
```

### Step 9 — Implement hook

Create `observatory/web-src/src/inspector/useRegionAppendix.ts`:

```typescript
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
```

### Step 10 — Run hook tests. Expected: 4 PASS.

### Step 11 — Full frontend suite + typecheck

```
cd observatory/web-src && npx vitest run && npx tsc -b
```

### Step 12 — Commit

```bash
git add observatory/web-src/src/api/ observatory/web-src/src/inspector/
git commit -m "$(cat <<'EOF'
observatory: rest+hook+parser for rolling appendix (v3 task 3)

fetchAppendix wraps GET /api/regions/{name}/appendix. useRegionAppendix
maps RestError(404) to data:'' so fresh regions that have never slept
render an empty state instead of a red 'Failed: 404'. parseAppendix is
a pure markdown parser using String.prototype.match: splits on
^## <ts> [— <trigger>] headings, tolerates missing trigger, trailing
whitespace, and files without any headings (collapse to a single
implicit entry).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Drifts you MUST correct (verified against current files)

### Drift A — 404 body shape (post-Task-1-review-fix)

The plan's Step 5 test mocks `{ error: 'not_found', message: 'no appendix' }` for the 404 case. **Task 1's review-fix (commit `ac3f76a`) changed the backend 404-missing body to `{"error":"appendix_missing","message":"No appendix file for region"}`** (per spec §9.2). Update the 404 test mock to use the post-review-fix shape so the test reflects real backend behavior:

```typescript
it('throws RestError with status 404 on missing appendix', async () => {
  mockFetchOnce(404, { error: 'appendix_missing', message: 'No appendix file for region' });
  await expect(fetchAppendix('good_region')).rejects.toMatchObject({
    name: 'RestError',
    status: 404,
    message: 'No appendix file for region',
  });
});
```

The hook tests (Step 8) don't need changing — they only branch on `e.status === 404`, not on `e.message` or `e.body.error`, so the hook's 404-handling is independent of the body shape.

### Drift B — `rest.test.ts` uses `mockFetchOnce` helper, not inline `vi.fn()`

The plan's Step 5 code uses `globalThis.fetch = vi.fn().mockResolvedValue(...)`. The **existing** `observatory/web-src/src/api/rest.test.ts` defines helpers `mockFetchOnce(status, body, contentType?)` and `mockFetchNonJsonError(status, text)`, plus an `afterEach(() => vi.unstubAllGlobals())`. Use those helpers for consistency.

See the Step 5 rewritten block above for the correct form.

---

## Existing-contract surface (read these before writing)

**`observatory/web-src/src/api/rest.ts`**:
- `RestError` class: `constructor(public status: number, message: string, public body?: unknown)`. Sets `this.name = 'RestError'`.
- `_get(path, init?)` internal helper: throws `RestError` on non-2xx with the flat `{error, message}` body extracted.
- Existing fetchers: `fetchPrompt`, `fetchStm`, `fetchSubscriptions`, `fetchConfig`, `fetchHandlers`. Your `fetchAppendix` mirrors `fetchPrompt` (text response).
- `getHealth` + `getRegions` bypass `_get` — they use naked `fetch`; that's a v1 quirk, leave alone.

**`observatory/web-src/src/api/rest.test.ts`**:
- Imports at top; add `fetchAppendix` to the list.
- `mockFetchOnce(status, body, contentType = 'application/json')` helper — builds a proper `Response` with `statusText` derived from the status code.
- `afterEach(() => vi.unstubAllGlobals())` — already set; don't duplicate.
- Existing tests organized by `describe('fetchX', ...)` blocks.

**`observatory/web-src/src/inspector/useRegionFetch.ts`** (reference only — **do not modify**):
- Existing v2 hook pattern using `useCallback` + `useEffect` + `cancelled` flag + `mountedRef` + `reloadTick`.
- `useRegionAppendix` diverges: uses `reqId: useRef<number>` for race-cancellation (functionally equivalent) and carries `error: Error | null` (not `string | null`) so consumers can introspect the error type. Follow the plan's Step 9 code verbatim.

**`observatory/web-src/src/inspector/useRegionFetch.test.ts`** (reference only):
- Uses `renderHook`/`waitFor`/`cleanup` from `@testing-library/react@16.3.2`. Your hook tests follow the same idiom.

## Gotchas

- **Vitest `globals: false`** — import `describe, it, expect, vi, beforeEach, afterEach` from `'vitest'` explicitly.
- **`renderHook` unmount cleanup** — use `cleanup()` in `afterEach` to avoid test-to-test state leak (`renderHook` mounts into `document.body` by default).
- **`vi.spyOn(rest, 'fetchAppendix')`** — this requires `fetchAppendix` to be a named export, not a default export. Plan's Step 6 exports it correctly.
- **Plan's `error?.message`** on the `surfaces non-404 errors` test — `Error | null` chain-op is safe because the test's preceding `waitFor` ensures state transitioned. Don't tighten to `error!.message` (non-null assertion) — the chain-op is clearer.
- **Em-dash vs hyphen:** the parser splits on `—` (Unicode EM DASH, U+2014), NOT on `-` (hyphen-minus). The region runtime writes em-dash per `region_template/appendix.py`. The plan's regex `[^—]+?` uses em-dash literally — preserve it.
- **`md.trim() === ''` early-return:** plan's Step 3 guards the empty-string case. Keep it — otherwise the trailing `[{ ts: '', trigger: '', body: '' }]` branch would fire with body trimmed to `''`, which is semantically wrong (we want `[]` not `[{ ts:'',trigger:'',body:'' }]`).

## Verification gates (must all pass before commit)

```
cd observatory/web-src && npx vitest run && npx tsc -b
cd ../.. && .venv/Scripts/python.exe -m ruff check observatory/
```

Expected: **~103 frontend tests passing** (was 91 after Task 2 — add 6 parser + 2 REST + 4 hook = +12 = 103). Ruff clean. Typecheck clean.

## Hard rules

- Do NOT touch `region_template/`, `glia/`, `regions/`, `bus/`, `shared/`.
- Do NOT modify `useRegionFetch.ts` — it's v2's; Task 3's hook is a sibling, not a refactor.
- Do NOT push.
- TDD: tests FIRST, observe red, THEN implement.
- If a spec-vs-plan conflict surfaces that the prompt doesn't cover, stop with `NEEDS_CONTEXT`.

## Report format

1. Status / SHA / files touched
2. Test delta (before/after)
3. Any drift from this brief
4. Concerns
