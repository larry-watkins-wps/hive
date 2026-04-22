# v2 Task 13 — Inspector Prompt + STM + JsonTree sections

You are the **implementer subagent** for v2 Task 13 of the Hive observatory
sub-project. Fresh context — you have not worked on this repo in this
conversation. Everything you need is in this prompt. Do **not** attempt to
read the plan or HANDOFF yourself; the controller has already extracted
the relevant text.

## Where this task fits

Observatory v2 adds a right slide-over inspector panel (420 px) that opens
when a region mesh is clicked in the 3D scene. Tasks 6–12 landed the
shell (store wiring, REST wrappers, CameraControls, fuzzy orbs, labels,
edges, Inspector chrome + 5 of 8 sections + keyboard cycling). Three
section stubs remain. Your job: fill in **Prompt** + **STM**, and create
the **JsonTree** recursive JSON renderer the STM section uses. You are
NOT implementing Messages (that is Task 14) or touching Inspector.tsx
(already wired).

## Authority ordering

1. **Spec wins over plan prose.** If plan code and spec text disagree,
   follow the spec and flag the discrepancy in your status report.
2. **User (Larry) instructions always override.**

## Files

Create or modify exactly these four files. Nothing else:

- CREATE: `observatory/web-src/src/inspector/sections/JsonTree.tsx`
- REPLACE stub: `observatory/web-src/src/inspector/sections/Prompt.tsx`
- REPLACE stub: `observatory/web-src/src/inspector/sections/Stm.tsx`
- CREATE: `observatory/web-src/src/inspector/Stm.test.tsx`

**Do NOT modify** any of these:
- `observatory/web-src/src/inspector/Inspector.tsx` (already imports
  `Prompt` and `Stm` and wires them with `name={displayName}` — once your
  stubs become real, they render).
- `observatory/web-src/src/inspector/useRegionFetch.ts` (already returns
  `{ loading, error, data, reload }` in the shape you need).
- `observatory/web-src/src/api/rest.ts` (already exports `fetchPrompt`
  and `fetchStm`).
- `observatory/web-src/src/inspector/format.ts` (already exports
  `fmtBytes` — you may import from here if helpful).

## Current state of the two stubs (you will replace these)

`observatory/web-src/src/inspector/sections/Prompt.tsx`:
```tsx
// TODO(Task 13): Implement Prompt section — collapsed <details> with fetched
// prompt.md text, size label, reload button, and auto-refetch on phase /
// last_error_ts change. Spec §3.2 item 4 and §3.3.
// eslint-disable-next-line @typescript-eslint/no-unused-vars
export function Prompt(_props: { name: string }) {
  return null;
}
```

`observatory/web-src/src/inspector/sections/Stm.tsx`:
```tsx
// TODO(Task 13): Implement STM section — collapsed <details> rendering
// fetched STM as a recursive JSON tree (JsonTree.tsx in Task 13), with
// empty-state "STM is empty." and auto-refetch on phase / last_error_ts.
// eslint-disable-next-line @typescript-eslint/no-unused-vars
export function Stm(_props: { name: string }) {
  return null;
}
```

## Spec excerpt — §3.2 items 4 & 6, §3.3, §3.4

**§3.2 item 4 — Prompt:** collapsed by default. `<details>` summary shows
size in kB. Expanded: scrollable monospaced `<pre>` of fetched text, with
a "reload" button in the summary. Auto-refetch when the region's
`last_error_ts` or `phase` changes.

**§3.2 item 6 — STM:** collapsed by default. JSON tree view via a tiny
in-repo recursive component (no new dependency). Same refetch rules as
Prompt.

**§3.2 final para:** sections 4–8 render a chevron (▸ / ▾) for
collapsed/expanded. Default collapsed for Prompt + STM.

**§3.3 refetch matrix:**
| Section | Fetch trigger | Auto-refetch triggers |
|---|---|---|
| Prompt | on open + region change | `last_error_ts` change · `phase` change · reload button |
| STM | on open + region change | `last_error_ts` change · `phase` change · reload button |

**§3.4 loading / error / empty states:**
- loading: 24-px grey skeleton bar (in practice, inline "loading…" text
  matching the existing sections is acceptable — see Handlers.tsx below
  for the project pattern).
