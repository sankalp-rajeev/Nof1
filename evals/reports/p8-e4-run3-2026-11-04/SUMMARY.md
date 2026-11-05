# E4 run 3: infrastructure/runner warm-up schema stop

This is an incomplete execution, not a completed cohort evaluation. No
pre-registered cohort gate outcome is claimed.

- Generation dispatches: 1, local persona warm-up only.
- Exact provider API cost: $0; unsettled paid hold: $0.
- Returned usage: 275 input / 2 output tokens.
- Cohort turns: 0; processed patients: 0/30; E4: null.
- Original reason: provider_failure / persona_warmup_invalid.

The warm-up returned and failed the old RenderedText check. Its original raw body
was not retained, and normal cleanup deleted the trace row. A separately approved
four-call local diagnostic later reproduced {} with the same usage on both native
and OpenAI-compatible adapters: the required text field was missing. That
diagnostic and the subsequent readiness fix are documented in STATUS.md, with raw
synthetic outputs under .cache. No hardware timeout was established for run 3.

The original configuration, ledger, report and STARTED marker remain unchanged.
The four-run rollup records this as a runner/setup failure separately from the
other infrastructure and budget stops. No run was resumed or merged.
