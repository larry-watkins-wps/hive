## 2026-04-23T17:32:39+00:00 — heartbeat_cycle

Cold start: no events logged during this wake cycle. STM empty, modulators absent, self-state absent. This is expected for initial boot. Insula has no baseline yet against which to calibrate felt-state labels. First priority on next wake: establish subscription to hive/system/metrics/* topics and begin collecting raw metric streams. Once metric flow is observed, can begin tuning thresholds for compute_load, token_budget, region_health aggregation, and the semantic felt_state classifier. Early handlers will be rule-based (threshold + label lookup); learned calibration will follow after sufficient episodes are stored.

## 2026-04-23T19:58:05+00:00 — heartbeat_cycle

Cold start: insula has no baseline yet. STM and event log are empty because no metrics have flowed. This is expected and correct. The first priority is to confirm MQTT subscriptions to hive/system/metrics/* topics and begin collecting metric snapshots. Early felt_state labels will be rule-based (thresholds + lookup tables); learned calibration—mapping specific metric combinations to semantically meaningful felt states—will emerge only after 10–20 episodes are stored and reviewed. Threshold tuning should begin conservatively: compute_load thresholds at 0.3 (light), 0.6 (moderate), 0.8 (heavy); token_budget at 0.1 (critical), 0.3 (low), 0.7 (comfortable); error_rate at 5% (watch), 10% (concern), 20% (alarm). These will shift as observed outcomes accumulate.

## 2026-04-23T22:07:08+00:00 — heartbeat_cycle

Cold start cycle complete. No metric streams observed yet; MQTT subscriptions to hive/system/metrics/* topics are presumed active but no payloads received during this wake period. STM and event log remain empty, which is expected for initial bootstrap. Next wake cycle should confirm metric flow is reaching insula. If metrics are flowing but not being parsed, check subscription handlers and MQTT broker connectivity. If metrics are still absent, escalate to glia to verify metric publishers are online. Threshold tuning deferred until first episode data is available.
