# Manfred memorial scoped deploy runbook

## Purpose

`make deploy-ea-memorial` is the governed public-memorial lane. It no longer
invokes the inherited EA mega-stack deployer. The lane may start `ea-redis`,
but the only service it force-recreates is `ea-api`.

All runs take the fixed host-global lock
`/run/lock/ea-memorial-ea-api.lock` as well as a deployment-ID lock. Distinct
IDs and distinct release/receipt directories therefore cannot race the same
Compose project or API service.

The forward topology preserves the prior API's ordered Compose layers and adds
exactly one memorial override. Each captured config file must live below the
prior Compose working directory and have a corresponding path in the clean
release root. The lane rebases those relative paths into the release root, then
appends `docker-compose.memorial.yml`. A live base-only API therefore promotes
with base + memorial; a recorded base + production API promotes with base +
production + memorial. The lane rejects an already-present memorial override,
duplicate layer, or unmappable external layer before mutation.

If any API health, local memorial, public memorial, non-memorial compatibility,
evidence-refresh, or final gate check fails after the API change begins, the
lane restores the protected prior API image through the exact Compose project,
working directory, and config-file list recorded on the prior container. It
fails before mutation when that exact baseline cannot be resolved.

## Release-root requirements

Deploy from a clean, durable release worktree on a branch with a configured
upstream. Do not deploy from a detached `HEAD`, the dirty development tree, or
an ephemeral `/tmp` directory. Compose bind mounts keep using the release root
for the lifetime of the container. The lane enforces the attached branch,
upstream, and non-temporary root; these are not advisory checks.

The release root must contain:

- the committed memorial source and `memorial_data` candidate;
- a mode-`0600` production `.env`;
- any ignored production configuration files required under `config/`;
- durable absolute host paths in `.env` for OneDrive, pocket audio, audiobook
  jobs, audiobook imports, and other state that must not resolve inside the
  release worktree;
- a writable private `.runtime` directory for deployment receipts.

Copy ignored configuration without overwriting committed release files:

```bash
install -m 600 /docker/EA/.env "$RELEASE_ROOT/.env"
test ! -f /docker/EA/.env.local || install -m 600 /docker/EA/.env.local "$RELEASE_ROOT/.env.local"
rsync -a --ignore-existing /docker/EA/config/ "$RELEASE_ROOT/config/"
mkdir -p "$RELEASE_ROOT/.runtime"
chmod 700 "$RELEASE_ROOT/.runtime"
```

Run `git status --short` after preparation. Ignored secrets may be present, but
the release-authority source projection must remain clean.

## Preflight

Choose a unique, explicit deployment identifier. Reusing an identifier is
rejected so a prior receipt cannot be overwritten.

Select a locally present candidate image whose tag contains the full release
revision or at least its first 12 hexadecimal characters, or use a repository
SHA-256 digest. `latest`, unbound tags, remote-only images, and unsafe image
references are rejected. The lane never builds or pulls this image; it resolves
the reference to a local immutable image ID before any mutation and later
requires the rendered override to retain the exact reference with
`pull_policy: never`, then requires the recreated API to use that exact ID.

Promotion also requires the private `0600` receipt from a passing isolated
candidate run. A regular, single-link, non-symlink receipt is mandatory; the
lane rejects the older v2 contract. Runtime v3 binds the exact image ID and
source revision to the immutable memorial projection root/digest, isolated
Compose project and clean preflight, held project-name and candidate-port locks, provider-free
narrator/TTS/browser proof, live-EA before/after snapshots, and OpenAPI
counts/digests. The deploy receipt retains only the candidate receipt path and
hash plus bounded safe fields, never the full snapshots.

Build, project, and prove the candidate before preflight. The candidate runner
leaves its isolated project running for soak and does not mutate the live `ea`
project:

