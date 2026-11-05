# E4 infrastructure aborts and runner repair

Both E4-only runs are **aborted infrastructure failures**, not completed cohort
evaluations. Their original reports and ledgers remain unchanged and separate.
The classifications, cost reconciliation and original-file SHA-256 hashes are in
`p8-e4-infrastructure-2026-11-04.json` and each run's `INFRASTRUCTURE_ABORT.json`.

Run 1 (`p8-e4-2026-11-04`): 570 generation attempts, 3/30 patients processed through
completion or dropout, 126 turns. Human reports laptop shutdown under sustained GPU
load. The recorded stop is `budget_exhausted` / `spend_admission_cap`: a paid failure
retained its conservative reservation, after which the next paid admission failed.
Known actual API cost is **$0.12070975**. Exact total is **unknown** because the paid
failure returned no usage; the retained reservation is **$0.789432**, giving a
conservative total upper bound of **$0.91014175**. The original paid error code was
not retained, so the shutdown's causal link to that call cannot be proved from its
ledger. Partial F1 is 0.8516746411; it is not a full-cohort pass.

Run 2 (`p8-e4-run2-2026-11-04`): 58 generation attempts, 1/30 patients processed
through completion or dropout, 12 turns. Exact calculated actual API cost is
**$0.01148250**, with no unsettled paid reservation. Attempt 58, `1:5:free`, is a
failed local persona call. The recorded stop is `provider_failure`. Human reports
an Ollama model-runner fault and automatic server restart about 90 seconds later;
the local server log confirms `fatal error: fault` and Ollama 0.18.2 listening again
at 19:23:59.768 America/New_York. Partial F1 is 0.8333333333; it is not a full-cohort
pass. No retries existed around that failed call.

Repair scope: at most four additional local-persona dispatches, each gated by a
read-only server check, with four 45-second recovery slots. Maximum deliberate
backoff is 180 seconds; inventory probes have a three-second timeout, and each
generation retains its separate 120-second timeout. Unavailable-server slots do
not dispatch generation. Every actual retry passes the existing router, trace and
global call/spend ledger. Exhaustion stops with `persona_retries_exhausted` and
records the last provider code and recovery counters.

The eval persona uses native `/api/chat` with `keep_alive=24h`. The installed
Ollama 0.18.2 OpenAI adapter has no keep-alive field, so an extra OpenAI request
field would be ignored. Native request options reproduce its existing conversion:
same message content, JSON mode, temperature, output limit, and top_p=1. Production
and paid-provider adapters remain unchanged. One schema-validated, routed and
metered warm-up request is made before the cohort, using the existing persona
prompt with an empty observation list. Its latency and output are excluded from
cohort E8 and E4; its calls/costs still count toward the run limits.

Item 3 uses the human-authorized fallback: no crash-resume capability is added.
Safe resumption needs coordinated patient/metric checkpoints and cumulative budget
restoration, beyond this repair. Existing one-shot claims are retained.

No live generation was performed for this repair or report. The original 19 frozen
input hashes match; no prompt, rule, dataset, baseline, model or price changes.
Run 3 and P9 remain unauthorized.

Transport references: [installed-version conversion](https://github.com/ollama/ollama/blob/v0.18.2/openai/openai.go)
and [native chat API](https://docs.ollama.com/api/chat).
