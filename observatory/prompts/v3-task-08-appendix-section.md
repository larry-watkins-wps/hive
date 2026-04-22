# Observatory v3 — Task 8 implementer prompt

One task, end-to-end. `superpowers:test-driven-development`. Report status + SHA when done.

**Working directory:** `C:\repos\hive`. **Node:** `cd observatory/web-src && npx vitest run && npx tsc -b`.

---

## Task

Build the inspector **Appendix section** and **relabel Prompt**. Adds live appendix rendering below the existing Prompt in the slide-over panel.

### Authoritative references

- **Spec §9** (lines 241–292): Appendix subsection layout, parsing, empty state.
- **Spec §11** (lines 334–341): Messages section upgrade (Task 10's concern; not this task).
- **Plan Task 8:** `observatory/docs/plans/2026-04-22-observatory-v3-plan.md` lines 2232–2404.

---

## Plan verbatim (with drifts below)

### Files
- Create: `observatory/web-src/src/inspector/sections/Appendix.tsx`
- Create: `observatory/web-src/src/inspector/sections/Appendix.test.tsx`
- Modify: `observatory/web-src/src/inspector/sections/Prompt.tsx` — relabel header to "Prompt (DNA)".
- Modify: `observatory/web-src/src/inspector/Inspector.tsx` — mount Appendix directly below Prompt.

### Contract (spec §9)

- **Expanded by default** (`<details open>`).
- 404 → empty state `"No appendix yet — region hasn't slept."`.
- Non-404 error → `Failed: <message>`.
- Auto-refetch on `phase` or `last_error_ts` change (skip first render — v2 Task 13 pattern).
- Parser preserves file order (chronological); reverse in the component so newest shows first.
- Each entry: timestamp + trigger tag + `<pre>` body.
- Max height 360 px; scrollable.

### Tests (plan Step 1 — 4 tests; see plan for full code)

- Renders entries newest-first
- Shows empty state on 404 (`RestError(404)`)
- Surfaces non-404 errors inline
- Reload triggers refetch

### Implementation (plan Step 3 — see plan)

The plan's Step 3 implementation is mostly correct; only the prop shape needs adjustment (Drift A).

---

## Drifts you MUST correct

### Drift A — Prop shape: match Prompt.tsx's internal-state-lookup pattern

Plan's Step 3 declares:
```tsx
export function Appendix({ name, phase, lastErrorTs }: {
  name: string;
  phase: string;
  lastErrorTs: string | null;
}) { ... }
```

But Plan's Step 5 tries to pass `<Appendix name={name} phase={stats.phase} lastErrorTs={stats.last_error_ts} />` from Inspector.tsx, which **does not have `stats` in scope**. The real `Inspector.tsx` mounts `<Prompt name={displayName} />` — a `{name}`-only signature. `Prompt.tsx` internally reads stats via `useStore((s) => s.regions[name]?.stats)`.

**Fix:** change `Appendix`'s signature to `{ name: string }` and read stats internally, matching `Prompt.tsx:23-24`:

```tsx
export function Appendix({ name }: { name: string }) {
  const { loading, error, data, reload } = useRegionAppendix(name);
  const stats = useStore((s) => s.regions[name]?.stats);
  // ...
  const firstRef = useRef(true);
  useEffect(() => {
    if (firstRef.current) { firstRef.current = false; return; }
    if (stats) reload();
  }, [stats?.phase, stats?.last_error_ts]);
  // ...
}
```

Import `useStore` from `'../../store'`.

Update the tests to set up region stats via `useStore.setState(...)` before rendering, instead of passing props:

```tsx
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, cleanup, fireEvent } from '@testing-library/react';
import * as rest from '../../api/rest';
import { Appendix } from './Appendix';
import { useStore } from '../../store';

function seedRegion(name: string, phase = 'wake', last_error_ts: string | null = null) {
  useStore.setState({
    regions: {
      [name]: {
        role: 'cognitive',
        llm_model: '',
        stats: {
          phase, queue_depth: 0, stm_bytes: 0, tokens_lifetime: 0,
          handler_count: 0, last_error_ts, msg_rate_in: 0, msg_rate_out: 0,
          llm_in_flight: false,
        },
      },
    },
  });
}

beforeEach(() => { useStore.setState({ regions: {} }); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe('Appendix', () => {
  it('renders entries newest-first', async () => {
    vi.spyOn(rest, 'fetchAppendix').mockResolvedValue(
      '## 2026-04-22T10:00:00Z — sleep\n\nfirst entry body\n\n## 2026-04-22T12:00:00Z — sleep\n\nsecond entry body\n',
    );
    seedRegion('pfc');
    const { container, findByText } = render(<Appendix name="pfc" />);
    await findByText(/second entry body/);
    const text = container.textContent ?? '';
    expect(text.indexOf('second entry body')).toBeLessThan(text.indexOf('first entry body'));
  });

  it('shows empty state on 404', async () => {
    vi.spyOn(rest, 'fetchAppendix').mockRejectedValue(new rest.RestError(404, 'missing'));
    seedRegion('fresh');
    const { findByText } = render(<Appendix name="fresh" />);
    expect(await findByText(/No appendix yet — region hasn't slept\./i)).toBeTruthy();
  });

  it('surfaces non-404 errors inline', async () => {
    vi.spyOn(rest, 'fetchAppendix').mockRejectedValue(new rest.RestError(403, 'sandbox'));
    seedRegion('pfc');
    const { findByText } = render(<Appendix name="pfc" />);
    expect(await findByText(/Failed:\s*sandbox/i)).toBeTruthy();
  });

  it('reload triggers refetch', async () => {
    const spy = vi.spyOn(rest, 'fetchAppendix').mockResolvedValue('## 2026-04-22T10:00:00Z — sleep\n\nfirst');
    seedRegion('pfc');
    const { findByText, getByText } = render(<Appendix name="pfc" />);
    await findByText(/first/);
    spy.mockResolvedValue('## 2026-04-22T11:00:00Z — sleep\n\nsecond');
    fireEvent.click(getByText(/reload/i));
    await findByText(/second/);
  });
});
```

Inspector.tsx mount becomes (simple, matching Prompt):
```tsx
<Prompt name={displayName} />
<Appendix name={displayName} />
```

### Drift B — Prompt relabel

Plan Step 4 says change title to `"Prompt (DNA)"`. Current label at `Prompt.tsx:44-47`:
```tsx
<span className="font-semibold">
  Prompt{' '}
  <span className="text-[#8a8e99] text-[10px]">· {sizeLabel}</span>
</span>
```

Change to:
```tsx
<span className="font-semibold">
  Prompt (DNA){' '}
  <span className="text-[#8a8e99] text-[10px]">· {sizeLabel}</span>
</span>
```

Size label (`{sizeLabel}`) unchanged — don't duplicate state; the existing `fmtBytes(data.length)` rendering stays.

### Drift C — Styling: match Prompt's existing class palette

Plan's Step 3 uses `border-t border-[rgba(80,84,96,.35)]` + `summary.cursor-pointer px-3 py-1 text-[11px]` etc. — different alpha values than Prompt's existing `border-b border-[#1f1f27]` + `summary.px-4 py-2`. Inconsistent with v2's inspector visual language.

**Fix:** match Prompt's existing palette:
```tsx
<details open className="border-b border-[#1f1f27]">
  <summary className="px-4 py-2 cursor-pointer flex items-center justify-between">
    <span className="font-semibold">
      Appendix <span className="text-[#8a8e99] text-[10px]">(rolling) · {sizeLabel}</span>
    </span>
    <button
      type="button"
      onClick={(e) => { e.preventDefault(); e.stopPropagation(); reload(); }}
      className="text-[10px] text-[#8a8e99] border border-[#2a2a33] px-2 rounded"
    >
      reload
    </button>
  </summary>
  <div className="px-4 pb-3 text-[11px]">
    {loading && <div className="text-[#8a8e99]">loading…</div>}
    {error && <div className="text-[#ff6a6a]">Failed: {error.message}</div>}
    {!loading && !error && (data === null || data === '') && (
      <div className="text-[#8a8e99]">No appendix yet — region hasn't slept.</div>
    )}
    {entries.length > 0 && (
      <div className="max-h-[360px] overflow-y-auto">
        {entries.map((e, i) => (
          <div key={i} className="mb-2">
            <div className="flex gap-2 items-baseline">
              <span className="font-mono text-[10px] text-[#8a8e99]">{e.ts || '—'}</span>
              {e.trigger && (
                <span className="text-[11px] px-1 rounded bg-[#1e1e26]">{e.trigger}</span>
              )}
            </div>
            <pre className="font-mono text-[10px] whitespace-pre-wrap text-[#cfd2da] opacity-85 mt-1 bg-[#0e0e14] p-2 rounded">{e.body}</pre>
          </div>
        ))}
      </div>
    )}
  </div>
</details>
```

Key changes from plan's Step 3:
- Border/bg palette matches Prompt (`#1f1f27`, `#8a8e99`, `#0e0e14`, `#1e1e26`).
- Summary classes (`px-4 py-2 flex items-center justify-between`) match Prompt.
- Reload button styled to match Prompt's bordered button.
- Body pre uses Prompt's `bg-[#0e0e14] p-2 rounded` treatment for scannable entries.
- Max-height 360 px applied to the entries container, not the outer body (spec §9.1).

### Drift D — Empty-state detection

Per Task 3, `useRegionAppendix` maps 404 → `data: ''` (empty string) and maps non-404 errors → `error: Error`. Plan's Step 3 branches on `data === ''`. That works. But also `data === null` means "not loaded yet" (initial state before first fetch completes). Show loading shimmer for `data === null`, empty-state for `data === ''`:

```tsx
{loading && <div className="text-[#8a8e99]">loading…</div>}
{error && <div className="text-[#ff6a6a]">Failed: {error.message}</div>}
{!loading && !error && data === '' && (
  <div className="text-[#8a8e99]">No appendix yet — region hasn't slept.</div>
)}
{!loading && !error && entries.length > 0 && (...)}
```

(`data === null` during `loading` is covered by the `loading` branch. After loading completes, data is either `''`, a string with content, or error is set.)

---

## Existing-contract surface

**`observatory/web-src/src/inspector/sections/Prompt.tsx`** (current):
- `{name}-only` props, reads stats internally via `useStore((s) => s.regions[name]?.stats)`.
- `firstRef` skip-first-render pattern with `[stats?.phase, stats?.last_error_ts]` deps.
- `<details>` (collapsed by default), `border-b border-[#1f1f27]`, `summary.px-4 py-2`, reload button bordered.
- Size label: `· {fmtBytes(data.length)}` next to `Prompt` label in summary.

**`observatory/web-src/src/inspector/useRegionAppendix.ts`** (Task 3):
- `useRegionAppendix(name) → { loading, error, data, reload }`.
- `data === ''` on 404 (intentional empty).
- `error instanceof Error` on non-404 failures.
- `reload()` re-runs the fetch.

**`observatory/web-src/src/inspector/sections/parseAppendix.ts`** (Task 3):
- `parseAppendix(md) → AppendixEntry[]` with `{ts, trigger, body}`.
- Returns `[]` for empty input, single-entry fallback for no-headings input, multi-entry for normal markdown. **File-order (chronological)**; this component reverses.

**`observatory/web-src/src/inspector/format.ts`**:
- `fmtBytes(n) → string` — already imported by Prompt/Stats/Handlers.

**`observatory/web-src/src/inspector/Inspector.tsx`**:
- Mounts sections with `displayName` (not `name`) to preserve slide-out animation. Prompt: `<Prompt name={displayName} />`.
- You add `<Appendix name={displayName} />` directly after Prompt.

## Gotchas

- **`stats` may be undefined** when the region is mid-registration; the `if (stats) reload();` guard handles it.
- **`data === ''` branch** only fires after initial fetch completes — not during loading.
- **`entries` is the reversed parsed list**; render with `key={i}` is safe because React treats parent list identity (reverse of same data) as stable under the `data` ref not changing.
- **`.reverse()` mutates in place** — but it's called on `parseAppendix(data)`'s fresh output, not stored state. Safe. If you prefer, `[...parsed].reverse()` makes the immutability explicit.
- **`<details open>`** opens by default per spec §9.1 ("expanded by default"). Prompt stays `<details>` (no `open`) to match its existing collapsed-by-default behavior per spec §9.1 "collapsed by default".
- **vitest globals:false** — import explicitly from 'vitest'.
- **`findByText`** auto-awaits; no need for `waitFor` wrapping.

## Verification gates

```
cd observatory/web-src && npx vitest run && npx tsc -b
cd ../.. && .venv/Scripts/python.exe -m ruff check observatory/
```

Expected: **152 → 156 frontend tests** (+4 Appendix tests). tsc clean. Ruff clean.

## Hard rules

- Do NOT touch region_template/, glia/, regions/, bus/, shared/.
- Do NOT modify parseAppendix / useRegionAppendix / format.ts.
- Do NOT push.
- TDD: tests first, red, then green.
- If spec/plan conflict surfaces beyond A-D, stop with NEEDS_CONTEXT.

## Commit HEREDOC

```bash
git add observatory/web-src/src/inspector/
git commit -m "$(cat <<'EOF'
observatory: inspector Appendix section + Prompt DNA relabel (v3 task 8)

Appendix mounts directly below Prompt in the inspector slide-over.
Uses useRegionAppendix (404 → data:''); renders parsed entries
newest-first with timestamp + trigger tag + monospace body. Empty
state fires on 404 ('No appendix yet — region has not slept');
non-404 errors surface as the standard red Failed row. Auto-refetch
on phase/last_error_ts change (skip first render, v2 Task 13 pattern).
Prompt summary relabeled to 'Prompt (DNA)' to reflect post-ecd8a94
immutability.

Appendix prop shape aligned to Prompt's convention ({name}-only; reads
stats internally via useStore) rather than plan's proposed three-prop
signature — Inspector.tsx doesn't have stats in scope, so threading
them through would have required restructuring the slide-over mount.
Styling aligned to Prompt's #1f1f27/#8a8e99/#0e0e14 palette.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

## Report format

1. Status / SHA / files touched
2. Test delta (before/after; 152 → 156 expected)
3. Drift handling (A/B/C/D)
4. Other drift
5. Concerns
