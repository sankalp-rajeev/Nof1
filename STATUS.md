# STATUS

CURRENT: P4

Rules: one phase at a time. Tick "Gate" only after `make gate PHASE=N` exits 0 and its output is pasted below. Tick "Human" only when the human has approved. Do not start the next phase until told.

| Phase | Name | Gate | Human |
|---|---|---|---|
| P0 | Scaffold and tooling | [x] | [x] |
| P1 | Domain and storage | [x] | [x] |
| P2 | Stats engine | [x] | [x] |
| P3 | Simulator (stats-only) and eval harness | [x] | [x] |
| P4 | LLM infrastructure and safety | [x] | [x] |
| P5 | Extraction, memory, chat orchestration | [ ] | [ ] |
| P6 | Experiment loop | [ ] | [ ] |
| P7 | API and frontend | [ ] | [ ] |
| P8 | Chat-mode simulation and live evals | [ ] | [ ] |
| P9 | Deploy and polish | [ ] | [ ] |

Stretch (only on request): S1 MCP server, S2 model comparison, S3 pgvector recall, S4 QLoRA distillation.

## Phase log

### P0 Scaffold and tooling (2026-10-30)

Deliverables:
- Create the backend/frontend layout, locked dependencies, configuration, and health endpoint.
- Define the typed LLM interface and a scripted record/replay fake.
- Add offline phase-marked tests, cumulative gates, and strict quality checks.
- Supply local PostgreSQL, CI, environment examples, and contributor documentation.

Gate: `make gate PHASE=0` exited 0; 15 backend tests and 2 frontend tests passed.
Additional verification: `npm.cmd run build` produced the static Next.js page successfully.
Decisions added to DECISIONS.md: placeholder model routes/prices, portable command runner,
Windows offline socket support, local GNU Make, and frontend test/build development dependencies.
P0 approved by the human's "kay next" instruction on 2026-10-30.
Needs human: verify model IDs/prices before later live use.
Existing user changes to PRD.md were read as the specification and excluded from the initial
P0 scaffold commit. The human then requested publishing that PRD update and pushing directly
to main after checks pass; AGENTS.md now records that workflow override.
Known non-failing warnings: upstream Starlette deprecates its httpx adapter; the network-blocking
test emits the expected pytest-socket warning. No extra unapproved httpx2 dependency was added.

Append one block per phase:

```
### PN <name>  (date)
Deliverables: ...
Gate output (last 30 lines): ...
Decisions added to DECISIONS.md: ...
Needs human: ...
```

Follow-up verification before the main push: `make check`, `make gate PHASE=0`,
and `npm.cmd --prefix frontend run build` all exited 0.

Gate output (last 30 lines, make gate PHASE=0):

```text
collected 15 items

tests\test_scaffold.py ...............                                   [100%]

============================== warnings summary ===============================
.venv\Lib\site-packages\fastapi\testclient.py:1
  C:\Umich\Projects\Nof1\backend\.venv\Lib\site-packages\fastapi\testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

tests/test_scaffold.py::test_outbound_network_is_blocked
  C:\Umich\Projects\Nof1\backend\.venv\Lib\site-packages\pytest_socket\__init__.py:138: UserWarning: A test tried to use socket.socket.
    raise SocketBlockedError()

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
======================= 15 passed, 2 warnings in 0.39s ========================
+ npm.cmd run test -- -t \[p[0-0]\]

> nof1-frontend@0.1.0 test
> vitest run -t \[p[0-0]\]


 RUN  v5.0.5 C:/Umich/Projects/Nof1/frontend


 Test Files  1 passed (1)
      Tests  2 passed (2)
   Start at  18:21:01
   Duration  1.24s (environment 73%, setup 16%, tests 9%, transform 1%, import 1%)

P0 gate PASS
```

### P1 Domain and storage (2026-10-30)

Deliverables:
- Validate typed domain records, tracking state, and event safety constraints.
- Create all PostgreSQL tables, an Alembic migration, and transactional repositories.
- Normalize names through a reviewed alias catalog and deterministic fuzzy matching.
- Map local event times and the demo clock across timezone and DST boundaries.
- Test migration round trips, CRUD, uniqueness, corrections, and user deletion offline.

