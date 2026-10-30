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
make gate PHASE=2
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
experiment is not blinded. The larger simulator evaluation is scheduled for P3;
P2's small seeded unit-test cohort is not a substitute for that evaluation.