- error: inline red text `Failed: <message>` + retry button. (The
  existing pattern re-uses the summary's reload button for retry, which
  satisfies "retry".)
- Empty STM (`{}`) → "STM is empty."
- Prompt missing → "No `prompt.md` in this region."

## Existing contracts you will consume

`observatory/web-src/src/inspector/useRegionFetch.ts`:
```tsx
export function useRegionFetch<T>(
  name: string | null,
  fetcher: (name: string) => Promise<T>,
): { loading: boolean; error: string | null; data: T | null; reload: () => void };
```
- Re-fetches whenever `name` changes; `reload()` forces a re-run with
  the current name.
- `name === null` → idle (no fetch, state cleared). You will always
  receive a non-null `name` (Inspector only mounts section children
  under `{displayName && (...)}`), so you can treat the string as
  non-null inside your components.

`observatory/web-src/src/api/rest.ts`:
```tsx
export async function fetchPrompt(name: string): Promise<string>;
export async function fetchStm(name: string): Promise<Record<string, unknown>>;
```
On 404 the helper raises `RestError` (status 404) — your `error` slot
will contain the backend's message. The spec's "No `prompt.md` in this
region" copy should render when `data === null || data === ''`.

Hmm: the 404-on-missing-prompt case currently surfaces through `error`,
not `data === null`. Render "No `prompt.md` in this region." when
either `!loading && data === '' && !error` OR `!loading && error` *and*
the error message contains "not_found" / matches the backend's 404 body.
**Recommended simpler rule:** show the copy when
`!loading && !error && (data === null || data === '')`; keep the normal
red-error branch for genuine failures. Document your choice in a one-line
comment and note it in your status report.

`observatory/web-src/src/store.ts` (relevant slice):
```tsx
// regions is Record<string, RegionMeta>; stats is RegionMeta.stats
type RegionStats = {
  phase: 'bootstrap'|'wake'|'processing'|'sleep'|'shutdown'|'unknown';
  queue_depth: number; stm_bytes: number; tokens_lifetime: number;
  handler_count: number; last_error_ts: number | null;
  msg_rate_in: number; msg_rate_out: number; llm_in_flight: boolean;
};
export const useStore = create<...>(...);
```
Read stats with `useStore((s) => s.regions[name]?.stats)`.

`observatory/web-src/src/inspector/format.ts`:
```tsx
export function fmtBytes(n: number): string;  // "523 B" / "12 kB" / "1.2 MB"
```
Uses bytes. For Prompt's summary, the plan hard-codes
`(data.length / 1024).toFixed(1) + ' kB'`, but `data.length` is UTF-16
code-unit count, not byte count. Prompt files are ASCII in practice, so
either approach is fine. **Prefer `fmtBytes(data.length)` for consistency
with Handlers + Stats** unless it surfaces an issue — flag any deviation.

## Reference pattern — Handlers.tsx (style to match)

```tsx
import { fetchHandlers, type HandlerEntry } from '../../api/rest';
import { useRegionFetch } from '../useRegionFetch';
import { fmtBytes } from '../format';

export function Handlers({ name }: { name: string }) {
  const { loading, error, data, reload } = useRegionFetch(name, fetchHandlers);
  const entries: HandlerEntry[] = data ?? [];
  return (
    <details className="px-4 py-2 border-b border-[#1f1f27]">
      <summary className="cursor-pointer flex justify-between items-center">
        <span className="font-semibold">
          Handlers{' '}
          <span className="text-[#8a8e99] text-[10px]">· {entries.length} files</span>
        </span>
        <button
          type="button"
          onClick={(e) => { e.preventDefault(); e.stopPropagation(); reload(); }}
          className="text-[10px] text-[#8a8e99] border border-[#2a2a33] px-2 rounded"
        >
          reload
        </button>
      </summary>
      <div className="pt-2 text-[11px]">
        {loading && <div className="text-[#8a8e99]">loading…</div>}
        {error && <div className="text-[#ff6a6a]">Failed: {error}</div>}
        {/* ...entries rendering... */}
      </div>
    </details>
  );
}
```

**Critical detail:** the reload button uses `e.preventDefault();
e.stopPropagation();` so clicking it does NOT toggle the enclosing
`<details>` open/closed. The plan's snippet for Prompt/Stm omits
`stopPropagation` — **include it** for consistency and to avoid the
"one click reloads, then immediately collapses the section" UX bug.

