# Observatory — Session Handoff

*Last updated: 2026-04-20*

**Canonical resume prompt:** `continue observatory v1`

---

## State snapshot

| Milestone | Status | Notes |
|---|---|---|
| Brainstorm | ✅ Complete | 2026-04-20 — design approved |
| Spec written | ✅ Complete | `observatory/docs/specs/2026-04-20-observatory-design.md` |
| Plan written | ⏳ Pending | Next step — invoke `superpowers:writing-plans` against the spec |
| v1 implementation | ⏳ Pending | Depends on plan |
| v2 implementation | ⏳ Pending | |
| v3 implementation | ⏳ Pending | |

## What's done

- Brainstorming session 2026-04-20. All five design sections approved (visual vocabulary, region inspector, plumbing, MVP scope, tracking layout).
- Spec committed at `observatory/docs/specs/2026-04-20-observatory-design.md`.
- Scaffolding docs: this file plus `observatory/CLAUDE.md`.

## What's next

Invoke `superpowers:writing-plans` with the spec as input. Output lands at `observatory/docs/plans/2026-04-20-observatory-plan.md` and breaks v1 into task-level steps for `superpowers:subagent-driven-development`.

After the plan exists, the next session's prompt is:

```
continue observatory v1
```

The receiving agent should:

1. Read `observatory/CLAUDE.md`, then this file.
2. Read `observatory/docs/specs/2026-04-20-observatory-design.md` and `observatory/docs/plans/2026-04-20-observatory-plan.md`.
3. Execute Task 1 of the v1 plan via a fresh implementer subagent.

## Follow-ups / open threads

*(Empty. Log anything non-obvious here at session end.)*

## Changelog

| Date | Change |
|---|---|
| 2026-04-20 | Initial handoff — spec + CLAUDE.md + HANDOFF.md created. Plan not yet written. |