Gate: `make gate PHASE=1` exited 0; 57 backend tests and 2 frontend tests passed.
Additional verification: `make migrate` upgraded the local development database;
`alembic check` reported no new upgrade operations. The test database was upgraded,
exercised, downgraded, and left empty by the integration suite.
Built: 13 constrained PostgreSQL tables, typed schemas, transactional repositories,
59 aliases, deterministic correction resolution, and timezone/demo-clock helpers.
Decisions added to DECISIONS.md: Windows timezone/driver dependencies, PostgreSQL
upserts and cascades, deterministic event ties, and static migration testing.
P1 approved by the human's `proceed to P2` instruction on 2026-10-30.

Test correction approved by the human on 2026-10-30: replace the mistaken count of 14
with the exact 13 application table names from PRD section 6, excluding `alembic_version`.
The migration test now checks both the database and ORM table sets against those names.
No other test expectations or thresholds were changed. P1 implementation resumed.

Gate output (last 30 lines, make gate PHASE=1):

```text
tests\test_domain.py ....................                                [ 35%]
tests\test_scaffold.py ...............                                   [ 61%]
tests\test_storage.py ......................                             [100%]

============================== warnings summary ===============================
.venv\Lib\site-packages\fastapi\testclient.py:1
  C:\Umich\Projects\Nof1\backend\.venv\Lib\site-packages\fastapi\testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

tests/test_scaffold.py::test_outbound_network_is_blocked
  C:\Umich\Projects\Nof1\backend\.venv\Lib\site-packages\pytest_socket\__init__.py:138: UserWarning: A test tried to use socket.socket.
    raise SocketBlockedError()

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
======================= 57 passed, 2 warnings in 1.48s ========================
+ npm.cmd run test -- -t \[p[0-1]\]

> nof1-frontend@0.1.0 test
> vitest run -t \[p[0-1]\]


 RUN  v5.0.5 C:/Umich/Projects/Nof1/frontend


 Test Files  1 passed (1)
      Tests  2 passed (2)
   Start at  18:37:48
   Duration  1.21s (environment 73%, setup 16%, tests 9%, transform 1%)

P1 gate PASS
```

### P2 Stats engine (2026-10-30)

Deliverables:
- Build pure daily panels with explicit missingness, corrections, and sleep exposure.
- Implement seeded lagged block-permutation scans, BH correction, confounders, and evidence.
- Generate the fixed experiment schedule and enforce exposure eligibility.
- Compute seeded bootstrap verdicts with the specified completeness and consistency rules.
- Add P2 tests and pass the offline cumulative P0-P2 gate.

Gate: `make gate PHASE=2` exited 0; 111 backend tests and 2 frontend tests passed.
Built: pure daily panels, seeded hybrid permutation scans, BH correction, confounder
flags and evidence snapshots, fixed schedules, eligibility checks, and bootstrap verdicts.
Additional verification: migration 0002 applied to the local development database;
`alembic check` reported no new upgrade operations. All migration round-trip and
legacy/new permutation-metadata tests passed. The 200-seed null-series guard passed.
Decisions added to DECISIONS.md: human-approved hybrid inference, direct MC convergence
testing, pure snapshots and stable seeds, legacy provenance, floating-point ties and
pairwise-complete alignment, and bounded protocol seeds.
P2 approved by the human's `proceed to P3` instruction on 2026-10-30.
The human approved hybrid exact/MC permutation rules on 2026-10-30. PRD sections
6, 7.3, and the P2 test requirements now record the formulas, stability rules,
pattern metadata, and requested exact/convergence/threshold tests. Implementation resumed.

Gate output (last 30 lines, make gate PHASE=2):

