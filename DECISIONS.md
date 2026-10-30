# Decisions

Append-only: date | phase | decision | reason.

- 2026-10-30 | P0 | Model routes default to explicit `provider:CHANGE_ME` placeholders and prices start empty. | Section 15 reserves model IDs and pricing for the human; P0 and its gate require no live model.
- 2026-10-30 | P0 | Use a Python command dispatcher behind Make targets, selecting `npm.cmd` on Windows. | Keep the documented commands portable without depending on Unix shell syntax.
- 2026-10-30 | P0 | Block ordinary test sockets; permit Unix socket pairs and a loopback-only Windows asyncio wake-up pair. | Windows Python 3.11 implements asyncio's internal wake-up pipe with TCP; the health test still runs in process and outbound sockets remain blocked.
- 2026-10-30 | P0 | Use portable GNU Make 4.4.1 from the `gnumake` wheel in an ignored local tools directory. | GNU Make is absent from this Windows machine; it is a development tool, not an application dependency.
- 2026-10-30 | P0 | Use jsdom, PostCSS, and Testing Library jest-dom as frontend development dependencies. | Provide the DOM test environment, Tailwind compilation, and accessible rendering assertions required by the approved frontend stack.
- 2026-10-30 | P0 | Work directly on main and push completed increments after checks pass; publish the user's existing PRD update with the P0 follow-up. | Explicit human override of the separate phase-branch rule; phase boundaries and human approval to begin the next phase still apply.
