# Observatory — Implementation Decisions Log

Append-only log of non-obvious calls made during implementation. Format: date · question · call made · rationale.

| Date | Question | Call | Rationale |
|---|---|---|---|
| 2026-04-20 | Should v1 render visible edge lines between regions? | No; v1 uses sparks as the primary edge-activity signal and adjacency drives spring distance only. | Spec §4.3 mentions edge thickness, but sparks carry directional + topic-color information that lines alone cannot. Revisit after visual QA in Task 16; if the scene feels empty between sparks, add thin faded edges as a v1.1 follow-up. |
| 2026-04-20 | Should v1 use the full sandboxed `region_reader.py` from spec §6.5? | No; v1 uses narrow single-purpose reads (`glia/regions_registry.yaml` at startup, `regions/*/subscriptions.yaml` at startup). Full sandboxed reader arrives as v2 Task 1. | V1 REST endpoints (`/api/health`, `/api/regions`) never touch the filesystem per request. Shipping the reader in v1 adds attack surface for no behavioral benefit. |
| 2026-04-20 | Task 1 plan code blocks failed ruff (UP037 quoted `"Settings"`, UP035 `typing.Iterable`, PLR2004 magic `4`). Follow plan verbatim or fix? | Applied minimal mechanical fixes: dropped quotes (safe under `from __future__ import annotations`), imported `Iterable` from `collections.abc`, added `# noqa: PLR2004` on the `len(buf) == 4` assertion. | Plan Step 12 requires ruff clean; workspace root owns lint config and cannot be relaxed per top-level gotcha. Semantics identical. Flag for plan author to update Task 1 code blocks so Tasks 2+ don't inherit the same style drift. |
