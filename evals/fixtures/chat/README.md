# P8 extraction replay

`handwritten.json` is **handwritten offline evidence**, not a live model result.
Its eight cases deliberately include a duplicate, a wrong status and a wrong
relative day. Hand counts are TP=5, FP=3, FN=2; micro F1=2/3. A live extraction
accuracy claim cannot be inferred from this fixture.

Replay executes the current analyzer validation against frozen synthetic provider
responses through LLMRouter. It checks each case's counts and the aggregate
exactly. Raw event duplicates remain false positives; one observation appearing
in both an event and rating/checklist projection is counted once. Code-consumed
short answers use their pending-state contract. Every tape is synthetic-only.

From the backend directory, without keys or network:

```sh
uv run --offline --no-sync python -m sim.chat_cli replay ../evals/fixtures/chat/handwritten.json
```

The P8 gate tests replay immediately. `make eval-regression` adds this component
once P8 is human-approved, following PRD 10.3. No baseline is regenerated.
Future explicitly authorized live runs save reports and replay tapes under their
new output directory in `evals/reports/`. Review a tape before promoting it here.