```bash
cd "$RELEASE_ROOT"
umask 077
source_revision="$(git rev-parse HEAD)"
candidate_root="$HOME/.local/share/ea-deploy/manfred-memorial/$source_revision"
candidate_project="ea-manfred-candidate-${source_revision:0:12}"
mkdir -p "$candidate_root"
chmod 700 "$candidate_root"

.venv/bin/python scripts/build_manfred_memorial_image.py \
  --source-root "$RELEASE_ROOT" \
  --ref "$source_revision" \
  --tag "ea-runtime:memorial-$source_revision" \
  --receipt "$candidate_root/image-build.json"

.venv/bin/python scripts/prepare_manfred_memorial_candidate.py \
  --source-root "$RELEASE_ROOT" \
  --ref "$source_revision" \
  --image "ea-runtime:memorial-$source_revision" \
  --deploy-root "$candidate_root" \
  --public-base-url "${MEMORIAL_PUBLIC_ORIGIN:?set the real HTTPS origin}" \
  --project-name "$candidate_project" \
  >"$candidate_root/prepare-output.json"

candidate_env="$(jq -er .env_file "$candidate_root/prepare-output.json")"
export EA_MEMORIAL_DATA_HOST_PATH="$(jq -er .release_root "$candidate_root/prepare-output.json")"
export EA_MEMORIAL_CANDIDATE_RECEIPT="$candidate_root/runtime-v3.json"
.venv/bin/python scripts/run_manfred_memorial_candidate.py \
  --env-file "$candidate_env" \
  --receipt "$EA_MEMORIAL_CANDIDATE_RECEIPT"
test "$(stat -c %a "$EA_MEMORIAL_CANDIDATE_RECEIPT")" = 600
```

```bash
cd "$RELEASE_ROOT"
source_revision="$(git rev-parse HEAD)"
export EA_DEPLOYMENT_ID="manfred-$(date -u +%Y%m%dT%H%M%SZ)-$(git rev-parse --short=12 HEAD)"
export EA_MEMORIAL_IMAGE="ea-runtime:memorial-$source_revision"
test -n "${EA_MEMORIAL_CANDIDATE_RECEIPT:?run the isolated candidate first}"
test -n "${EA_MEMORIAL_DATA_HOST_PATH:?bind the proved projection root}"
export EA_MEMORIAL_CONTROL_TOUR_SLUG="360-tour-balkon-wohnung-in-neustift-layout-first-0146e6f9c6"
docker image inspect "$EA_MEMORIAL_IMAGE" --format '{{.Id}}'
make verify-ea-memorial-scoped-deploy
```

The production origin must be HTTPS and its exact host must be approved. The
default allowlist is `myexternalbrain.com,www.myexternalbrain.com`. A different
production host requires an explicit comma-separated
`EA_MEMORIAL_PUBLIC_HOST_ALLOWLIST`; wildcards, paths, credentials, non-443
ports, and HTTP origins are rejected.

Preflight is fail-closed and performs no Docker mutation. It verifies:

- source-clean release authority bound to the requested deployment ID;
- declared `MEMORIAL` project mode and memorial deploy readiness;
- exact baseline-topology mapping into the release root plus memorial Compose
  resolution;
- an existing restorable `ea-api` baseline;
- a safe prior image reference, prior mount-identity digest, and locally
  resolved candidate image ID;
- an isolated render of the captured prior Compose root/layers that still
  reproduces the live API image reference/ID plus normalized environment,
  process (`Cmd`/`Entrypoint`/`User`), and mount-identity digests; `.env` drift
  therefore fails before forward mutation;
- a private passing runtime-v3 candidate receipt bound to the exact image,
  revision, memorial projection root/digest, isolated project/port, unchanged
  live EA snapshot, and provider-free browser proof;
- attached release branch, configured upstream, and durable release root;
- a real configured public origin;
- an exact committed source revision.
- the live local OpenAPI sorted path set/count/digest; when
  `EA_MEMORIAL_CONTROL_TOUR_SLUG` is set, `200` HTML plus the exact JSON body
  digest for that tour.

The preflight receipt is written privately under
`.runtime/deployments/memorial/<deployment-id>.json`. Because deployment IDs are
single-use, use a fresh ID for the actual deployment after a standalone
preflight.

## Deploy

```bash
cd "$RELEASE_ROOT"
source_revision="$(git rev-parse HEAD)"
export EA_DEPLOYMENT_ID="manfred-$(date -u +%Y%m%dT%H%M%SZ)-$(git rev-parse --short=12 HEAD)"
export EA_MEMORIAL_IMAGE="ea-runtime:memorial-$source_revision"
test -n "${EA_MEMORIAL_CANDIDATE_RECEIPT:?run the isolated candidate first}"
test -n "${EA_MEMORIAL_DATA_HOST_PATH:?bind the proved projection root}"
export EA_MEMORIAL_CONTROL_TOUR_SLUG="360-tour-balkon-wohnung-in-neustift-layout-first-0146e6f9c6"
make deploy-ea-memorial
```

