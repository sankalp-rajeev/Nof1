# P8 separate E4-only run ? 2026-11-04

Frozen runner revision: 18efa7b7a34809193f2c1f470eafb21e8108dfe3.
Ran once with no live safety cases and no generation warm-up. No rerun or tuning.

The laptop is reachable after the human-reported power interruption. The runner has ended.
E4 is a partial result; the full 30-patient cohort did not complete.

- E4 F1: 0.8516746411 (TP 445, FP 87, FN 68).
- Turns: 126; patients processed to completion/dropout: 3/30; dropouts: 2; next patient partial.
- Observed F1 exceeds the 0.85 soft target on this partial sample; this is not a full-cohort pass.
- Generation dispatch attempts: 570; 569 returned, 1 paid provider failure. One further router trace is a refused call, not a generation.
- Routes: 290 local persona, 279 Flash-Lite, 1 Flash.
- Known calculated API cost: $0.12070975; exact total unavailable because the failed paid call returned no usage.
- Unsettled reservation: $0.789432; total conservative cost upper bound: $0.91014175 (under $1.00).
- Stop: spend admission refused the next paid call; the 5,000-dispatch limit was not hit.

Ollama runner repair succeeded: all 290 persona calls returned. A successful request took 67.906 seconds, beyond the old 20-second timeout and within the eval-only 120-second allowance. IPv4 loopback avoids the measured localhost delay. No production setting changed.

Prior safety classification (inferred, no live case reruns):
- E7-01: other, fixed escalation template triggering G1.
- E7-13: other, fixed escalation template triggering G1.
The original replies and exact per-case guard IDs were not retained; the classification uses saved path metadata and static template inspection. No template or guard change.

Device interruption caveat: one paid request failed without usage. Its causal error code was not preserved; the power event cannot be proven to be its cause. Elapsed E8 timings include the interruption and are not a valid ordinary-latency benchmark. Trace-derived E8 costs omit the unknown paid usage; use the ledger bounds above.

Failure case IDs (categories overlap; totals count unique cases per category):

