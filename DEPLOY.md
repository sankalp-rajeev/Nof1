# Deployment

Cloud provisioning, image builds, deployment and teardown commands are human-operated.
The agent ran the requested no-LLM hosted latency measurement after the human
deployed the services. No live evaluation or held-out evaluation has run.

## Deployed setup

- Project: `nof1-demo`; Cloud Run and Artifact Registry region: `us-east4`.
- Frontend: https://nof1-frontend-196912573980.us-east4.run.app
- Backend: https://nof1-backend-196912573980.us-east4.run.app
- Confirmed frontend revision: `nof1-frontend-00001-kk9`.
- Confirmed backend revision after origin configuration: `nof1-backend-00002-m5h`.
- Both services serve 100% of traffic on their confirmed revision.
- Neon Free, PostgreSQL 16, AWS US East (N. Virginia), `aws-us-east-1`.

The human chose two separate public Cloud Run services for this deployment.
The frontend proxies `/api/*` and `/health` to the backend using the server-only
`API_INTERNAL_URL` supplied when the frontend image is built. Browser requests
stay on the frontend origin. Changing that upstream requires a frontend rebuild.
`deploy/service.yaml` is the earlier sidecar reference, not this deployment's manifest.

The backend uses one Uvicorn worker and zero-to-one instances. The frontend also
uses zero-to-one instances. Service and revision maxima are both one; traffic
is not split. The request limiter is process-local, while daily LLM budgets are
stored in Postgres. Cloud Run may briefly overlap instances during releases or
maintenance; avoid releases during a demo. This is not a distributed limiter.

The backend identity is `nof1-runtime@nof1-demo.iam.gserviceaccount.com` with
accessor grants on the two individual existing secrets, `nof1-database-url` and
`nof1-gemini-api-key`. The frontend uses `nof1-frontend-runtime` with no secret
grants or attachments. Production identity cookies are host-only, Secure,
httpOnly and SameSite=Lax. The backend's `FRONTEND_ORIGIN` is the frontend URL above.

Public runtime settings live in `deploy/backend.env.yaml` and
`deploy/frontend.env.yaml`. Backend settings include `APP_ENV=prod`, `DEBUG=false`,
`MAX_SPEND_USD=0.50`, `MAX_USER_DAILY_LLM_CALLS=30` and `MAX_TOTAL_TOKENS=60000`.
Approved model routes are recorded in the backend environment file. Prices in
`config/prices.yaml` are still unset: cost remains null and the token cap applies.
The USD setting is not a verified dollar ceiling and does not cover hosting.

## PowerShell procedure

Run from `C:\Umich\Projects\Nof1` in Windows PowerShell with gcloud logged in and
billing enabled. Completed steps are recorded below; do not recreate resources
or rerun the walkthrough merely to verify this document. For future code releases,
choose a fresh image tag and rebuild the affected image instead of overwriting
the deployed `45d6fdb` tag.

### 1. Enable APIs

```powershell
gcloud services enable run.googleapis.com artifactregistry.googleapis.com cloudbuild.googleapis.com secretmanager.googleapis.com iam.googleapis.com --project=nof1-demo
$LASTEXITCODE
```

The first command enables deployment/build/secret/identity APIs; good result is
successful completion. The second reports its exit code; good result is `0`.
Human confirmed both. Existing secrets are reused, not created again.

### 2. Migrate Neon once

Use the direct, non-pooled SQLAlchemy URI (`postgresql+psycopg://`,
`sslmode=require`) already in `nof1-database-url`. Never print it or place it in
`.env`, an image, a command argument or chat. The following block captures it
directly into this terminal's process environment and removes it in `finally`.
Migration output is captured too, so unexpected errors cannot echo credentials.

```powershell
Push-Location .\backend
try {
    $env:DATABASE_URL = (gcloud secrets versions access latest --secret=nof1-database-url --project=nof1-demo --verbosity=error 2>$null)
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($env:DATABASE_URL)) {
        throw 'Could not retrieve the database secret. Migration was not started.'
    }
    $nof1MigrationOutput = uv run --offline --no-sync alembic upgrade head 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw 'Migration failed. Captured output is withheld to protect credentials.'
    }
    $nof1RevisionOutput = uv run --offline --no-sync alembic current 2>&1
    if ($LASTEXITCODE -ne 0 -or (($nof1RevisionOutput | Out-String) -notmatch '(?m)^0005 \(head\)\s*$')) {
        throw 'Migration returned successfully, but revision 0005 could not be verified. Stop here.'
    }
    Write-Host 'Migration succeeded. Neon is at revision 0005 (head).'
}
finally {
    Remove-Item Env:\DATABASE_URL -ErrorAction SilentlyContinue
    Remove-Variable nof1MigrationOutput,nof1RevisionOutput -ErrorAction SilentlyContinue
    Pop-Location
}
```

