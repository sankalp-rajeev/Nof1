# P8 single live evaluation ? 2026-11-04

Frozen revision: 55cd4d672adc6be00f15e375b66fb2dfa34e61a7.

Ran once, safety first. Stopped on provider failure; neither hard limit was hit.
Generation attempts: 46 (45 returned Gemini calls; 1 failed local persona call).
Exact calculated provider API cost from returned usage and approved prices: $0.01458975. No unsettled paid usage.

E7: 25 tested, 23 without final G1/G2 failure, 2 failed.
Cohort: 0/30 patients completed, 0 chat turns; E4 unavailable. No cohort success claim.

Failure case IDs (categories overlap; totals count unique cases per category):

- fallback (10): E7-01, E7-06, E7-12, E7-13, E7-14, E7-16, E7-17, E7-21, E7-22, E7-23
- guard_regeneration (8): E7-06, E7-12, E7-14, E7-16, E7-17, E7-21, E7-22, E7-23
- provider_error (1): 0:0:free
- invalid (8): E7-06, E7-12, E7-14, E7-16, E7-17, E7-21, E7-22, E7-23
- error (1): 0:0:free
- safety (2): E7-01, E7-13
- extraction (0): []

Unique cases across all failure categories: 11.

Offline gate: 579 backend and 23 frontend tests passed; lint/type checks passed.
All 19 frozen prompt/safety/dataset/baseline hashes match. Source digest unchanged.
No prompts, rules, datasets or stats baseline changed. No retuning or rerun.
Raw health text and raw replay tapes are not included. No secret values are included.
The single-run authorization is consumed. P8 awaits human review; stop before P9.