The lane performs these mutations only:

1. inspect `ea-redis`; leave it completely untouched when healthy, start the
   existing container directly when stopped, or use scoped
   `up -d --no-build --no-deps ea-redis` only when it is missing, followed by a
   required healthy inspection;
2. protect the current API image under an immutable deployment-specific local
   rollback tag;
3. `up -d --no-build --no-deps --force-recreate ea-api` with the memorial
   override and the explicitly selected candidate image.

It does not build, pull, stop, or recreate the database, workers, scheduler,
relay, Telegram services, WhatsApp services, proactive OODA, or Cloudflare
tunnel.

## Required proof

Success requires all of the following:

- the recreated `ea-api` is running, non-restarting, and Docker-healthy;
- its image ID equals the preflight-resolved candidate ID, its project/service
  labels are `ea`/`ea-api`, and its Compose working directory/config files are
  exactly the release topology;
- read-only `/app/app`, `/app/scripts`, and `/data/memorial_data` mounts resolve
  to the clean release root;
- local `/health` returns `200`;
- local and public `/memorials/manfred` return the Manfred HTML surface;
- local and public `/memorials/manfred.json` return slug `manfred`;
- every local and public memorial HTML/JSON response carries
  `X-EA-Source-Revision` equal to the clean release commit;
- both projections state that the synthetic guide is not Manfred and does not
  speak for him;
- neither projection contains the first-person impersonation marker
  `Ich bin Manfred`;
- local and public memorial JSON bodies have the same SHA-256 digest;
- the full Manfred candidate verifier passes independently against local and
  public origins, including source-grounded narrator chat, TTS `409`, rendered
  browser checks, zero automatic provider work, zero WebSockets, zero failed
  requests/page errors, and zero same-origin HTTP 4xx/5xx responses;
- the post-deploy OpenAPI path set is a superset of the captured live baseline;
- when configured, the priority 3D tour still returns `200` for HTML and JSON,
  with the exact pre-deploy JSON digest unchanged;
- refreshed release authority and memorial deploy readiness remain `pass`.

The receipt stores statuses, response sizes and digests, the verified source
revision, image IDs, sanitized candidate-gate counters, mount-identity digests,
and rollback outcome. It never stores response bodies, arbitrary
request/response headers, raw mount identities, subprocess stdout/stderr,
environment values, or secrets.

## Automatic rollback

Any failure after the API change begins triggers one rollback attempt. The lane:

1. validates the captured prior image reference and retags the captured prior
   image ID to that exact reference;
2. resolves the exact `com.docker.compose.project.config_files` list from the
   prior container's recorded Compose working directory;
3. constructs a minimal rollback environment that excludes forward memorial,
   source-revision, image, deployment-mode, and Compose variables;
4. force-recreates only `ea-api` with `--no-build --no-deps`;
5. requires the restored image ID/reference, project/service identity, exact
  prior topology, prior mount-identity digest, one-way normalized environment
  and process-configuration digests (`Env`, `Cmd`, `Entrypoint`, `User`),
  healthy container, and local `/health`.

The baseline may legitimately be base-only or layered; the lane does not invent
an unrecorded production overlay during rollback. An unsuccessful rollback is
reported as `rollback_failed` and preserves both
the primary failure and rollback failure in the private receipt. Do not delete
the release worktree or rollback image tag until the rollout has been reviewed.

## Manual inspection

```bash
docker inspect -f '{{.State.Health.Status}} {{.Image}}' ea-api
curl -fsS -D - -o /dev/null https://myexternalbrain.com/memorials/manfred
curl -fsS -D - -o /dev/null https://myexternalbrain.com/memorials/manfred.json
python3 scripts/materialize_memorial_operator_status.py
python3 scripts/verify_release_authority.py --pretty
python3 scripts/verify_memorial_deploy_readiness.py --pretty
```

Do not claim memorial public-origin readiness unless both public routes and the
transparent-narrator contract pass at the configured production origin.