## Plan step-by-step (verbatim from plan, lines 2679–2883)

### Step 1 — Create `JsonTree.tsx`

```tsx
import { useState } from 'react';

type JsonValue = string | number | boolean | null | JsonArray | JsonObject;
type JsonArray = JsonValue[];
type JsonObject = { [k: string]: JsonValue };

export function JsonTree({ value, depth = 0 }: { value: JsonValue; depth?: number }) {
  if (value === null) return <span className="text-[#8a8e99]">null</span>;
  if (typeof value === 'string') return <span className="text-[#8fd6a0]">"{value}"</span>;
  if (typeof value === 'number') return <span className="text-[#ffb36a]">{value}</span>;
  if (typeof value === 'boolean') return <span className="text-[#d6a0e0]">{String(value)}</span>;
  if (Array.isArray(value)) return <JsonArrayView arr={value} depth={depth} />;
  return <JsonObjectView obj={value} depth={depth} />;
}

function JsonObjectView({ obj, depth }: { obj: JsonObject; depth: number }) {
  const [open, setOpen] = useState(depth < 1);
  const keys = Object.keys(obj);
  if (keys.length === 0) return <span className="text-[#8a8e99]">{'{}'}</span>;
  return (
    <span>
      <button className="text-[#8a8e99] font-mono" onClick={() => setOpen(!open)}>{open ? '▾' : '▸'}</button>
      <span className="text-[#8a8e99]"> {'{'} </span>
      {open && (
        <div className="pl-3">
          {keys.map((k) => (
            <div key={k} className="font-mono text-[11px]">
              <span className="text-[#8ec5ff]">{k}</span>
              <span className="text-[#8a8e99]">: </span>
              <JsonTree value={obj[k]} depth={depth + 1} />
            </div>
          ))}
        </div>
      )}
      <span className="text-[#8a8e99]">{'}'}</span>
    </span>
  );
}

function JsonArrayView({ arr, depth }: { arr: JsonArray; depth: number }) {
  const [open, setOpen] = useState(depth < 1);
  if (arr.length === 0) return <span className="text-[#8a8e99]">[]</span>;
  return (
    <span>
      <button className="text-[#8a8e99] font-mono" onClick={() => setOpen(!open)}>{open ? '▾' : '▸'}</button>
      <span className="text-[#8a8e99]"> [</span>
      {open && (
        <div className="pl-3">
          {arr.map((item, i) => (
            <div key={i} className="font-mono text-[11px]">
              <span className="text-[#8a8e99]">{i}: </span>
              <JsonTree value={item} depth={depth + 1} />
            </div>
          ))}
        </div>
      )}
      <span className="text-[#8a8e99]">]</span>
    </span>
  );
}
```

### Step 2 — Replace `Prompt.tsx`

```tsx
import { useEffect } from 'react';
import { useStore } from '../../store';
import { useRegionFetch } from '../useRegionFetch';
import { fetchPrompt } from '../../api/rest';

export function Prompt({ name }: { name: string }) {
  const { loading, error, data, reload } = useRegionFetch(name, fetchPrompt);
  const stats = useStore((s) => s.regions[name]?.stats);

  // Auto-refetch on phase change or last_error_ts change (spec §3.3).
  useEffect(() => {
    if (stats) reload();
  }, [stats?.phase, stats?.last_error_ts]);  // deliberately excludes `reload` (stable)

  const sizeKb = data ? (data.length / 1024).toFixed(1) : '—';

  return (
    <details className="border-b border-[#1f1f27]">
      <summary className="px-4 py-2 cursor-pointer flex items-center justify-between">
        <span className="font-semibold">Prompt <span className="text-[#8a8e99] text-[10px]">· {sizeKb} kB</span></span>
        <button onClick={(e) => { e.preventDefault(); reload(); }} className="text-[10px] text-[#8a8e99] border border-[#2a2a33] px-2 rounded">reload</button>
      </summary>
      <div className="px-4 pb-3 text-[11px]">
        {loading && <div className="text-[#8a8e99]">loading…</div>}
        {error && <div className="text-[#ff6a6a]">Failed: {error}</div>}
        {!loading && !error && !data && <div className="text-[#8a8e99]">No <code>prompt.md</code> in this region.</div>}
        {data && <pre className="whitespace-pre-wrap break-words text-[#cfd2da] bg-[#0e0e14] p-2 rounded max-h-[360px] overflow-y-auto">{data}</pre>}
      </div>
    </details>
  );
}
```