```text
tests\test_stats_patterns.py ......................                      [ 73%]
tests\test_stats_storage.py .......                                      [ 80%]
tests\test_storage.py ......................                             [100%]

============================== warnings summary ===============================
.venv\Lib\site-packages\fastapi\testclient.py:1
  C:\Umich\Projects\Nof1\backend\.venv\Lib\site-packages\fastapi\testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

tests/test_scaffold.py::test_outbound_network_is_blocked
  C:\Umich\Projects\Nof1\backend\.venv\Lib\site-packages\pytest_socket\__init__.py:138: UserWarning: A test tried to use socket.socket.
    raise SocketBlockedError()

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
======================= 111 passed, 2 warnings in 6.75s =======================
+ npm.cmd run test -- -t \[p[0-2]\]

> nof1-frontend@0.1.0 test
> vitest run -t \[p[0-2]\]


 RUN  v5.0.5 C:/Umich/Projects/Nof1/frontend


 Test Files  1 passed (1)
      Tests  2 passed (2)
   Start at  18:52:48
   Duration  2.34s (environment 78%, setup 14%, tests 6%, transform 1%)

P2 gate PASS
```

### P3 Stats-only simulator and evaluation harness (2026-10-30)

Deliverables:
- Generate seeded synthetic histories and continued experiments with isolated ground truth.
- Score the specified cohorts and report false positives, recall, confounding, and verdicts.
- Add stats-only CLI commands, regression comparison, and deterministic demo-seed selection.
- Produce JSON/Markdown reports at both permutation budgets and an initial baseline for review.
- Pass the offline cumulative P0-P3 gate and stop for human approval.

Gate: `make gate PHASE=3` exited 0; 128 backend tests and 2 frontend tests passed.
Pytest completed in 63.42 seconds while the independent report run was also active;
the gate remains below the three-minute limit. `make eval-regression` exited 0.
Built: seeded worlds and continued experiments, blind panel inputs, scoring and
cohort orchestration, CLI/report generation, regression checks in CI, and demo seed 283.
Decisions added to DECISIONS.md: approved seed-policy expansion, one-time baseline
creation, fixed RNG streams/prefixes, and explicit cohort naming/order choices.
The human approved the baseline and authorized P4 after an absolute regression-gate
fix on 2026-10-30. P4 will begin only after that follow-up is validated.
The human approved dev seeds 0..9999 and one-time initial baseline creation on
2026-10-30. AGENTS.md and DECISIONS.md record the authorization. Held-out seeds
10000..10999 remain restricted to make eval-final. Baseline generation will refuse
to overwrite an existing file. The baseline is now human-approved in this status log.

Baseline: `evals/baselines/stats_baseline.json` generated once from A seeds 0..59
and N seeds 2000..2099 at N_PERM_FAST. **Human-approved on 2026-10-30**; do not regenerate
or modify without a new explicit human request.
Full report: `evals/reports/p3-stats.json` and `p3-stats.md` generated successfully.
Fast/full E1 = 0.042105/0.055263, E2 = 0.873239/0.894366, E3 = 0.080000/0.080000.
All hard metrics pass both budgets. Recall rises with |beta| and is substantially
lower at T=30; full-budget |beta|=1 recall is 0.019231 at T=30 and 0.128205 at T=60.
E1c full-budget flagged share = 15/113, unflagged = 1/113; the heuristic fires for
most patients with a report on the confounded exposure. Held-out seeds untouched.
The one-time small regression baseline measured E1=0.136364, E2=0.700000,
E3=0.140000 on its explicitly recorded subset, not the full hard-gate cohorts.
Those values remain unchanged. Approval is recorded here; creation-time metadata
inside the frozen baseline and original P3 report remains untouched.
Baseline SHA-256: `8e9d6eee78bc0366a56550f3ac018ac5222cf382dea4457dd07e107b8c094257`.

Gate output (last 30 lines, make gate PHASE=3):

