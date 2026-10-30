# STATUS

CURRENT: P0

Rules: one phase at a time. Tick "Gate" only after `make gate PHASE=N` exits 0 and its output is pasted below. Tick "Human" only when the human has approved. Do not start the next phase until told.

| Phase | Name | Gate | Human |
|---|---|---|---|
| P0 | Scaffold and tooling | [x] | [ ] |
| P1 | Domain and storage | [ ] | [ ] |
| P2 | Stats engine | [ ] | [ ] |
| P3 | Simulator (stats-only) and eval harness | [ ] | [ ] |
| P4 | LLM infrastructure and safety | [ ] | [ ] |
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
Needs human: approve P0 with `proceed to P1`; verify model IDs/prices before later live use.
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