### Step 3 — Replace `Stm.tsx`

```tsx
import { useEffect } from 'react';
import { useStore } from '../../store';
import { useRegionFetch } from '../useRegionFetch';
import { fetchStm } from '../../api/rest';
import { JsonTree } from './JsonTree';

export function Stm({ name }: { name: string }) {
  const { loading, error, data, reload } = useRegionFetch(name, fetchStm);
  const stats = useStore((s) => s.regions[name]?.stats);

  useEffect(() => {
    if (stats) reload();
  }, [stats?.phase, stats?.last_error_ts]);

  const keyCount = data ? Object.keys(data).length : 0;

  return (
    <details className="border-b border-[#1f1f27]">
      <summary className="px-4 py-2 cursor-pointer flex items-center justify-between">
        <span className="font-semibold">STM <span className="text-[#8a8e99] text-[10px]">· {keyCount} keys</span></span>
        <button onClick={(e) => { e.preventDefault(); reload(); }} className="text-[10px] text-[#8a8e99] border border-[#2a2a33] px-2 rounded">reload</button>
      </summary>
      <div className="px-4 pb-3 text-[11px]">
        {loading && <div className="text-[#8a8e99]">loading…</div>}
        {error && <div className="text-[#ff6a6a]">Failed: {error}</div>}
        {!loading && !error && data && Object.keys(data).length === 0 && <div className="text-[#8a8e99]">STM is empty.</div>}
        {data && Object.keys(data).length > 0 && <JsonTree value={data as any} />}
      </div>
    </details>
  );
}
```

### Step 4 — Write `Stm.test.tsx`

```tsx
import { describe, it, expect, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { Stm } from './sections/Stm';
import { useStore } from '../store';

describe('Stm', () => {
  beforeEach(() => {
    useStore.getState().applyRegionDelta({
      r: { role: 'x', llm_model: '', stats: {
        phase: 'wake', queue_depth: 0, stm_bytes: 0, tokens_lifetime: 0,
        handler_count: 0, last_error_ts: null, msg_rate_in: 0, msg_rate_out: 0,
        llm_in_flight: false,
      } },
    });
  });

  it('renders empty-state copy when STM is {}', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({}), { status: 200, headers: { 'content-type': 'application/json' } })));
    const { container } = render(<Stm name="r" />);
    // Expand the details.
    container.querySelector('details')!.open = true;
    await waitFor(() => expect(screen.getByText('STM is empty.')).toBeTruthy());
  });
});
```

## Known gotchas / drifts vs. plan (fix these in your implementation)

1. **`vitest.config.ts` has `globals: false`.** The plan's test file uses
   `beforeEach` without an import — that will fail. Add `beforeEach` to
   the `from 'vitest'` import. Same applies to any other non-imported
   globals you reach for.

2. **React hook deps lint.** `useEffect([stats?.phase, stats?.last_error_ts])`
   references `stats` and `reload` but excludes both. `stats?.x` is a
   primitive read so excluding `stats` is deliberate; `reload` is stable
   via `useCallback`. Add an `// eslint-disable-next-line react-hooks/exhaustive-deps`
   comment above the deps array OR use the existing project convention
   (check `Header.tsx` / `Stats.tsx` for precedent before choosing). Do
   **not** add `stats` to the deps array — it would loop on every store
   tick.

3. **Reload button event bubbling.** Plan's snippet only does
   `e.preventDefault()`. Follow `Handlers.tsx`: add `e.stopPropagation()`
   too, otherwise the click bubbles to `<summary>` and toggles the
   `<details>` closed. Explicitly verify with a manual thought-experiment
   while writing.

4. **Prompt size label.** Plan uses `(data.length / 1024).toFixed(1) + ' kB'`.
   Prefer `fmtBytes(data.length)` from `./format.ts` for consistency.
   Caveat: `string.length` is UTF-16 units, not bytes; for ASCII prompt
   files the difference is nil. If you deviate, note it in your status.

