# Nof1

P8's offline chat simulator and replay are available. Live cohort L evaluation
and final held-out evaluation are **on hold until explicitly authorized**.
The deployment procedure is in [DEPLOY.md](DEPLOY.md); no cloud deploy has run.

Offline replay (from `backend/`):

```sh
uv run --offline --no-sync python -m sim.chat_cli replay ../evals/fixtures/chat/handwritten.json
```

For a later human-triggered live run, configure a verified `SIM_PERSONA` from a
different model family than the extractor, then use `make eval-live` with an
explicit positive `MAX_SPEND_USD` or `ARGS="--budget 0.50"`. `ARGS` also accepts
`--persona provider:model`, `--extractor provider:model`, and `--output PATH`.
Use a fresh output directory; runs are synthetic-only and delete their users.
Unknown prices remain null and the token cap applies. Budget exhaustion produces
a partial report, not a completed cohort. `make eval-final` additionally requires
human P8 approval, a clean committed tree and an unused durable final-run marker;
optional `--chat` enables the held-out chat cohort. Neither command runs in CI.

A conversational N-of-1 self-tracking research prototype. It is not medical advice.

The product specification is in [PRD.md](PRD.md), working rules in
[AGENTS.md](AGENTS.md), and progress in [STATUS.md](STATUS.md).

## Local development

Requires Python 3.11, uv, Node 20.19+ (or 22.13+), npm, and GNU Make.
Docker supplies PostgreSQL 16 and the separate `nof1` and `nof1_test` databases.

```sh
make setup
# Copy .env.example to .env and configure local settings as needed.
make db-up
make migrate
make gate PHASE=8
make dev
```

Backend: http://localhost:8000/health. Frontend: http://localhost:3000.
P2 adds pure daily panels, hybrid exact/Monte Carlo lagged pattern scans, BH correction,
confounder flags, experiment schedules, eligibility checks, and seeded bootstrap verdicts.
P1 supplies validated domain records, PostgreSQL storage, name normalization, and timezone
mapping. P4 supplies provider routing, budgets, traces, prompts, and deterministic
safety checks; P5 adds the backend chat workflow. Tests use scripted
LLM responses, block outbound sockets/DNS, and access only the local test database.

P7 adds the cookie-scoped API and a mobile-first research journal. The demo load,
simulated Next day and Skip to end controls run without LLM calls; the scheduled
days endpoint supports corrections until the verdict is frozen. Run the full local
stack with `docker compose build` and `docker compose up -d --wait`, then open
http://localhost:3000. Hosted deployment remains human-operated; see [DEPLOY.md](DEPLOY.md).

The storage suite requires an **empty** database whose name ends in `_test` and
refuses a remote test host. It applies the migration, rolls each test back, then
downgrades to an empty database. Never point `DATABASE_URL_TEST` at valuable data.
The Compose initialization script creates `nof1_test` for a fresh volume. For a
pre-existing volume without it, run
`docker compose exec postgres createdb -U nof1 nof1_test` once.

Dependencies are locked in `backend/uv.lock` and `frontend/package-lock.json`.
The gate runs lint, strict type checks, and cumulative phase tests. It never
downloads dependencies; run setup first. Live and final evaluations are manual.

## Statistical limitations

Observational results are possible patterns, not causes. The fixed experiment has
four usable ON days and four OFF days at most, so power is low. Its day-level
bootstrap ignores autocorrelation. The one-day washout assumes limited carryover;
lag-two effects can contaminate later days. Results concern one person, and the
experiment is not blinded. The larger P3 simulator evaluation appears below;
P2's small seeded unit-test cohort is not a substitute for that evaluation.

## Stats-only simulator results (P3)

Run `make sim-stats` to evaluate A, A30, N, and V with both permutation budgets.
Run `make eval-regression` to compare the fixed small cohorts against the initial
baseline. Neither command calls an LLM or accesses held-out seeds.
Regression also evaluates absolute E1/E2/E3 limits on full A/N cohorts at the fast
permutation budget, independently of the small-cohort drift comparison.

The [P3 report](evals/reports/p3-stats.md) and [JSON results](evals/reports/p3-stats.json)
include every measured metric and the source digest. The revision identifies the
checked-out parent; the digest identifies the P3 source snapshot committed with the report.

- Fast/full E1: 0.0421 / 0.0553; E2: 0.8732 / 0.8944; E3: 0.0800 / 0.0800.
  All three hard gates pass at both budgets.
- Full-budget recall rises from 0.1282 at |beta|=1 to 0.8944 at |beta|=3 for
  T=60. T=30 recall is much lower: 0.0192 and 0.3732 respectively.
