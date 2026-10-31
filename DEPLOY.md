# Deployment

Deployment is human-operated. No cloud or paid command has been run by the agent.
Target: Cloud Run and a Neon Free PostgreSQL 16 project, chosen by the human.

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

## Production topology

One Cloud Run service contains public Next.js on port 3000 and a backend sidecar
on localhost:8000, with one Uvicorn worker. Only the frontend has an ingress port.
Next.js rewrites /api/* and /health using the server-only API_INTERNAL_URL build
setting (never NEXT_PUBLIC_*). Changing the upstream requires a frontend rebuild;
the deployed sidecar upstream stays localhost. Browser requests are relative and
CSP restricts connections to the frontend origin. The host-only nof1_uid cookie
is Secure, httpOnly and SameSite=Lax in production.

## Copy-paste Cloud Run + Neon procedure

Run these commands yourself in **Google Cloud Shell Bash**, from the repository
root. No deployment command below has been run by the agent. Cloud Run, builds,
image storage and secrets can incur charges; Neon must remain on its Free plan.
You need a billing-enabled Google project and permission to enable services,
create service accounts/roles/secrets, push images and deploy Run services/jobs.

Region pairing: Neon AWS `aws-us-east-1` and Cloud Run `us-east4` are both Northern
Virginia. This is cross-cloud: separate cloud regions in the same US East metro, not an
identical cloud region. Neon currently offers AWS regions, not GCP regions.
See [Neon regions](https://neon.com/docs/introduction/regions) and
[Cloud Run locations](https://docs.cloud.google.com/run/docs/locations).

Create the Neon project in us-east-1 **from the start**: an existing project's
region cannot be changed; a different region requires a new project/migration.
First create a **Free**, PostgreSQL **16** Neon project in **AWS US East (N.
Virginia)** in the Neon console. Choose its direct connection (pooling off;
hostname must not contain `-pooler`). Preserve `sslmode=require`; change only
the scheme to `postgresql+psycopg://`. Use this same direct URI for the app and
Alembic. Keep it in Secret Manager, never a file, image, repo, command argument
or chat. No PgBouncer or `prepare_threshold` override is used. The engine uses
pre-ping, a 120-second recycle interval and at most five open connections.
Neon Free [suspends after five idle minutes](https://neon.com/docs/introduction/plans).

If using the current Neon CLI instead of the console, authenticate to your Free
organization first, then create it without exposing connection credentials:

```bash
neon projects create --name nof1 --region-id aws-us-east-1 --pg-version 16 --no-secrets
```

Use CLI 4.9.0 or later: older versions ignore `--no-secrets`. See the official
[project creation reference](https://neon.com/docs/cli/projects). Do not run both
console creation and this alternative; create one project only.

Set public identifiers (the project ID prompt is not a credential):

```bash
set -euo pipefail
set +x
read -rp 'Google Cloud project ID: ' PROJECT_ID
export PROJECT_ID REGION=us-east4 SERVICE=nof1 REPOSITORY=nof1
export TAG="$(git rev-parse --short HEAD)"
export IMAGE_BASE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPOSITORY}"
export RUNTIME_SA="nof1-runtime@${PROJECT_ID}.iam.gserviceaccount.com"
gcloud config set project "$PROJECT_ID"
gcloud services enable run.googleapis.com artifactregistry.googleapis.com secretmanager.googleapis.com
gcloud artifacts repositories create "$REPOSITORY" --repository-format=docker --location="$REGION"
gcloud iam service-accounts create nof1-runtime --display-name='Nof1 runtime'
gcloud auth configure-docker "${REGION}-docker.pkg.dev" --quiet
```

Repository/account/secret creation commands are **first deployment only**. On
later releases reuse them; do not recreate or delete existing resources.
Enter secrets at hidden prompts. `printf` is a Bash builtin; values go over stdin
to Secret Manager, not command arguments or terminal output. Do not enable shell
tracing or paste credentials in commands. These commands create secret version 1:

```bash
gcloud secrets create nof1-gemini-key --replication-policy=automatic
gcloud secrets create nof1-database-url --replication-policy=automatic
read -rsp 'Gemini API key (hidden): ' NOF1_KEY; printf '\n'
printf '%s' "$NOF1_KEY" | gcloud secrets versions add nof1-gemini-key --data-file=-
unset NOF1_KEY
read -rsp 'Neon direct SQLAlchemy URI with sslmode=require (hidden): ' NOF1_DB; printf '\n'
printf '%s' "$NOF1_DB" | gcloud secrets versions add nof1-database-url --data-file=-
unset NOF1_DB
for secret in nof1-gemini-key nof1-database-url; do
  gcloud secrets add-iam-policy-binding "$secret" --member="serviceAccount:${RUNTIME_SA}" --role=roles/secretmanager.secretAccessor
done
```

Build locally in Cloud Shell and push. `.dockerignore` excludes secrets and caches.
The frontend build receives only a non-secret localhost origin; neither image
receives the Gemini key or database URI. Audit dependencies remain build/dev only.

```bash
docker build -f backend/Dockerfile -t "${IMAGE_BASE}/backend:${TAG}" .
docker build -f frontend/Dockerfile --build-arg API_INTERNAL_URL=http://127.0.0.1:8000 -t "${IMAGE_BASE}/frontend:${TAG}" .
docker push "${IMAGE_BASE}/backend:${TAG}"
docker push "${IMAGE_BASE}/frontend:${TAG}"
```

Run the migration as one task **before** serving the release. The job reads the
same direct database secret; it has no Gemini key and cannot generate replies.
For subsequent releases replace `jobs create` with `jobs update`:

```bash
gcloud run jobs create nof1-migrate --region="$REGION" --image="${IMAGE_BASE}/backend:${TAG}" --service-account="$RUNTIME_SA" --command=alembic --args=upgrade,head --tasks=1 --parallelism=1 --max-retries=0 --task-timeout=300s --set-env-vars=APP_ENV=prod,DEBUG=false --set-secrets=DATABASE_URL=nof1-database-url:1
gcloud run jobs execute nof1-migrate --region="$REGION" --wait
```

Obtain the deterministic public Run origin from the project number, then render
the non-secret template and deploy. Port 3000 is the **only ingress port**;
the backend listens on loopback and has one worker. The startup probe orders the
containers. See [Cloud Run sidecars](https://docs.cloud.google.com/run/docs/configuring/services/containers).

```bash
PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"
export FRONTEND_ORIGIN="https://${SERVICE}-${PROJECT_NUMBER}.${REGION}.run.app"
mkdir -p .cache/deploy
python3 - <<'PY'
import os
from pathlib import Path
from string import Template
source = Path('deploy/service.yaml').read_text()
Path('.cache/deploy/service.yaml').write_text(Template(source).substitute(os.environ))
PY
gcloud run services replace .cache/deploy/service.yaml --region="$REGION"
gcloud run services add-iam-policy-binding "$SERVICE" --region="$REGION" --member=allUsers --role=roles/run.invoker
gcloud run services update "$SERVICE" --region="$REGION" --max=1 --min=0
gcloud run services update-traffic "$SERVICE" --region="$REGION" --to-latest
printf 'Open %s\n' "$FRONTEND_ORIGIN"
```

The manifest pins `APP_ENV=prod`, `DEBUG=false`, `MAX_SPEND_USD=0.50`,
`MAX_USER_DAILY_LLM_CALLS=30`, and a conservative `MAX_TOTAL_TOKENS=60000`.
The debug endpoint returns 404 in prod even if DEBUG is accidentally true.
With unverified/missing prices, USD cost is null and the token cap takes over:
**0.50 is not a guaranteed dollar ceiling until config/prices.yaml has verified
model prices**. Do not invent them. Set a provider-side quota as well if a strict
cash ceiling is required. These limits cover model calls, not hosting bills.

Keep **one service instance, one revision receiving traffic, one backend worker**.
The 30-request/minute limiter lives in process memory; extra workers or replicas
would each have an independent bucket. Both service and revision max are one in
the template. Cloud Run can briefly exceed max during maintenance/deployments,
and restarting resets request buckets; do not deploy or split traffic during the
interview. Database-backed daily LLM budgets survive restarts. This is a demo
constraint, not a distributed limiter. See [Cloud Run maximum instances](https://docs.cloud.google.com/run/docs/configuring/max-instances).

### Warm both services before the interview

Cold Cloud Run containers take time to start, and the first DB request must wake
Neon. `/health` alone intentionally does not touch the database. Ten minutes
before the interview, run this **one line** in the same shell. It hits the public
origin only, wakes both layers, and deletes its temporary account/cookie file:

```bash
cookie_jar="$(mktemp)"; (trap 'rm -f "$cookie_jar"' EXIT; curl --fail --silent --show-error --retry 4 --retry-all-errors "$FRONTEND_ORIGIN/health" && curl --fail --silent --show-error --retry 4 --retry-all-errors -c "$cookie_jar" "$FRONTEND_ORIGIN/api/tracking" >/dev/null && curl --fail --silent --show-error -b "$cookie_jar" -X DELETE "$FRONTEND_ORIGIN/api/me")
```

Ten minutes is longer than Neon's five-minute idle timer. **Repeat this line one
minute before the interview**, or use the demo during the intervening time;
a single request ten minutes earlier does not keep a free database awake.
After an idle period, use Load demo history and verify the timeline returns
without a stale-connection error (pre-ping/recycle). No LLM is needed to warm up.

In the browser, check the public demo notice, load demo, run its protocol to a
verdict, then click Delete my data → Confirm delete my data. Verify the empty
journal after reload and that the prior cookie is gone/replaced. Inspect Network:
all requests must remain on the frontend origin. Do not enter real health data.
Cloud-hosted smoke remains human-owned; local checks are recorded in STATUS.md.

### Post-deploy measured latency

After deploying, run this from the same client/location you will use for the
interview. It warms both endpoints, measures nine requests each, deletes its
throwaway account and records medians in this section. It makes no LLM calls.
Run it before opening the interview browser, so it cannot touch that browser's
cookie. Commit the updated DEPLOY.md after recording the live URL and results.

```bash
python3 scripts/measure_deploy.py "$FRONTEND_ORIGIN"
```

<!-- latency:start -->
Pending human deployment: /health median **not measured**; /api/tracking median
**not measured**. No deployed URL exists in this session; local timings would
not measure cross-cloud latency.
<!-- latency:end -->
