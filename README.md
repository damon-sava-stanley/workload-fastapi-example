# FastAPI on DataRobot Workload API — sample

A minimal FastAPI service deployed as a managed, autoscalable container on
DataRobot's [Workload API](https://docs.datarobot.com), built server-side from
this repo's `Dockerfile` (no local Docker or external registry required).

## What's here

```
app/main.py       FastAPI app: GET /, GET /healthz, POST /echo
Dockerfile        python:3.12-slim, EXPOSE 8080, runs as non-root
requirements.txt  fastapi, uvicorn[standard], pydantic
.dockerignore
.datarobot.yaml   workload manifest (written by `dr workload config`)
```

## The one gotcha this sample exists to demonstrate

DataRobot's edge gateway serves the workload under a path prefix
(`/api/v2/endpoints/workloads/<workload-id>/`) but **strips that prefix before
the request reaches the container**, and does not rewrite the app's responses.
So the app needs to:

- **route** on the stripped path (`/`, `/healthz`, `/echo` — not the prefixed
  version), but
- **emit** URLs (its OpenAPI schema, Swagger UI, any redirects) *with* the
  prefix, or the browser resolves them against the origin root and 404s.

FastAPI/Starlette has this built in via `root_path`. `app/main.py` derives it
at startup from `WORKLOAD_ID`, which DataRobot auto-injects into every
workload container — no extra env var to configure, and it survives rebuilds:

```python
WORKLOAD_ID = os.getenv("WORKLOAD_ID")
ROOT_PATH = f"/api/v2/endpoints/workloads/{WORKLOAD_ID}" if WORKLOAD_ID else ""
app = FastAPI(root_path=ROOT_PATH)
```

Locally (`WORKLOAD_ID` unset) this is a no-op — `root_path` is `""` and the
app behaves like any ordinary FastAPI app on `localhost`.

The app also runs with **no auth of its own**: the DataRobot login is the auth
gate for the endpoint, and an app that sends its own `Authorization: Bearer …`
header would have it hijacked by the edge as a (invalid) DataRobot API key.

## Prerequisites

- `dr` CLI v0.4.3+ (`dr --version`), authenticated (`dr auth check`)
- `DATAROBOT_CLI_FEATURE_WORKLOAD=true` exported
- Org-side `ENABLE_WORKLOAD_API_CONTAINERS` feature flag enabled (needed for
  the server-side Dockerfile build; ask a DataRobot admin if step 3 below
  fails with a feature-flag error)

No local Docker or container registry needed — the image is built on
DataRobot's build infrastructure from the synced source.

## Runtime parameters

| Variable          | Kind   | Purpose                                          |
|-------------------|--------|--------------------------------------------------|
| `APP_GREETING`    | plain  | Returned by `GET /`                              |
| `MAX_ECHO_TIMES`  | plain  | Upper bound on `times` for `POST /echo`          |
| `SERVICE_API_KEY` | secret | Required in `X-Service-Key` header for `GET /secure` |

Locally: `cp .env.template .env`, edit, then `uvicorn app.main:app`. `.env` is
gitignored (and excluded from the sync and the image); only `.env.template` is
committed.

In a workload they live under the container's `environmentVars` in
`.datarobot.yaml`. `dr workload config --sync-env` writes them from `.env`:
plain values as literals, secrets stored as DataRobot credentials and
referenced as `dr-credential:<id>/<key>`, so the secret never lands in git.

```yaml
environmentVars:
  - {name: APP_GREETING, value: Hello from DataRobot}
  - {name: MAX_ECHO_TIMES, value: "10"}
  - {name: SERVICE_API_KEY, value: "dr-credential:<credential-id>/apiToken"}
```

## Deploy

```bash
# 1. Write the manifest (one-time; already committed as .datarobot.yaml)
dr workload config --yes \
  --name fastapi-sample \
  --build-mode dockerfile \
  --port 8080 \
  --health /healthz \
  --cpu 0.5 --memory 512MB --replicas 1 \
  --importance low

# 2. Preview
dr workload up --dry-run

# 3. Deploy: sync source -> server-side build -> create artifact + workload
dr workload up
```

`dr workload up` blocks until the workload is serving (`--detach` to return
immediately). The artifact is created as a **draft** — drafts auto-stop after
8 hours whether or not they're in use; keep iterating on the draft and only
`dr workload up --lock` when you're ready to make it permanent (irreversible).

## Verify

```bash
WID=$(dr workload list --output-format json | python3 -c \
  "import json,sys;print(next(w['id'] for w in json.load(sys.stdin)['workloads'] if w['name']=='fastapi-sample'))")
dr workload get "$WID"                 # expect status: running
dr workload logs "$WID" --limit 50     # expect the startup line with the resolved root_path
ENDPOINT=$(dr workload endpoint "$WID")

curl -sS -H "Authorization: Bearer $DATAROBOT_API_TOKEN" "$ENDPOINT/" 
curl -sS -H "Authorization: Bearer $DATAROBOT_API_TOKEN" "$ENDPOINT/healthz"
curl -sS -X POST "$ENDPOINT/echo" \
  -H "Authorization: Bearer $DATAROBOT_API_TOKEN" -H "Content-Type: application/json" \
  -d '{"message":"hello","times":3}'
```

Then open `$ENDPOINT/docs` in a browser **while logged into DataRobot** —
Swagger UI should load and successfully fetch its schema (check that
`openapi.json`'s `servers[0].url` matches the workload prefix), and "Try it
out" should return 2xx. That's the real proof the `root_path` wiring works; a
bare `curl` to `/` won't catch a broken prefix.

If the workload hangs in `launching` or goes `errored`, run the bundled
diagnostic script from the `datarobot-workload-api` skill:

```bash
python3 <skill-dir>/scripts/diagnose_workload.py "$WID"
```

## Iterate

```bash
# after editing app/ or the Dockerfile:
dr workload up          # new catalog version, new build, rolling redeploy onto the same artifact

# change only replicas / cpu / memory: edit .datarobot.yaml, then
dr workload up           # rolling update, no rebuild
```

At `replicaCount: 1` there's a brief gap during a rolling redeploy; bump to
`2+` for zero-downtime.

## Promote to production

```bash
dr workload up --lock    # locks the artifact permanently — irreversible
```

## Tear down

```bash
dr workload stop "$WID"
dr workload delete "$WID"
dr artifact delete <artifact-id>   # drafts only; locked artifacts can't be deleted
```

Order matters: stop before delete on the workload, delete the workload before
the artifact (it references the artifact by ID).

## Next steps (not covered here)

- **Observability**: wire up OpenTelemetry for traces (`/otel/workload/<id>/traces/`
  is empty until the app is instrumented); logs and service stats work out of
  the box (`dr workload logs`, `/workloads/<id>/stats/`).
- **Credentials**: inject secrets via DataRobot's credential store rather than
  plaintext env vars (`environmentVars[].source: dr-credential`).
- **Autoscaling**: replace `replicaCount` with an `autoscaling` policy in
  `.datarobot.yaml` (e.g. on `cpuAverageUtilization`).
- **CI/CD**: manage the artifact + workload declaratively (Pulumi) instead of
  the interactive CLI.