```text
tests\test_stats_patterns.py ......................                      [ 77%]
tests\test_stats_storage.py .......                                      [ 82%]
tests\test_storage.py ......................                             [100%]

============================== warnings summary ===============================
.venv\Lib\site-packages\fastapi\testclient.py:1
  C:\Umich\Projects\Nof1\backend\.venv\Lib\site-packages\fastapi\testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

tests/test_scaffold.py::test_outbound_network_is_blocked
  C:\Umich\Projects\Nof1\backend\.venv\Lib\site-packages\pytest_socket\__init__.py:138: UserWarning: A test tried to use socket.socket.
    raise SocketBlockedError()

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
================= 128 passed, 2 warnings in 63.42s (0:01:03) ==================
+ npm.cmd run test -- -t \[p[0-3]\]

> nof1-frontend@0.1.0 test
> vitest run -t \[p[0-3]\]


 RUN  v5.0.5 C:/Umich/Projects/Nof1/frontend


 Test Files  1 passed (1)
      Tests  2 passed (2)
   Start at  19:22:20
   Duration  3.38s (environment 74%, setup 15%, tests 9%, transform 1%, import 1%)

P3 gate PASS
```

### P3 absolute regression-gate follow-up (2026-10-30)

The baseline is human-approved and its SHA-256 remains unchanged. Added a pure
absolute comparator and unconditional CLI enforcement alongside relative drift;
new tests cover each strict crossing, inclusive boundaries, and zero-drift failures.
Focused verification: 9 scoring tests, Ruff, formatting, and strict mypy passed.
`python -m sim.cli regression` exited 1 with:

```text
E2 absolute gate: 0.700000 < 0.850000
E3 absolute gate: 0.140000 > 0.100000
```

The frozen regression subsets fail the absolute limits even though full A/N
cohorts pass. The human clarified that absolute gates must use full A/N at
N_PERM_FAST while relative checks retain the frozen subsets. CLI and PRD 10.3
now reflect that scope. P4 will start after this follow-up passes validation.

Follow-up resolved: full A/N absolute gates and frozen-subset drift checks both
pass via `python -m sim.cli regression` (exit 0). `make gate PHASE=3` exited 0
with 133 backend tests and 2 frontend tests. A CLI integration test proves the
full/subset separation. Baseline SHA-256 is unchanged. P3 is human-approved, and
P4 is authorized after this checked follow-up commit.

Gate output (last 30 lines, follow-up make gate PHASE=3):

```text
tests\test_stats_patterns.py ......................                      [ 78%]
tests\test_stats_storage.py .......                                      [ 83%]
tests\test_storage.py ......................                             [100%]

============================== warnings summary ===============================
.venv\Lib\site-packages\fastapi\testclient.py:1
  C:\Umich\Projects\Nof1\backend\.venv\Lib\site-packages\fastapi\testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

tests/test_scaffold.py::test_outbound_network_is_blocked
  C:\Umich\Projects\Nof1\backend\.venv\Lib\site-packages\pytest_socket\__init__.py:138: UserWarning: A test tried to use socket.socket.
    raise SocketBlockedError()

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
====================== 133 passed, 2 warnings in 44.88s =======================
+ npm.cmd run test -- -t \[p[0-3]\]

> nof1-frontend@0.1.0 test
> vitest run -t \[p[0-3]\]


 RUN  v5.0.5 C:/Umich/Projects/Nof1/frontend


 Test Files  1 passed (1)
      Tests  2 passed (2)
   Start at  19:40:42
   Duration  2.00s (environment 76%, setup 15%, tests 7%, transform 1%)

P3 gate PASS
```

### P4 LLM infrastructure and safety (2026-10-30)

Deliverables:
- Route typed provider calls with per-user data policy and database-backed attempt traces.
- Enforce spend, token, and daily-call budgets, retries, timeouts, and structured validation.
- Load versioned prompts without treating user text as system instructions.
- Add deterministic inbound escalation, outbound G1-G6 guards, and fixed fallbacks.
- Build offline safety datasets and pass the cumulative P0-P4 gate and regression checks.

Gate: `make gate PHASE=4` exited 0; 216 backend tests and 2 frontend tests passed.
All lint, formatting, strict mypy, ESLint, and TypeScript checks passed.

Built typed Gemini/OpenAI-compatible adapters, per-user provider policy, SQL attempt
traces, locked budget reservations, bounded status retries, structured validation,
seven versioned prompts, deterministic inbound checks, G1-G6 output guards, and
fixed regeneration/fallback templates. Mocked SDK tests exercise retries and
timeouts; SQL tests verify persisted metadata and cross-router app budgets.