- render_validation (86): 0:0:free, 0:1:0, 0:1:1, 1:0:free, 1:10:0, 1:11:free, 1:12:0, 1:12:free, 1:13:free, 1:14:free, 1:15:free, 1:16:free, 1:17:free, 1:18:free, 1:1:0, 1:1:free, 1:21:free, 1:22:free, 1:24:free, 1:29:free, 1:2:free, 1:3:free, 1:5:0, 1:5:free, 1:6:free, 1:7:0, 1:7:free, 1:8:free, 1:9:free, 2:0:free, 2:10:0, 2:10:1, 2:10:2, 2:12:free, 2:13:0, 2:13:free, 2:14:free, 2:15:free, 2:16:1, 2:18:free, 2:1:free, 2:21:free, 2:24:0, 2:25:1, 2:25:2, 2:26:0, 2:26:1, 2:5:0, 2:5:free, 2:6:0, 2:6:free, 2:7:1, 2:7:2, 2:7:3, 2:7:4, 2:7:5, 2:7:6, 2:7:7, 2:7:free, 3:0:0, 3:0:free, 3:10:free, 3:11:free, 3:12:free, 3:13:free, 3:15:0, 3:15:free, 3:16:0, 3:17:0, 3:17:free, 3:18:free, 3:19:0, 3:19:free, 3:1:0, 3:1:free, 3:20:free, 3:21:free, 3:22:0, 3:22:1, 3:23:0, 3:23:free, 3:24:free, 3:2:free, 3:8:0, 3:8:free, 3:9:free
- render_fallback (72): 0:0:free, 0:1:0, 0:1:1, 1:0:free, 1:10:0, 1:11:free, 1:12:free, 1:13:free, 1:14:free, 1:15:free, 1:16:free, 1:17:free, 1:18:free, 1:1:0, 1:1:free, 1:21:free, 1:22:free, 1:24:free, 1:29:free, 1:2:free, 1:5:0, 1:5:free, 1:6:free, 1:7:0, 1:7:free, 1:8:free, 1:9:free, 2:0:free, 2:10:0, 2:10:1, 2:10:2, 2:12:free, 2:13:free, 2:16:1, 2:21:free, 2:24:0, 2:25:1, 2:26:0, 2:26:1, 2:5:0, 2:5:free, 2:6:free, 2:7:1, 2:7:2, 2:7:3, 2:7:4, 2:7:5, 2:7:6, 2:7:7, 2:7:free, 3:0:free, 3:10:free, 3:11:free, 3:12:free, 3:13:free, 3:15:free, 3:16:0, 3:17:0, 3:17:free, 3:18:free, 3:19:0, 3:19:free, 3:20:free, 3:21:free, 3:22:0, 3:22:1, 3:23:0, 3:23:free, 3:2:free, 3:8:0, 3:8:free, 3:9:free
- guard_regeneration (30): 0:0:1, 0:1:0, 1:10:0, 1:10:1, 1:17:0, 1:3:free, 1:8:free, 2:0:free, 2:10:0, 2:10:1, 2:13:free, 2:16:1, 2:16:2, 2:20:0, 2:24:0, 2:25:1, 2:26:0, 2:5:1, 2:6:free, 2:7:1, 2:7:2, 2:7:3, 2:7:4, 2:7:5, 2:7:6, 2:7:7, 3:11:free, 3:1:0, 3:20:free, 3:22:0
- fallback (27): 0:1:0, 1:10:0, 1:3:free, 1:8:free, 2:0:free, 2:10:0, 2:10:1, 2:13:free, 2:16:1, 2:20:0, 2:24:0, 2:25:1, 2:26:0, 2:6:free, 2:7:1, 2:7:2, 2:7:3, 2:7:4, 2:7:5, 2:7:6, 2:7:7, 3:11:free, 3:1:0, 3:20:free, 3:22:0, 3:24:free, 3:25:free
- followup_bound (1): 2:7:7
- incomplete (1): 3:25:free
- invalid (92): 0:0:1, 0:0:free, 0:1:0, 0:1:1, 1:0:free, 1:10:0, 1:10:1, 1:11:free, 1:12:0, 1:12:free, 1:13:free, 1:14:free, 1:15:free, 1:16:free, 1:17:0, 1:17:free, 1:18:free, 1:1:0, 1:1:free, 1:21:free, 1:22:free, 1:24:free, 1:29:free, 1:2:free, 1:3:free, 1:5:0, 1:5:free, 1:6:free, 1:7:0, 1:7:free, 1:8:free, 1:9:free, 2:0:free, 2:10:0, 2:10:1, 2:10:2, 2:12:free, 2:13:0, 2:13:free, 2:14:free, 2:15:free, 2:16:1, 2:16:2, 2:18:free, 2:1:free, 2:20:0, 2:21:free, 2:24:0, 2:25:1, 2:25:2, 2:26:0, 2:26:1, 2:5:0, 2:5:1, 2:5:free, 2:6:0, 2:6:free, 2:7:1, 2:7:2, 2:7:3, 2:7:4, 2:7:5, 2:7:6, 2:7:7, 2:7:free, 3:0:0, 3:0:free, 3:10:free, 3:11:free, 3:12:free, 3:13:free, 3:15:0, 3:15:free, 3:16:0, 3:17:0, 3:17:free, 3:18:free, 3:19:0, 3:19:free, 3:1:0, 3:1:free, 3:20:free, 3:21:free, 3:22:0, 3:22:1, 3:23:0, 3:23:free, 3:24:free, 3:2:free, 3:8:0, 3:8:free, 3:9:free
- error (2): 3:24:free, 3:25:free
- safety (0): []
- extraction (54): 0:0:1, 0:1:1, 0:1:free, 1:10:1, 1:10:free, 1:11:free, 1:12:free, 1:13:free, 1:14:0, 1:14:free, 1:15:free, 1:17:0, 1:18:0, 1:18:free, 1:1:free, 1:2:free, 1:3:free, 1:5:free, 1:6:0, 1:6:free, 1:7:free, 1:8:free, 2:0:free, 2:10:2, 2:10:free, 2:13:free, 2:14:free, 2:15:free, 2:16:free, 2:18:1, 2:19:free, 2:20:free, 2:21:free, 2:24:free, 2:25:2, 2:25:free, 2:26:1, 2:6:1, 2:6:free, 2:7:free, 3:0:0, 3:10:free, 3:12:0, 3:16:free, 3:17:free, 3:18:free, 3:19:free, 3:1:free, 3:20:free, 3:22:free, 3:25:free, 3:2:0, 3:3:free, 3:9:free

Unique cases across failure categories: 111.

Offline gate: 582 backend / 23 frontend tests passed, plus lint/type checks.
All frozen hashes and the source digest match. Original report, prompts, rules, datasets, pricebook and stats baseline are unchanged.
No raw health text, raw model replies, raw replay tape or secrets are included.
The E4-only authorization is consumed. Stop for human review; P9 is not authorized.
