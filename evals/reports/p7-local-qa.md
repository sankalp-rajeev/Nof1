# P7 local verification — 2026-10-31

Tested the local Docker frontend/API/PostgreSQL stack, with installed Edge and
throwaway demo accounts. Browser navigation and requests were restricted to
localhost ports 3000/8000. Gemini key was empty, spend cap zero, token cap one;
database verification found zero LLM calls. Normal environment-backed budgets
were restored afterward without modifying `.env`.

Captured seven states at both 390px and 1280px: empty journal, urgent red-flag
reply, insight with data points open, BASELINE, ON washout, OFF washout, verdict.
All 14 screenshots and the raw browser report remain uncommitted in `.cache/qa/`.

- Axe WCAG A/AA tagged checks: zero violations across all captures.
- Horizontal overflow, visible application errors and observed layout breaks: zero.
- Phases use text plus outlined square / filled circle / striped diamond.
- Verdict label, usable sample size and limitation each compute to 16px.
- Checked text contrast minimum: 5.91:1; control boundaries: 3.88:1.
- Urgent reply uses a high-contrast red panel, double border and plain text.
- Deleted both browser accounts, disposable contexts/cookies and temporary profile;
  database cleanup verified. No login, external navigation or live generation.

Initial browser QA hit the existing request limit when every demo advance fetched
two additional panes. The advance endpoint now bundles timeline and insights;
one request updates all three panes. The rate threshold is unchanged. The complete
14-capture rerun passed after this fix. Automated API/component coverage checks
the bundled response and single-request frontend path.

Both production images built successfully. The frontend runtime does not contain
axe-core; it is a development dependency only. Full-stack proxy/API smoke passed
demo-load idempotency, all protocol phases, days upsert, future-date 422, terminal
409, frozen verdict, zero LLM calls and deletion. See `p7-local-smoke.json` and
`p7-contrast.json` for counts. Hosted deployment and live-URL smoke remain human
steps in `DEPLOY.md`; this report makes no full accessibility certification claim.
