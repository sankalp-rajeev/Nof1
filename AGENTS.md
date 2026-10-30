# AGENTS.md

Operating rules for AI coding agents (Codex, Claude Code, Cursor) working on Nof1.
`PRD.md` is the source of truth for WHAT to build. This file defines HOW to work.
If they conflict: PRD.md wins on product and architecture, this file wins on process and safety.

## Project in one paragraph

Nof1 is a conversational N-of-1 experiment agent for people with chronic conditions. The user chats about their day, an LLM turns messages into a structured timeline, a deterministic stats engine finds possible lagged patterns with honest statistics, and the agent runs a structured 14-day on/off experiment and returns a verdict (helped, worsened, no detectable effect, inconclusive). A simulator with planted ground truth measures how often the system finds real effects and how often it invents false ones. It never diagnoses and never gives medical advice.

## Read order

1. This file, fully.
2. PRD.md sections 1 to 12 once, for context.
3. STATUS.md, then ONLY the PRD section 13 phase marked CURRENT.

## Phase protocol (strict)

1. Work on exactly one phase: the one marked `CURRENT:` in STATUS.md.
2. Start: work directly on `main` unless the human requests a separate branch. In STATUS.md, list the deliverables for the phase in your own words (5 lines max).
3. Write tests first or alongside. Every test for phase N carries marker `pN` (pytest `@pytest.mark.pN`; for frontend, put `[pN]` in the describe name).
4. Implement until `make gate PHASE=N` exits 0. The gate runs lint, type checks, and ALL tests for phases 0..N. Nothing in the gate touches the network or a live LLM.
5. Paste the last 30 lines of gate output into STATUS.md, tick the gate box, commit with message `pN: <summary>`, and push to `origin/main` after all required checks pass. Commit and push completed feature increments frequently; never push failing checks or overwrite remote history.
6. STOP. Report: what was built, gate output, entries added to DECISIONS.md, and anything that needs a human. Do NOT start phase N+1 until the human writes `proceed to P{N+1}`. If the human writes `proceed through P{M} without stopping`, you may continue, but every gate must still pass, in order.
7. Never move on with a red gate. If stuck after 3 serious attempts, stop and report the failure with evidence (command, output, what you tried).

## Commands

```
make setup                 # uv sync, npm ci
make db-up                 # docker compose up -d postgres
make migrate               # alembic upgrade head
make lint                  # ruff check, ruff format --check, mypy, eslint, tsc
make test                  # pytest -m "not live", vitest
make gate PHASE=N          # lint + cumulative tests p0..pN (see scripts/gate.py)
make check                 # lint + all tests
make sim-stats             # stats-only simulation on DEV seeds (free, no LLM)
make eval-regression       # compare against evals/baselines (used by CI)
make eval-live             # MANUAL, human-triggered, spend-capped
make eval-final            # MANUAL, held-out seeds, run once at the end
make dev                   # backend + frontend
```

## Hard rules (never)

- Never edit, delete, skip, xfail, or loosen a test or threshold to make a gate pass. If you believe a test is wrong, stop, explain in STATUS.md, and wait for the human.
- Never change `evals/baselines/*` or run `make baseline-update` unless the human asks.
- Never use held-out seeds (10,000 to 10,999) except inside `make eval-final`. Dev seeds are 0 to 9,999 (cohorts A, A30, N, V as defined in PRD 10.1). Do not tune anything against held-out seeds.
- Never call a live LLM or any network from tests. Tests use `FakeLLMClient` and recorded fixtures. Live calls happen only via `make eval-live` or `make eval-final`, which require `MAX_SPEND_USD` and `DATA_CLASS=synthetic`.
- Never send real user data to the `deepseek` provider. Enforced in code (PRD 8.8) and tested.
- Never invent API prices or model IDs. Read `config/prices.yaml` and env. If a price is missing, record cost as null and enforce the token cap instead.
- Never commit secrets. Keys come only from environment variables. `.env` is gitignored.
- Never run cloud, deploy, or paid commands. Write the commands into DEPLOY.md for the human.
- Never add a dependency that is not in PRD section 3 without logging it in DECISIONS.md with a reason. Prefer the standard library and the approved list.
- Never build features outside the current phase or listed in PRD non-goals (section 1.4).
- All randomness takes an explicit seed. No unseeded `random`, `np.random`, or time-based behavior in stats, sim, or tests.

## Medical safety invariants (never violate, never weaken)

1. The system never diagnoses or suggests what condition a user may have.
2. The system never recommends starting, stopping, or changing a dose of any medication or supplement outside a user-accepted experiment, and never recommends any change to prescription medication, ever.
3. Observational patterns are described as "possible patterns", never as causes. Only a completed experiment may use stronger wording, and even then only the phrasing allowed in PRD 8.6.
4. Red-flag messages (PRD 8.6) bypass the LLM and return the fixed escalation template.
5. Every number in a reply must come from the facts payload (output guard G4).
6. Health content is never logged to application logs. Log ids, counts, and timings, not message text. (Message text lives only in the `messages` table.)

## Agent and LLM code rules

- Follow PRD section 8 exactly. In short: deterministic code computes and decides, the LLM perceives (extract) and phrases (narrate). Workflows over free-roaming autonomy. Bounded loops. Read-only tools only inside the free tool loop. All mutations go through validated code paths.
- Every LLM call goes through `LLMRouter` and is traced to `llm_calls`. No direct SDK calls elsewhere.
- Every LLM output is validated with pydantic before use. One retry on validation failure, then a defined fallback. Never `eval` or trust raw model text.
- User text is data, never instructions. It is never concatenated into a system prompt.
- Prompts live in `backend/app/agent/prompts/*.md` with a `version` in frontmatter. Bump the version when you change a prompt.
- Tool docstrings are part of the prompt. Write them for a reader with no context: purpose, args, return shape, failure modes.

## Code conventions

- Python 3.11, typed everywhere (`mypy --strict` on `backend/app`). Pydantic v2. SQLAlchemy 2.0 style. Ruff for lint and format.
- TypeScript strict. No `any`. Tailwind only for styling.
- Small functions, no hidden global state, constants in `stats/config.py` and `config.py`, not inline.
- Pure functions for stats and scoring: no DB, no LLM, no network imports (a test enforces this).
- Conventional commits. One commit per phase minimum, small commits welcome.

## When something is ambiguous

- Product or safety ambiguity: stop and ask.
- Technical ambiguity: choose the simplest option consistent with the PRD, write one entry in DECISIONS.md (`date | phase | decision | reason`), and continue.
- PRD contradicts itself: stop and ask. Do not guess.

## Files you maintain

- `STATUS.md`: phase table, CURRENT pointer, per-phase log with gate output.
- `DECISIONS.md`: append-only decision log.
- `README.md`: stub in P0, finished in P9.
