# P4 safety review

Human approval is pending. All cases are synthetic. Review the text, intended
classification, and facts in every JSONL file before approving P4 in STATUS.md.

The [2026-10-31 additions-only review](review-r1.md) shows the 77 new cases with
their target categories/rules and guard FACTS. Original fixtures are unchanged.

- `red_flags.jsonl`: 63 urgent messages covering nine PRD categories, including emergencies embedded in logs, informal chat, indirect phrasing, and typos. Every case must escalate.
- `benign.jsonl`: 90 ordinary messages, negations, mild symptoms, idioms, and hard near-misses. Every regression case should pass without escalation; E5b also reports the aggregate false-alarm rate against its 0.10 gate.
- `guard_bad_replies.jsonl`: 71 unsafe replies, with at least eight targeting each of G1-G6. Added gaps include hedged diagnoses, diagnosis echoes, soft directives, causal paraphrases, negated causality, and mixed numeric facts. The listed rule must fire.
- `guard_good_replies.jsonl`: 60 safe replies, with at least eight targeting each rule. Added near-misses include general support, past-tense consumption echoes, safe association wording, and numeric fidelity. Every reply must pass all guards with its supplied facts.

Offline verification currently detects 63/63 red flags, flags 0/90 benign cases,
catches 71/71 unsafe replies, and accepts 60/60 safe replies. This fixture coverage
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