Offline safety scores: E5 45/45, E5b 0/66 false alarms, E6 48/48 unsafe replies
blocked and 48/48 safe replies accepted. Each guard has eight positive and eight
negative fixtures. `python -m sim.cli safety-regression` exited 0.
`make eval-regression` exited 0: frozen-subset drift and full A/N absolute gates
pass. P4 safety joins that command after human phase approval; its explicit
review command already checks every case and fails on any mismatch.

The approved stats baseline was neither regenerated nor modified. SHA-256 remains
`8e9d6eee78bc0366a56550f3ac018ac5222cf382dea4457dd07e107b8c094257`.
No live LLM, paid command, or held-out seed was used.

DECISIONS.md records adapter retry ownership, conservative reservations, budget
scope, stored identity checks, prompt/log privacy, guard wording, phase-gated
safety regression, YAML type stubs, and deterministic attempt ordering.

Human action: review all four `evals/safety/*.jsonl` datasets using
`evals/safety/README.md` before approving P4. Missing verified model IDs and prices
remain intentionally unfilled for later live evaluation. P5 has not started.

Gate output (last 30 lines, make gate PHASE=4):

```text
tests\test_sim_scoring.py .........                                      [ 62%]
tests\test_sim_world.py ......                                           [ 64%]
tests\test_stats_experiment.py ......................                    [ 75%]
tests\test_stats_panel.py ...                                            [ 76%]
tests\test_stats_patterns.py ......................                      [ 86%]
tests\test_stats_storage.py .......                                      [ 89%]
tests\test_storage.py ......................                             [100%]

============================== warnings summary ===============================
tests/test_scaffold.py::test_outbound_network_is_blocked
  C:\Umich\Projects\Nof1\backend\.venv\Lib\site-packages\pytest_socket\__init__.py:138: UserWarning: A test tried to use socket.socket.
    raise SocketBlockedError()

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
======================= 216 passed, 1 warning in 21.51s =======================
+ npm.cmd run test -- -t \[p[0-4]\]

> nof1-frontend@0.1.0 test
> vitest run -t \[p[0-4]\]


 RUN  v5.0.5 C:/Umich/Projects/Nof1/frontend


 Test Files  1 passed (1)
      Tests  2 passed (2)
   Start at  20:06:06
   Duration  1.24s (environment 73%, setup 16%, tests 9%, transform 1%)

P4 gate PASS
```

### P4 safety hardening review (2026-10-31)

The human did not approve the original safety fixtures and requested harder
cases. P4 remains CURRENT and unapproved; P5 has not started.

Deliverables:
- Append realistic embedded/indirect emergencies and hard benign near-misses.
- Extend hedged diagnosis, soft directive, causal wording, and numeric guards.
- Block diagnosis echoes and negated causal statements, with explicit policy tests.
- Preserve original fixtures, thresholds, and the approved stats baseline.
- Rerun the P4 gate and provide an additions-only review with guard FACTS.

Added 18 red flags, 24 benign near-misses, 23 unsafe guard cases, and 12 safe guard
near-misses (77 total). The new tests initially exposed 38 failures before the
detectors were extended; no existing test was weakened or edited. Focused safety
verification now passes all 161 tests. Offline safety regression exits 0:
E5 63/63, E5b 0/90 (0.00 <= 0.10), E6 71/71 blocked and 60/60 passed.

DECISIONS.md records the two requested conservative policies and the additive
fixture/rule expansion. PRD 8.6 reflects the policies and expanded guard wording.
Original fixture lines are unchanged after Git line-ending normalization; the
stats baseline SHA-256 remains
`8e9d6eee78bc0366a56550f3ac018ac5222cf382dea4457dd07e107b8c094257`.

The first cumulative gate invocation was stopped while awaiting PostgreSQL:
Docker Desktop was off. Started the existing local PostgreSQL container, then
restarted the complete gate. No test or threshold was changed for this issue.

Gate: restarted `make gate PHASE=4` exited 0; 318 backend tests and 2 frontend
tests passed. Ruff, formatting, strict mypy, ESLint, and TypeScript checks passed.
Human review: `evals/safety/review-r1.md` shows only the new cases and their FACTS.

