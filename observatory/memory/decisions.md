# Observatory — Implementation Decisions Log

Append-only log of non-obvious calls made during implementation. Format: date · question · call made · rationale.

| Date | Question | Call | Rationale |
|---|---|---|---|
| 2026-04-20 | Should v1 render visible edge lines between regions? | No; v1 uses sparks as the primary edge-activity signal and adjacency drives spring distance only. | Spec §4.3 mentions edge thickness, but sparks carry directional + topic-color information that lines alone cannot. Revisit after visual QA in Task 16; if the scene feels empty between sparks, add thin faded edges as a v1.1 follow-up. |
| 2026-04-20 | Should v1 use the full sandboxed `region_reader.py` from spec §6.5? | No; v1 uses narrow single-purpose reads (`glia/regions_registry.yaml` at startup, `regions/*/subscriptions.yaml` at startup). Full sandboxed reader arrives as v2 Task 1. | V1 REST endpoints (`/api/health`, `/api/regions`) never touch the filesystem per request. Shipping the reader in v1 adds attack surface for no behavioral benefit. |
