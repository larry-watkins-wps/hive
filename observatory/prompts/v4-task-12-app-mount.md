# Task 12 — App.tsx mount + production build

You are an implementer subagent for observatory v4 Task 12.

## Scope

Modify exactly one file: `observatory/web-src/src/App.tsx`. Mount `ChatOverlay` and install `useChatKeys` + `useChatPersistence` hooks. Then run the full vitest, typecheck, and production build to verify the integration.

Do NOT modify ChatOverlay, useChatKeys, useChatPersistence, store, or any other file. Do NOT edit anything under `regions/`.

## Repo facts

- Working directory: `C:\repos\hive` (Windows + bash). Vitest + tsc + npm build run from `observatory/web-src/`.
- Current `App.tsx` (lines 1–30) — read this first; the file has a strict-mode-safety comment that must be preserved:

```tsx
import { useEffect } from 'react';
import { Scene } from './scene/Scene';
import { Hud } from './hud/Hud';
import { Inspector } from './inspector/Inspector';
import { Dock } from './dock/Dock';
import { useInspectorKeys } from './inspector/useInspectorKeys';
import { useDockKeys } from './dock/useDockKeys';
import { connect } from './api/ws';
import { useStore } from './store';

export function App() {
  // Strict-mode safe: connect() returns a cleanup that closes the socket; the
  // double mount/unmount in dev is absorbed by the reconnect guard in ws.ts.
  useEffect(() => connect(useStore), []);
  // Window-level keydown bindings for Esc / [ / ] / R. Installed once at the
  // App root so no per-component listeners duplicate. Spec §3.1 / §4.
  useInspectorKeys();
  // Dock-specific keys (spec §4.1): backtick toggles collapse; Space toggles
  // pause when the event target is inside #dock-root.
  useDockKeys();
  return (
    <div className="relative w-full h-full">
      <Scene />
      <Hud />
      <Inspector />
      <Dock />
    </div>
  );
}
```

## What to apply

(a) Add three new imports near the top (after the existing chat-adjacent imports):

```tsx
import { ChatOverlay } from './chat/ChatOverlay';
import { useChatKeys } from './chat/useChatKeys';
import { useChatPersistence } from './chat/useChatPersistence';
```

(b) Inside `App()`, install the chat hooks **after** `useDockKeys()` and add `<ChatOverlay />` as a sibling at the end of the JSX:

```tsx
useChatKeys();
useChatPersistence(useStore);
```

```tsx
<ChatOverlay />
```

The expected final shape of App.tsx:

```tsx
import { useEffect } from 'react';
import { Scene } from './scene/Scene';
import { Hud } from './hud/Hud';
import { Inspector } from './inspector/Inspector';
import { Dock } from './dock/Dock';
import { useInspectorKeys } from './inspector/useInspectorKeys';
import { useDockKeys } from './dock/useDockKeys';
import { ChatOverlay } from './chat/ChatOverlay';
import { useChatKeys } from './chat/useChatKeys';
import { useChatPersistence } from './chat/useChatPersistence';
import { connect } from './api/ws';
import { useStore } from './store';

export function App() {
  // Strict-mode safe: connect() returns a cleanup that closes the socket; the
  // double mount/unmount in dev is absorbed by the reconnect guard in ws.ts.
  useEffect(() => connect(useStore), []);
  // Window-level keydown bindings for Esc / [ / ] / R. Installed once at the
  // App root so no per-component listeners duplicate. Spec §3.1 / §4.
  useInspectorKeys();
  // Dock-specific keys (spec §4.1): backtick toggles collapse; Space toggles
  // pause when the event target is inside #dock-root.
  useDockKeys();
  useChatKeys();
  useChatPersistence(useStore);
  return (
    <div className="relative w-full h-full">
      <Scene />
      <Hud />
      <Inspector />
      <Dock />
      <ChatOverlay />
    </div>
  );
}
```

**Preserve every existing comment exactly.** Do not refactor, reorder, or change other imports. Only add the three chat imports + the two hook calls + the `<ChatOverlay />` child.

## Procedure

1. Read the current `observatory/web-src/src/App.tsx` to confirm it matches the snippet above (drift would be unexpected).
2. Apply the edits in place via `Edit` tool calls (do not rewrite the whole file with `Write`; use surgical edits).
3. Run the full vitest suite: `cd observatory/web-src && npx vitest run`. Expect **207 passed** (no new tests in this task; the App.tsx test environment is already covered by component tests).
4. Run typecheck: `cd observatory/web-src && npx tsc -b` — clean.
5. Run the production build: `cd observatory/web-src && npm run build` — must emit `observatory/web/index.html` + `assets/index-*.{css,js}`. Capture bundle sizes from the output. Chunk-size warning is pre-existing and acceptable.
6. **Self-review:** confirm the diff is minimal (3 added imports, 2 added hook calls, 1 added JSX child); confirm the existing strict-mode comment + the existing inspector/dock comments survive untouched.
7. **Commit** with the verbatim HEREDOC from the plan:

```bash
cd C:/repos/hive
git add observatory/web-src/src/App.tsx
git commit -m "$(cat <<'EOF'
observatory(v4): mount ChatOverlay + chat hooks in App.tsx

ChatOverlay sits as a sibling to Scene/Hud/Inspector/Dock.
useChatKeys + useChatPersistence install at the App root same as
the existing inspector/dock hooks. Spec §6.1.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

## Reporting

Reply DONE / DONE_WITH_CONCERNS / NEEDS_CONTEXT / BLOCKED with: commit SHA, full vitest count, tsc status, npm build status (output bundle paths + sizes). Do not push.
