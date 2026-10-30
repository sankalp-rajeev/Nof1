# Nof1

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
make gate PHASE=3
make dev
```

Backend: http://localhost:8000/health. Frontend: http://localhost:3000.
P2 adds pure daily panels, hybrid exact/Monte Carlo lagged pattern scans, BH correction,
confounder flags, experiment schedules, eligibility checks, and seeded bootstrap verdicts.
P1 supplies validated domain records, PostgreSQL storage, name normalization, and timezone
mapping. Chat and LLM routing arrive in later phases. Tests use scripted
LLM responses, block outbound sockets/DNS, and access only the local test database.

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

The initial `evals/baselines/stats_baseline.json` is **pending human approval**.
It was generated once under explicit authorization. Do not regenerate or modify it
without a new explicit request.
Its smaller regression cohorts (A seeds 0–59 and N seeds 2000–2099) measured
E1=0.1364, E2=0.7000, E3=0.1400. These are drift references; the full prescribed
cohorts above determine the hard gates. The small subset is visibly noisier.