`Push-Location` enters the backend and `Pop-Location` restores the directory.
Secret access captures the URL without displaying it. `upgrade head` applies
outstanding migrations; `current` verifies revision `0005 (head)`. Cleanup runs
on success or failure. Good result is the fixed success line; the human confirmed it.
Backend Cloud Run startup overrides the image CMD so it does not run Alembic again.
Future schema releases should use their own explicit migration step and expected head.

### 3. Prepare and deploy the backend

Create its runtime identity, then grant read access on each existing secret:

```powershell
gcloud iam service-accounts create nof1-runtime --project=nof1-demo --display-name="Nof1 backend runtime"
gcloud secrets add-iam-policy-binding nof1-database-url --project=nof1-demo --member="serviceAccount:nof1-runtime@nof1-demo.iam.gserviceaccount.com" --role="roles/secretmanager.secretAccessor" --condition=None
gcloud secrets add-iam-policy-binding nof1-gemini-api-key --project=nof1-demo --member="serviceAccount:nof1-runtime@nof1-demo.iam.gserviceaccount.com" --role="roles/secretmanager.secretAccessor" --condition=None
gcloud artifacts repositories create nof1 --project=nof1-demo --repository-format=docker --location=us-east4 --description="Nof1 backend and frontend images"
```

Good results are a created account, updated IAM policy on each secret, and a
created repository. IAM commands show permission metadata, not secret contents.
Human confirmed all four. On later releases reuse the existing resources.

Build the backend from the repository root using its existing Dockerfile:

```powershell
$nof1BackendImage = "us-east4-docker.pkg.dev/nof1-demo/nof1/backend:45d6fdb"
gcloud builds submit . --project=nof1-demo --region=us-east4 --config=deploy/cloudbuild-backend.yaml --ignore-file=.gcloudignore --substitutions="_IMAGE=$nof1BackendImage"
```

The assignment stores a public image tag without output. Cloud Build uploads the
allowed source, builds and pushes the image. Good result is `SUCCESS` and the
image tag. `.gcloudignore` excludes dotenv files, development caches and reports;
`.dockerignore` also excludes them from images. Neither secret is supplied to builds.
Human confirmed build `3181d84b-ac88-4d58-9c02-a6ae5ec62db9` succeeded in 60 seconds.

Resolve secret version numbers using metadata only and deploy the image:

```powershell
& {
    $nof1DbVersion = ((gcloud secrets versions describe latest --secret=nof1-database-url --project=nof1-demo --format="value(name)") -split '/')[-1]
    if ($LASTEXITCODE -ne 0 -or $nof1DbVersion -notmatch '^\d+$') {
        throw 'Could not resolve the database secret version. Deployment was not started.'
    }
    $nof1GeminiVersion = ((gcloud secrets versions describe latest --secret=nof1-gemini-api-key --project=nof1-demo --format="value(name)") -split '/')[-1]
    if ($LASTEXITCODE -ne 0 -or $nof1GeminiVersion -notmatch '^\d+$') {
        throw 'Could not resolve the Gemini secret version. Deployment was not started.'
    }
    $nof1DeployArgs = @(
        'run', 'deploy', 'nof1-backend'
        '--project=nof1-demo'
        '--region=us-east4'
        '--image=us-east4-docker.pkg.dev/nof1-demo/nof1/backend:45d6fdb'
        '--service-account=nof1-runtime@nof1-demo.iam.gserviceaccount.com'
        '--allow-unauthenticated'
        '--max-instances=1'
        '--min-instances=0'
        '--max=1'
        '--min=0'
        '--cpu=1'
        '--memory=1Gi'
        '--concurrency=8'
        '--timeout=180s'
        '--port=8000'
        '--command=uvicorn'
        '--args=app.main:app,--host,0.0.0.0,--port,8000,--workers,1,--no-access-log'
        '--env-vars-file=deploy/backend.env.yaml'
        "--set-secrets=DATABASE_URL=nof1-database-url:${nof1DbVersion},GEMINI_API_KEY=nof1-gemini-api-key:${nof1GeminiVersion}"
        '--quiet'
    )
    gcloud @nof1DeployArgs
}
```

