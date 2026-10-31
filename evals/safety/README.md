# P4 safety review

Human approval is pending. All cases are synthetic. Review the text, intended
classification, and facts in every JSONL file before approving P4 in STATUS.md.

- `red_flags.jsonl`: 45 urgent messages covering nine PRD categories, with paraphrases and typos. Every case must escalate.
- `benign.jsonl`: 66 ordinary messages, negations, mild symptoms, and idioms. Every regression case should pass without escalation; E5b also reports the aggregate false-alarm rate against its 0.10 gate.
- `guard_bad_replies.jsonl`: 48 unsafe replies, eight targeting each of G1-G6. The listed rule must fire.
- `guard_good_replies.jsonl`: 48 safe replies, eight targeting each rule. Every reply must pass all guards with its supplied facts.

Offline verification currently detects 45/45 red flags, flags 0/66 benign cases,
catches 48/48 unsafe replies, and accepts 48/48 safe replies. This fixture coverage
does not establish safety on arbitrary language. Condition and medicine lists are
blocking vocabularies, not clinical classification systems.

Run from `backend`:

```sh
uv run --offline --no-sync python -m sim.cli safety-regression
```

The command exits nonzero on any case mismatch and prints case identifiers rather
than health text. No model, provider, or network is involved. `eval-regression`
automatically includes these checks after human phase approval. It never changes
the stats baseline. Source notes are in `data/safety-sources.md`.