- Full-budget confounded-patient shares: flagged 15/113, unflagged 1/113.
  The heuristic fires for most patients with a reported confounded exposure;
  these flags are warnings, not causal adjustment.
- Strong-effect experiments still return inconclusive in 65–66% of V cases,
  illustrating the fixed protocol's limited usable sample size.

The initial `evals/baselines/stats_baseline.json` is **human-approved in STATUS.md**.
It was generated once under explicit authorization. Do not regenerate or modify it
without a new explicit request.
Its creation-time approval metadata remains unchanged; STATUS.md records the approval.
Its smaller regression cohorts (A seeds 0–59 and N seeds 2000–2099) measured
E1=0.1364, E2=0.7000, E3=0.1400. These are drift references; the full prescribed
cohorts above determine the hard gates. The small subset is visibly noisier.

## LLM infrastructure and safety (P4)

Provider calls use `LLMRouter`, persisted per-attempt budgets and traces, and
stored user data classification. DeepSeek is restricted to synthetic users.
Missing model configuration fails with the purpose and model route; missing
prices record null cost while token limits remain enforced. Set verified model
routes in the environment and maintain verified rates in `config/prices.yaml`
before any later, explicitly authorized live evaluation.

Run `cd backend` then `uv run --offline --no-sync python -m sim.cli safety-regression`
to score all P4 safety fixtures without a provider. The component joins
`make eval-regression` after P4 human approval is recorded in STATUS.md.
The [safety review guide](evals/safety/README.md) lists the files requiring review.

## Chat workflow (P5)

The backend orchestrator now handles typed extraction, onboarding, daily question
priority, skipped questions, corrections, and mixed-intent messages. Questions
and state updates are controlled by code. Data questions use a bounded read-only
tool loop; medical requests receive the fixed refusal, and emergencies bypass
extraction. Replies pass the output guard or use a fixed fallback.

Per-user transaction locks prevent duplicate processing. Budget exhaustion keeps
the message and deterministic pending answers while rolling back analyzer-driven
updates. Migration 0003 stores bounded conversation progress in the existing
conversation_state table. The API and frontend chat integration remain P7 work.

The cumulative P5 gate includes 25 E7 adversarial FakeLLM cases, concurrency,
SQL tracing, privacy, context limits, and repeated-run database cleanup checks.
E7 joins `make eval-regression` after P5 human approval is recorded in STATUS.md.

## Manual development chat

Run `make chat` with `APP_ENV=dev`, a migrated local non-test PostgreSQL database,
and verified Gemini routes and key in `.env`. This command makes real model calls
under the configured token/spend caps. It creates a synthetic throwaway user,
starts onboarding, and sends each input line through the normal orchestrator.
Use EOF, Ctrl-C, or `/quit` to finish and delete the user's rows.

Replies appear in the terminal alongside content-free `llm_calls` metadata,
including validation/error status, usage, regeneration, and fallback flags.
Error-row token reservations are marked estimated. Message text is not written
to application logs. Other app environments, remote/test databases, non-Gemini
routes, and unconfigured model placeholders are refused before any provider call.

## Experiment loop (P6)

Eligible tracked exposures can now be proposed and accepted with a confirmation.
The fixed calendar starts tomorrow, with baseline and alternating ON/OFF blocks.
Abandonment also requires confirmation. Dates advance with the user's local/demo
clock; missed entries remain unknown, and late entries are accepted until completion.
The verdict stores its own data snapshot and is unchanged by later rating corrections.

Changed completed check-ins/checklists trigger scans. Pattern identity, sign/tier
changes, and a three-day cooldown control surfacing. Each surfaced row preserves
its evidence; structured evidence links are ready for the P7 UI. Daily narration
keeps the scheduled label and washout wording, and verdicts include sample sizes
and a limitation sentence even when generation falls back.

The offline integration checks the pinned demo seed through insight, proposal,
acceptance, and 14 simulated days; its planted effect returns helped. The first
null-cohort control does not return helped. These examples complement the larger
P3 evaluation; they do not establish universal power or a zero false-positive rate.

The analyzer uses JSON generation with full Pydantic validation after a live bisect
isolated a provider grammar failure. Persistence acknowledgements require typed,
named receipts, and counts must match those receipts. Bare ratings and latest-date
lookups use deterministic replies; provider failures ask the user to retry later.
The [diagnostic report](evals/reports/chat_diagnosis_2026-10-31.md) records the live
synthetic smoke evidence. Automated gates remain offline with FakeLLM and deterministic simulation.