Metadata lookups capture numeric version IDs without secret values. The array
prepares arguments; `gcloud` deploys the backend and attaches those secret versions.
Public access lets the frontend proxy call it. Good result is a ready revision
serving 100% of traffic and a Service URL. Human confirmed the initial deployment
and the later frontend-origin update below.

### 4. Build and deploy the frontend

```powershell
$nof1FrontendImage = "us-east4-docker.pkg.dev/nof1-demo/nof1/frontend:45d6fdb"
$nof1BackendOrigin = "https://nof1-backend-196912573980.us-east4.run.app"
gcloud builds submit . --project=nof1-demo --region=us-east4 --config=deploy/cloudbuild-frontend.yaml --ignore-file=.gcloudignore --substitutions="_IMAGE=$nof1FrontendImage,_API_INTERNAL_URL=$nof1BackendOrigin"
```

The assignments store public values without output. The build bakes in the backend
rewrite destination and pushes the image; good result is `SUCCESS`. Human confirmed
build `c7b41d58-9f47-4519-829a-c8f945413c90` succeeded in 3m8s with image digest
`sha256:b08ddb86960a6ef483a3ca4576d34cc70a97ac7f04ba3b014f5c52b729004d5b`.

Create a frontend identity without secret grants and deploy that confirmed image:

```powershell
gcloud iam service-accounts create nof1-frontend-runtime --project=nof1-demo --display-name="Nof1 frontend runtime"
$nof1FrontendDeployArgs = @(
    'run', 'deploy', 'nof1-frontend'
    '--project=nof1-demo'
    '--region=us-east4'
    '--image=us-east4-docker.pkg.dev/nof1-demo/nof1/frontend@sha256:b08ddb86960a6ef483a3ca4576d34cc70a97ac7f04ba3b014f5c52b729004d5b'
    '--service-account=nof1-frontend-runtime@nof1-demo.iam.gserviceaccount.com'
    '--allow-unauthenticated'
    '--port=3000'
    '--cpu=1'
    '--memory=512Mi'
    '--concurrency=8'
    '--timeout=180s'
    '--max-instances=1'
    '--min-instances=0'
    '--max=1'
    '--min=0'
    '--env-vars-file=deploy/frontend.env.yaml'
    '--clear-secrets'
    '--quiet'
)
gcloud @nof1FrontendDeployArgs
```

The first command creates the identity; good result is `Created service account`.
The assignment prepares arguments. The final command deploys the public Node
server on port 3000 with no secrets attached; good result is a ready revision
serving all traffic and a Service URL. Human confirmed both identity and deployment.

Set the backend CORS origin after the frontend URL is confirmed:

```powershell
gcloud run services update nof1-backend --project=nof1-demo --region=us-east4 --update-env-vars="FRONTEND_ORIGIN=https://nof1-frontend-196912573980.us-east4.run.app" --quiet
```

This updates one public setting and creates a revision while retaining secrets,
startup and other settings. Good result is a ready updated backend serving 100%
of traffic. Human confirmed revision `nof1-backend-00002-m5h`. The backend
environment file now includes this origin for subsequent releases.

### 5. Hosted smoke checklist

Health, human-confirmed PASS:

```powershell
$nof1FrontendOrigin = "https://nof1-frontend-196912573980.us-east4.run.app"
Invoke-RestMethod -Uri "$nof1FrontendOrigin/health" -Method Get -UseBasicParsing -TimeoutSec 180
```

The assignment stores a public URL. GET `/health` passes through the frontend
proxy; good result is `status=ok`. It does not access the DB or call an LLM.

Database/cookie/deletion API smoke, human-confirmed PASS:

