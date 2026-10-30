# STATUS

CURRENT: P0

Rules: one phase at a time. Tick "Gate" only after `make gate PHASE=N` exits 0 and its output is pasted below. Tick "Human" only when the human has approved. Do not start the next phase until told.

| Phase | Name | Gate | Human |
|---|---|---|---|
| P0 | Scaffold and tooling | [ ] | [ ] |
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

Append one block per phase:

```
### PN <name>  (date)
Deliverables: ...
Gate output (last 30 lines): ...
Decisions added to DECISIONS.md: ...
Needs human: ...
```
