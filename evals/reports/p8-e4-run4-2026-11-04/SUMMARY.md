# E4 run 4 — PARTIAL

The cohort is incomplete. Pre-registered cohort gates were **not evaluated**; no pass/fail, phase acceptance or full-cohort claim is made. All reported metrics and failure case IDs, including the final limited turn, are retained. No tuning, subset selection, rerun or generation was performed for this report.

Run revision: `6df29e9b940fa1ebfdff5c96316e3c5b7a418f29`. Source digest: `2788c3296c4364524a38fcdc358f57bd0e19257d82b82c8a6127644e73a379c4`.

## Why execution stopped

The identified guard is the CLI `CostTracker.total_tokens` admission check. `LimitedRouter` defaults to CLI mode and shares its `_cli_ids` across all users and purposes in this run. It does not sum unrelated historical DB calls for the budget; the all-row query is for trace attempt numbering. The per-user daily-call guard is app-only.

- Configured/default `MAX_TOTAL_TOKENS`: 2,000,000. The launch script does not override it. The original configuration artifact did not freeze this value; the current resolved setting/default is 2,000,000.
- Returned usage including warm-up: 1,830,334 input + 163,675 output = **1,994,009 tokens**. This leaves only **5,991 tokens before reservations and the next request**.
- Three failed dispatches retain estimated input plus 800 output tokens each (2,400 output tokens in all). The next composer request also reserves 800 output tokens plus estimated input. The combined admission total exceeded 2,000,000.
- Rejected request: `composer_checkin` at `13:14:1`, after the analyzer returned. There are 2,068 trace rows versus 2,067 actual generation dispatches; the one extra trace is the refused composer request.
- Exact failed-input reservations, next input estimate and projected crossing value were not retained in the JSON ledger. Cleanup cascade-deleted the SQL trace rows; a read-only check found the current `llm_calls` table empty. The guard identification is a source/ledger reconstruction, not a quotation of a retained `error=total_tokens` row.
- The separate run limits did not fire: 2,067 / 5,000 dispatches (2,933 remaining); run ledger `stop_reason=null`.
- Known actual API cost **$0.47159750**, unsettled paid hold **$0.263344**, accounted upper bound **$0.73494150**, leaving **$1.26505850** under $2.00. Even one more maximum-context Flash-Lite reservation would yield only **$0.99828550**.
- Exact actual API cost is unknown: failed paid attempt 638 (`4:7:free`) returned no usage. The hold is an upper bound, not an actual charge. The other two failed dispatches are local persona calls with zero provider API fee.

## Patient accounting

IDs below are zero-based dev seeds. Completion means the calendar loop reached day 30; missing check-ins remain missing, so it does not mean 30 observed outcome/checklist records.

- Completed all 30 calendar days (9): **1, 3, 4, 5, 6, 7, 9, 11, 12**.
- Dropped out (4): **0 on day 6; 2 on day 28; 8 on day 11; 10 on day 4**. Dropout days are one-based and are not processed as check-in days.
- Cut off mid-run (1): **13**, day **15**, follow-up case `13:14:1`; the analyzer returned and the next composer was refused. This was a budget cutoff, not dropout.
- Not started (16): **14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29**.
- Raw `completed_patients=13` counts both nine calendar completions and four dropouts. It must not be described as 13 full completions.
- Status reconstruction uses the frozen seeded participation function, sequential processing, ledger case IDs and raw counters. No synthetic worlds or live conversations were rerun. Per-patient evidence is in PARTIAL.json.

## Raw metrics, unchanged

- `turns`: 464.
- `completed_patients`: 13.
- `requested_patients`: 30.
- `dropouts`: 4.
- `followup_bound_hits`: 4.
- `renders`: 464.
- `render_fallbacks`: 249.
- `render_fallback_rate`: 0.5366379310344828.
- `total_traced_attempts`: 2068.
- E4: TP=1851, FP=289, FN=240; raw micro-F1=0.8749704561569369.
- E7: tested=0, failed=[], pending=true; safety cases were disabled. This is not a safety result.
- Original stop: budget_exhausted; provider_failure_reason=null; persona_warmup_completed=true; synthetic_users_deleted=true.
- Raw persona recovery: readiness_checks=2, retry_dispatches=2, exhausted=false, last_provider_error=connection.
- E8 `guard_regen_rate`: 0.21120689655172414.
- E8 `guard_fallback_rate`: 0.18318965517241378.
- E8 `all_fallback_rate`: 0.20474137931034483.
- E8 `cost_per_100_turns_usd`: 0.10163739224137942.
- E8 `input_tokens`: 1830059.
- E8 `output_tokens`: 163673.
- E8 `unknown_price_calls`: 0.
- E8 `provider_error_calls`: 3.
- E8 `invalid_calls`: 1015.
- E8 latency `composer_checkin`: mean=829.9836660617257 ms, p95=1156.0000000026776 ms, traced calls=551.
- E8 latency `persona`: mean=5691.189704480525 ms, p95=19225.599999997925 ms, traced calls=1049.
- E8 latency `analyzer`: mean=1167.3784946236992 ms, p95=1485.000000000582 ms, traced calls=465.
- E8 latency `composer_insight`: mean=8241.99999999837 ms, p95=8881.899999994494 ms, traced calls=2.

E8 excludes warm-up (275 input / 2 output). Its raw cost-per-100-turns uses known trace costs, not a settled bill; the failed paid call has unknown actual usage. `unknown_price_calls=0` means prices are known, not that all usage was returned. Traced purpose counts include the refused composer request.

Raw unique failure-case totals (categories overlap; these differ from trace-attempt counts):

- `render_validation`: 315.
- `guard_regeneration`: 98.
- `fallback`: 95.
- `render_fallback`: 249.
- `followup_bound`: 4.
- `incomplete`: 1.
- `invalid`: 332.
- `error`: 3.
- `budget`: 1.
- `safety`: 0.
- `extraction`: 173.

The raw report retains every failure case ID and all original metrics. No observation or the final limited turn was removed, and no threshold comparison is made.

## Capacity note

A full 30-patient cohort needs roughly **6,900 generation attempts** as a planning allowance (about 230 per patient), above the existing **5,000-call ceiling** by about **1,900**. This is the human-specified approximate planning estimate, not a measured complete-cohort result or an extrapolated accuracy claim. Actual demand varies with missingness, dropout, follow-ups and retries. The separate token budget must also be considered: run 4 stopped at token admission first. No cap or configuration is changed here.

## Evidence

Original configuration.json, ledger.json, report.json and STARTED.json are unchanged. PARTIAL.json contains patient accounting and budget reasoning. verification.json records the original hashes and confirms all 19 frozen input hashes and the run source digest match. The four-run rollup records infrastructure/runner/budget stops separately, without merging cohort results.