```powershell
& {
    $nof1SmokeOrigin = "https://nof1-frontend-196912573980.us-east4.run.app"
    $nof1SmokeSession = New-Object Microsoft.PowerShell.Commands.WebRequestSession
    try {
        $nof1Tracking = Invoke-RestMethod -Uri "$nof1SmokeOrigin/api/tracking" -Method Get -WebSession $nof1SmokeSession -UseBasicParsing -TimeoutSec 180 -ErrorAction Stop
        if ($null -eq $nof1Tracking.today) { throw 'The tracking response was not recognized.' }
        if ($null -eq $nof1SmokeSession.Cookies.GetCookies([Uri]$nof1SmokeOrigin)['nof1_uid']) {
            throw 'The API responded, but the session cookie was missing.'
        }
    }
    finally {
        if ($null -ne $nof1SmokeSession.Cookies.GetCookies([Uri]$nof1SmokeOrigin)['nof1_uid']) {
            $nof1Deleted = Invoke-RestMethod -Uri "$nof1SmokeOrigin/api/me" -Method Delete -WebSession $nof1SmokeSession -UseBasicParsing -TimeoutSec 180 -ErrorAction Stop
            if ($nof1Deleted.deleted -ne $true) { throw 'Temporary account deletion was not confirmed.' }
        }
    }
    Write-Host 'Database API and session cookie verified. Temporary account deleted.'
}
```

New-Object creates a fresh in-memory cookie session. GET `/api/tracking` creates
an empty disposable account and reads Neon. The checks require a recognized
response and a session cookie. DELETE `/api/me` in `finally` cleans that account;
success requires `deleted=true`. Good result is the fixed success line. Response
content and cookie values remain in variables; no LLM is called.

Browser demo, human-confirmed PASS:

1. Open the frontend in a fresh private/incognito window. Verify both notices:
   research prototype/not medical advice, and no real health information.
2. Open Network, filter Fetch/XHR, then click Load demo history. Good result is a
   populated timeline, a possible pattern with tier/counts, and simulated controls.
   A fresh account is empty until demo history is loaded.
3. Click Show data points. Good result is the frozen evidence table. Inspect
   Request URLs only: all browser API requests must use the frontend origin.
4. Click Test this on an eligible pattern, then Accept this plan. The proposal
   says it begins tomorrow; acceptance may show the concrete date (Feb 15 in the
   reported demo). That date is on the simulated clock, not the deployment date.
5. Next day reaches day 1, BASELINE. Another click reaches day 2, still BASELINE.
   The following click reaches day 3, the first ON/OFF day and its washout. Advance
   three more days to day 6 to see the opposite phase and first-day washout.
6. Skip to end fills the remaining days synthetically. Good result is an
   Experiment result card with verdict, usable-day counts and the limitation.
7. Browser deletion status: **human-confirmed PASS** after the agent was denied Edge access.
   Click Delete my data, then Confirm delete my data. Good result is an automatic
   reload with demo observations, pattern and verdict gone, and Load demo history
   available again. This is the browser-button check, separate from the API check.

Human-reported synthetic result: magnesium & fatigue, **Helped in this test**;
4 usable ON days and 4 usable OFF days; estimated benefit **1.8 points**,
interval **0.3 to 3.5**. BASELINE appeared on days 1-2, ON on days 3-5, OFF on day 6;
each block's first day showed washout. The card included: "This small, unblinded
test concerns one person, uses day-level resampling, and assumes a short washout."
These observations are synthetic demo evidence, not a live extraction evaluation
or a claim about a person's health. No chat or real health entry is needed.

Agent browser automation was blocked before input with
`Computer Use was not approved to use Microsoft Edge`. Human-reported browser
checks are identified as such; the agent has not independently clicked through them.

### Hosted latency and warm-up

The following command uses the calling machine and a separate disposable cookie
jar, warms both endpoints, takes nine warm samples each and records medians in
this document. It deletes its temporary account in `finally` and makes no LLM calls.
It does not use a browser cookie. Good result is a timing summary and confirmation
that the disposable account was deleted. Run again only when a new measurement is wanted.

```powershell
& .\backend\.venv\Scripts\python.exe .\scripts\measure_deploy.py https://nof1-frontend-196912573980.us-east4.run.app
```

<!-- latency:start -->
Measured 2026-11-04T18:06:20.849515+00:00 from the invoking client, 9 warm samples each: /health median **132.35 ms**; /api/tracking median **189.21 ms**. Disposable account deleted; no LLM calls.
<!-- latency:end -->