5. **`data as any` cast in `Stm.tsx`.** `fetchStm` returns
   `Record<string, unknown>` which is not assignable to `JsonValue`.
   Two clean options:
   - (a) Keep the cast but localize: `<JsonTree value={data as JsonValue} />`
     (import `JsonValue` as a type-only export from JsonTree if you
     choose this — requires an `export type JsonValue`).
   - (b) Widen `JsonTree` to accept `unknown` and internally narrow.
   Option (a) is simpler and keeps JsonTree strict. Your call; document
   in status.

6. **404 on missing prompt → surfaces as `error`.** The backend returns
   404 `{"error":"not_found","message":"..."}` when `prompt.md` is
   absent. The plan's "No `prompt.md` in this region." branch only
   triggers when `!error && !data`, which will NOT fire on a real 404.
   Acceptable options:
   - (a) Leave as-is: real 404s show red "Failed: ..." which is fine for
     v2 (spec §3.4 doesn't require semantic empty-state for 404).
   - (b) Detect the 404 `not_found` body by checking
     `error?.includes('not_found')` OR by instanceof-checking `RestError`
     + status 404 (would require passing the raw error from the hook).
   **Go with (a)** — simpler, matches what the plan expects, and
   genuinely unreachable in practice for wired-up regions. Document.

7. **TypeScript strict.** `noUnusedLocals` + `noUnusedParameters` will
   fail on unused imports or unused destructured bindings. In `Stm.tsx`
   you won't use `stats` directly except via its fields; the optional
   chaining keeps it valid. Don't import anything you don't consume.

8. **Don't add a new dependency.** Spec §3.2 item 6 says "tiny in-repo
   recursive component (no new dependency)". `npm install` anything →
   fail.

## Verification — MUST all pass cleanly

Run from repo root (the repo IS `C:\repos\hive`, git branch is `main`):

```bash
cd observatory/web-src
npx tsc -b                    # clean
npm run test -- --run         # all tests pass; you add 1+ new tests
npm run build                 # clean build
cd ../..
```

Do NOT run `python -m pytest` or `ruff` — this task is frontend-only.

**Baseline before your changes:**
- `npm run test -- --run` → 78 passed
- Test count after: 79+ (at least 1 new Stm test; more is welcome if
  they pin a real contract — do not pad).

## Commit — after tests pass

Stage exactly these files (no more, no less):

```bash
git add observatory/web-src/src/inspector/sections/Prompt.tsx \
        observatory/web-src/src/inspector/sections/Stm.tsx \
        observatory/web-src/src/inspector/sections/JsonTree.tsx \
        observatory/web-src/src/inspector/Stm.test.tsx
```

Pre-existing untracked paths — **leave alone**:
- `_test_review_tmp/`
- `docs/superpowers/plans/2026-04-21-append-only-prompt-evolution.md`
- `regions/prefrontal_cortex/.gitignore`
- `regions/prefrontal_cortex/handlers/notebook.py`

Commit on `main` with a HEREDOC message (exact format):

```
git commit -m "$(cat <<'EOF'
observatory: inspector Prompt + STM + JsonTree (v2 task 13)

Prompt: collapsed <details> with <pre> body + reload; auto-refetch on
phase or last_error_ts change. STM: same shape, rendered via JsonTree
(recursive, no dependencies, inline styling). Empty-state copy for both.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

One commit only. No review-fix commits — those come after the reviews,
driven by the controller.

## Status report — return ONE of these

- **DONE** — files created/replaced, tests added, verification passes,
  commit created. Report:
  1. The commit SHA.
  2. Any deviations from the plan's code blocks (gotchas #1–#6 above are
     expected; call out anything else).
  3. Final test count (`npm run test -- --run` output's pass number).
  4. Whether you used option (a) or (b) for gotcha #5 (JsonTree cast).

- **DONE_WITH_CONCERNS** — same as DONE but you noticed something the
  controller should know (spec gap, flaky test, unexpected TS error).

- **NEEDS_CONTEXT** — a fact in this prompt is wrong or insufficient.
  Specify exactly what.

- **BLOCKED** — something structurally prevents completion. Explain.

Do not ask for permission to proceed. You have full authorization for
the file edits, test runs, and commit described above.
