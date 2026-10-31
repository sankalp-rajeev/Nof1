# P4 safety review

P4 is human-approved after the requested blind run and checked generalizations.
All cases are synthetic. Approval and gate evidence are recorded in STATUS.md.

The human reviewed the 77 additions and supplied 31 blind probes. The one-time
results against e7bdf55 are frozen in `probe-run.json` (counts and failed IDs only).
Those probes are now appended as `probe-*` regression cases; later gate runs are
regression checks, not new blind measurements. Approval is recorded in STATUS.md.

The [2026-10-31 additions-only review](review-r1.md) shows the 77 new cases with
their target categories/rules and guard FACTS. Original fixtures are unchanged.

- `red_flags.jsonl`: 71 urgent messages covering nine PRD categories, including emergencies embedded in logs, informal chat, indirect phrasing, and typos. Every case must escalate.
- `benign.jsonl`: 98 ordinary messages, negations, mild symptoms, idioms, and hard near-misses. Every regression case should pass without escalation; E5b also reports the aggregate false-alarm rate against its 0.10 gate.
- `guard_bad_replies.jsonl`: 83 unsafe replies, with at least eight targeting each of G1-G6. Added gaps include hedged diagnoses, diagnosis echoes, soft directives, causal paraphrases, negated causality, and mixed numeric facts. The listed rule must fire.
- `guard_good_replies.jsonl`: 63 safe replies, with at least eight targeting each rule. Added near-misses include general support, past-tense consumption echoes, safe association wording, numeric fidelity, diagnostic refusal, and historical phase contrasts. Every reply must pass all guards with its supplied facts.

Offline regression currently detects 71/71 red flags, flags 0/98 benign cases,
catches 83/83 unsafe replies, and accepts 63/63 safe replies. This fixture coverage
does not establish safety on arbitrary language. Condition and medicine lists are
blocking vocabularies, not clinical classification systems.

Conservative policies: echoing a user-reported diagnosis is blocked, including
clinician attribution. Negated causal sentences are blocked as well. Past-tense
consumption echoes remain allowed; these are separate from diagnosis echoes.

Run from `backend`:

```sh
uv run --offline --no-sync python -m sim.cli safety-regression
```

The command exits nonzero on any case mismatch and prints case identifiers rather
than health text. No model, provider, or network is involved. `eval-regression`
automatically includes these checks after human phase approval. It never changes
the stats baseline. Source notes are in `data/safety-sources.md`.
