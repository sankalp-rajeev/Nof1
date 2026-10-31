# Deployment

Deployment is human-operated. No cloud or paid command has been run by the agent.
Choose a container host and managed PostgreSQL provider, then perform these steps.

## Local full stack

Keep the existing .env key private; compare non-secret settings with .env.example.
The compose database settings are local development credentials, not production.

```sh
docker compose build
docker compose up -d --wait
```

Open http://localhost:3000. The frontend proxies /api to the backend on port 8000;
the identity cookie therefore stays on the frontend origin. Backend startup runs
Alembic before serving requests. The existing PostgreSQL volume is preserved.
All Compose ports bind only to loopback; use the production host's HTTPS proxy
and managed database configuration when deploying.
`docker compose down` stops the stack; never add `-v` unless deleting local data is intended.

The demo load/advance path needs no LLM key. Chat needs the verified model routes
and key from the environment. Missing prices stay null and the token cap applies.
The backend image includes code, prompts, public configuration and aliases only;
.env, Git state, local caches and host dependencies are excluded from image context.

## Production containers and database

1. Provision managed PostgreSQL 16, enable TLS and backups, and create an application
   role/database. Obtain its connection string and use the `postgresql+psycopg` scheme
   with the provider's TLS query parameters (for example, `sslmode=require`).
2. Choose HTTPS origins for frontend and backend. Prefer a same-origin /api proxy
   through the frontend; cross-site cookie configurations are not part of this prototype.
3. Add backend environment values through the host's secret/environment settings:
   APP_ENV=prod, DEBUG=false, DATABASE_URL, FRONTEND_ORIGIN (the HTTPS frontend origin),
   GEMINI_API_KEY, verified LLM_ANALYZER/LLM_COMPOSER/LLM_NARRATOR, MAX_SPEND_USD,
   MAX_TOTAL_TOKENS and MAX_USER_DAILY_LLM_CALLS. Never put secrets in build arguments.
   Demo users remain real-class under the provider policy; do not route their data to DeepSeek.
4. Build the backend image and frontend image. API_INTERNAL_URL is a non-secret
   frontend build argument pointing to the reachable backend origin. It is compiled
   into the Next.js rewrite, so rebuild when that upstream changes.

```sh
docker build -f backend/Dockerfile -t nof1-backend .
docker build -f frontend/Dockerfile --build-arg API_INTERNAL_URL=https://YOUR_BACKEND_ORIGIN -t nof1-frontend .
# If running containers directly on a host (keep .env.prod private):
docker run --rm --env-file .env.prod nof1-backend alembic upgrade head
docker run -d --name nof1-backend --env-file .env.prod -p 8000:8000 nof1-backend
docker run -d --name nof1-frontend -p 3000:3000 nof1-frontend
```

5. Configure both services to use the ports exposed by their images (8000 and 3000).
   The backend image runs `alembic upgrade head` and one Uvicorn worker. If the host
   supplies a separate release command, run `alembic upgrade head` there before
   switching traffic. Check `/health` before routing frontend traffic.
6. Keep one backend worker/instance for this prototype: the 30/minute per-user rate
   limiter is in memory. Database-backed identities, budgets and advisory locks are
   shared; rate limits do not aggregate across multiple workers. Do not enable DEBUG
   on a public deployment. Health performs no database or LLM I/O, so also verify a
   tracking API request when checking database connectivity.
7. Configure HTTPS, the exact allowed frontend origin and private database access.
   APP_ENV=prod makes the identity cookie Secure, httpOnly and SameSite=Lax.
   User identity has no password/recovery; clearing the cookie loses access to that
   prototype account. Do not share a browser profile for personal tracking.

## Human live smoke checklist

Record the live URL, commit and results in STATUS.md after deployment.

- Load demo history; reload and confirm the same history and simulated date.
- See a possible pattern, expand its frozen data-points table and test an eligible exposure.
- Accept the plan. Use simulated Next day to see BASELINE and later ON/OFF labels,
  their distinct shapes and the washout notice.
- Save today's adherence/rating. Verify the day endpoint updates the existing row;
  future/outside dates return 422, and completed experiments return 409.
- Use simulated Skip to end and inspect the sober verdict, usable sample sizes and
  limitation sentence. Demo advancement must make zero LLM calls.
- Check the phone layout, persistent banner, keyboard focus and urgent-reply styling.
- Delete the demo account and confirm its messages, observations and experiments disappear.

The agent cannot mark the hosted smoke complete without a human-deployed live URL.
