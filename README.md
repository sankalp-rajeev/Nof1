# Nof1

A conversational N-of-1 self-tracking research prototype. It is not medical advice.

The product specification is in [PRD.md](PRD.md), working rules in
[AGENTS.md](AGENTS.md), and progress in [STATUS.md](STATUS.md).

## Local development

Requires Python 3.11, uv, Node 20.19+ (or 22.13+), npm, and GNU Make.
Docker is needed for PostgreSQL from P1 onward.

```sh
make setup
# Copy .env.example to .env and configure local settings as needed.
make gate PHASE=0
make dev
```

Backend: http://localhost:8000/health. Frontend: http://localhost:3000.
P0 provides scaffolding only; chat, storage, statistics, and LLM routing arrive
in later phases. Tests use scripted LLM responses and block outbound sockets.

Dependencies are locked in `backend/uv.lock` and `frontend/package-lock.json`.
The gate runs lint, strict type checks, and cumulative phase tests. It never
downloads dependencies; run setup first. Live and final evaluations are manual.