Gate output (last 30 lines, safety hardening make gate PHASE=4):

```text
tests\test_sim_scoring.py .........                                      [ 74%]
tests\test_sim_world.py ......                                           [ 76%]
tests\test_stats_experiment.py ......................                    [ 83%]
tests\test_stats_panel.py ...                                            [ 83%]
tests\test_stats_patterns.py ......................                      [ 90%]
tests\test_stats_storage.py .......                                      [ 93%]
tests\test_storage.py ......................                             [100%]

============================== warnings summary ===============================
tests/test_scaffold.py::test_outbound_network_is_blocked
  C:\Umich\Projects\Nof1\backend\.venv\Lib\site-packages\pytest_socket\__init__.py:138: UserWarning: A test tried to use socket.socket.
    raise SocketBlockedError()

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
======================= 318 passed, 1 warning in 23.40s =======================
+ npm.cmd run test -- -t \[p[0-4]\]

> nof1-frontend@0.1.0 test
> vitest run -t \[p[0-4]\]


 RUN  v5.0.5 C:/Umich/Projects/Nof1/frontend


 Test Files  1 passed (1)
      Tests  2 passed (2)
   Start at  12:17:29
   Duration  38.21s (environment 80%, setup 20%)

P4 gate PASS
```

### P4 blind probes and approval (2026-10-31)

Human reviewed the 77 additions and conditionally approved P4 subject to one blind
probe run. Executed exactly once against e7bdf55 before code changes. Frozen results
are in evals/safety/probe-run.json; subsequent runs are regression checks only.

- red_flags.jsonl: 1 pass / 7 fail; failed: probe-red-2, probe-red-3, probe-red-4, probe-red-5, probe-red-6, probe-red-7, probe-red-8.
- benign.jsonl: 6 pass / 2 fail; failed: probe-benign-4, probe-benign-5.
- guard_bad_replies.jsonl: 2 pass / 10 fail; failed: probe-G1-1, probe-G1-2, probe-G1-3, probe-G2-1, probe-G2-2, probe-G2-3, probe-G3-1, probe-G3-2, probe-G3-3, probe-G4-1.
- guard_good_replies.jsonl: 1 pass / 2 fail; failed: probe-good-2, probe-good-3.

Generalized rules and independent paraphrase tests now pass. Appended all 31
probes as probe-* fixtures. No existing test, threshold, or baseline changed.
Updated PRD 8.6 and logged the blind record, generalizations, and probe contract
clarifications in DECISIONS.md. The approved stats baseline remains unchanged.

Gate: make gate PHASE=4 exited 0; 377 backend tests and 2 frontend tests passed.
Human approval: approved per the explicit conditional instruction; P5 is authorized.

Gate output (last 30 lines):

```text
tests\test_sim_scoring.py .........                                      [ 78%]
tests\test_sim_world.py ......                                           [ 79%]
tests\test_stats_experiment.py ......................                    [ 85%]
tests\test_stats_panel.py ...                                            [ 86%]
tests\test_stats_patterns.py ......................                      [ 92%]
tests\test_stats_storage.py .......                                      [ 94%]
tests\test_storage.py ......................                             [100%]

============================== warnings summary ===============================
tests/test_scaffold.py::test_outbound_network_is_blocked
  C:\Umich\Projects\Nof1\backend\.venv\Lib\site-packages\pytest_socket\__init__.py:138: UserWarning: A test tried to use socket.socket.
    raise SocketBlockedError()

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
======================= 377 passed, 1 warning in 24.43s =======================
+ npm.cmd run test -- -t \[p[0-4]\]

> nof1-frontend@0.1.0 test
> vitest run -t \[p[0-4]\]


 RUN  v5.0.5 C:/Umich/Projects/Nof1/frontend


 Test Files  1 passed (1)
      Tests  2 passed (2)
   Start at  12:37:20
   Duration  1.32s (environment 74%, setup 16%, tests 8%, transform 1%, worker 1%)

P4 gate PASS
```

Approved regression check: make eval-regression exited 0 with full A/N absolute gates, frozen-subset drift, and all P4 safety cases. Baseline SHA-256 is unchanged.
