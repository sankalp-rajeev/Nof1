# E4 run 2: aborted infrastructure failure

Fresh E4-only run, 30 patients x 30 days requested, separate from run 1.
Hard limits: $2.00 and 5,000 generation attempts. Neither limit was reached.

- Actual dispatch attempts: 58, including the failed local persona call.
- Exact calculated actual API cost: $0.01148250; unsettled paid reservation: $0.
- Patients processed through completion/dropout: 1/30; turns: 12.
- Original stop: provider_failure at 1:5:free, attempt 58.
- Partial E4 F1: 0.8333333333 (TP 40, FP 9, FN 7). No full-cohort pass.

Ollama's model runner faulted during the in-flight persona call. The human reports
an automatic server restart about 90 seconds later; the local server log confirms
fatal error: fault and Ollama 0.18.2 listening again at 19:23:59.768 local time.
The evaluation had no recovery retries and stopped on the single local failure.

The original configuration, ledger and report are preserved byte-for-byte.
INFRASTRUCTURE_ABORT.json contains reconciliation and original-file hashes.
No run was resumed or merged, and no new generation was used for reporting.
See ../p8-e4-infrastructure-2026-11-04.md for the repair and run-1 cost uncertainty.