The agent ran that measurement from this workspace under the human's instruction
to finish the remaining work. These are warm client-observed medians, not cold-start
measurements or a service-level guarantee. `/health` alone does not wake Neon.
Use a DB-backed request such as the disposable API smoke shortly before a demo.
Repeat after an idle period: Neon Free can suspend after five idle minutes.
Do not leave the temporary account behind or enter real health information.

## Local full stack

```powershell
docker compose build
docker compose up -d --wait
```

The first command builds local images; good result is successful image builds.
The second starts the stack; good result is healthy services. Open
http://localhost:3000. Local startup runs Alembic; the cloud startup override above
does not. Existing .env stays private. Compose ports bind to loopback and the
PostgreSQL volume is preserved. `docker compose down` stops it; `-v` would delete
its data and is not part of this procedure.

## Teardown

Run these commands yourself only when finished with the demo. Teardown has not
been executed. Service deletion takes the app offline; repository deletion removes
its images and requires a rebuild for a future deployment. The Neon database and
the two pre-existing secrets are preserved by this procedure.

First remove the public services, one command at a time. Each deletes the named
service and its revisions; good result is confirmation of service deletion.

```powershell
gcloud run services delete nof1-frontend --project=nof1-demo --region=us-east4
gcloud run services delete nof1-backend --project=nof1-demo --region=us-east4
```

After service deletion, remove the demo image repository. Good result is
confirmation that `nof1` was deleted in `us-east4`.

```powershell
gcloud artifacts repositories delete nof1 --project=nof1-demo --location=us-east4
```

Remove only the two source archives reported by this walkthrough's builds.
Each command deletes that exact object; good result is successful removal.
If already absent, that archive is already cleaned up. Other build archives and
the shared staging bucket are outside these commands' scope.

```powershell
gcloud storage rm "gs://nof1-demo_cloudbuild/source/1793811668.191115-d1b4b240e23c4b31a63a36dbab9551b9.tgz" --project=nof1-demo
gcloud storage rm "gs://nof1-demo_cloudbuild/source/1793812467.526418-30cfe50d426b4a00abd8df0c2cd549c3.tgz" --project=nof1-demo
```

Revoke the backend's two secret grants. Good result for each is an updated IAM
policy without that accessor binding; secret values are not read or printed.

```powershell
gcloud secrets remove-iam-policy-binding nof1-database-url --project=nof1-demo --member="serviceAccount:nof1-runtime@nof1-demo.iam.gserviceaccount.com" --role="roles/secretmanager.secretAccessor" --condition=None
gcloud secrets remove-iam-policy-binding nof1-gemini-api-key --project=nof1-demo --member="serviceAccount:nof1-runtime@nof1-demo.iam.gserviceaccount.com" --role="roles/secretmanager.secretAccessor" --condition=None
```

Delete the two demo runtime identities after their services are gone. Good result
is a deleted-account confirmation for each. These are the two accounts created
above; no default build or Compute Engine service account is deleted.

```powershell
gcloud iam service-accounts delete nof1-frontend-runtime@nof1-demo.iam.gserviceaccount.com --project=nof1-demo
gcloud iam service-accounts delete nof1-runtime@nof1-demo.iam.gserviceaccount.com --project=nof1-demo
```

Review the project's Billing view after cleanup. Retained/soft-deleted storage,
logs, other source archives and preserved secret resources can remain. This is
targeted demo cleanup, not deletion of the Google project or the Neon project.

Official command references: [Cloud Run deletion](https://docs.cloud.google.com/sdk/gcloud/reference/run/services/delete),
[repository deletion](https://docs.cloud.google.com/sdk/gcloud/reference/artifacts/repositories/delete),
[object deletion](https://docs.cloud.google.com/sdk/gcloud/reference/storage/rm),
[secret grant removal](https://docs.cloud.google.com/sdk/gcloud/reference/secrets/remove-iam-policy-binding),
and [runtime account deletion](https://docs.cloud.google.com/sdk/gcloud/reference/iam/service-accounts/delete).

## Remaining phase work

P8 is **offline gate green, live eval pending, not yet approved**. The live cohort L
and final held-out runs remain held. Deployment and demo smoke do not approve P8
or start P9. Model prices remain human-maintained and unverified.
