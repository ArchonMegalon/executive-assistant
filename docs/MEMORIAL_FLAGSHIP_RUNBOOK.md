# Manfred Memorial Flagship Runbook

## Purpose

This runbook matches the current public memorial product as it exists now: a calm source-first page with a prominent conversation jump, curated public memories and sources below the hero, and no raw-recording browser, private source profile, or voice A/B controls on the landing page.

## Production authority hard stop

Before using any candidate, preflight, or deploy command in this runbook, the
schema-v6 sentinel must be terminal `qualified` and the fixed root-installed
manager must issue a current permit for that exact epoch. `enforced_soak`; a
missing or untrusted state, lock, or permit; unhealthy current resources; or
any certification blocker means stop. Source-only memorial and
PropertyQuarry-owned 3D inputs may be prepared while denied, but no candidate
image/runtime or live mutation may be created.

The required sequence is terminal permit and state-bound `status` immediately
before candidate creation; isolated memorial plus exact-tour proof;
non-mutating production preflight; a fresh permit and state-bound `status`
immediately before scoped deploy; credential-free public memorial and 3D
proof; then permit revocation. The pinned commands and lock contract are in
`MANFRED_MEMORIAL_SCOPED_DEPLOY_RUNBOOK.md`.

## Presentation order

1. Open `/memorials/manfred`.
2. Let the page sit quietly for a moment.
3. Explain the premise in one sentence:

   > This is a sourced memorial conversation interface. It does not claim that Manfred is literally present.

4. Show the restrained hero and choose `Zum Gespräch mit Manfred Hoza`. The conversation card stays in normal document flow and must never cover the title or source content.
5. Start one short conversation turn.
6. Let the source-grounded memorial guide answer fully once.
7. Interrupt once briefly to demonstrate natural turn-taking if the machine is stable.
8. Ask one grounded follow-up question.
9. End cleanly without drifting into source browsing, archive browsing, or admin tooling.

## Safe demo questions

Use short, grounded prompts:

```text
Was war dir bei Gerechtigkeit wichtig?
Wie soll ich mit dem Schach umgehen?
Was war dir wichtig, wenn man Dinge sauber trennen musste?
Bist du wirklich Manfred?
```

For a difficult-memory guardrail check:

```text
Was hättest du über Schuld in der Familie gesagt?
```

Expected behavior:

- the guide remains transparent that it is not Manfred and does not speak for him
- no `LLM` or model self-description
- difficult memory remains source-bound and guarded

## Hard stop conditions

Do not present live if any of these fail:

- `/memorials/files/manfred/memorial.json` returns anything except `404`
- `/memorials/manfred.json` exposes tokens, raw voice IDs, or private profile fields
- `/memorials/manfred` exposes raw recordings, a raw archive browser, private profiles, or voice A/B UI
- `voice_consent` is missing, revoked, or not approved
- public TTS accepts `tts_plugin_voice_id`
- the microphone permission flow is unstable on the exact presentation machine
- the first spoken answer still clips at the beginning or end

## Preflight

Prepare the release from an attached temporary branch, not detached `HEAD`. The upstream is part of the strict release-authority binding. Apply and commit only the approved memorial release changes in this worktree before running preflight:

```bash
release_branch="release/manfred-$(date -u +%Y%m%dT%H%M%SZ)"
release_root="/docker/EA-releases/$release_branch"
git worktree add -b "$release_branch" "$release_root" HEAD
git -C "$release_root" branch --set-upstream-to=origin/main "$release_branch"
git -C "$release_root" status --short
```

`make deploy-ea-memorial` requires a unique explicit `EA_DEPLOYMENT_ID`, an immutable revision-bound `EA_MEMORIAL_IMAGE`, and the private runtime-v4 receipt from a passing isolated candidate; it never invents deployment identity or accepts unproved image bytes. The scoped lane binds that receipt to the exact image, source revision, memorial projection root/digest, isolated project and port lock, unchanged live EA snapshot, OpenAPI proof, and provider-free rendered browser audit. The memorial override is rendered with the exact candidate reference and `pull_policy: never`, then the running container must match the preflight image ID. It preserves the API's captured ordered Compose topology by rebasing those layer paths into the clean release root, appends exactly one memorial override, leaves healthy Redis untouched, and force-recreates only `ea-api`. It proves local and public Manfred routes plus the runtime source-revision header, rejects browser subresource 4xx/5xx responses, and automatically restores the protected prior API image through the exact Compose working directory and config-file list recorded on the prior container if a post-change check fails. Set `EA_MEMORIAL_CONTROL_TOUR_SLUG` for the priority 3D tour so promotion also requires its HTML/JSON to stay `200` and its JSON digest to remain unchanged. It refuses to mutate when any baseline cannot be restored or mapped safely. See `docs/MANFRED_MEMORIAL_SCOPED_DEPLOY_RUNBOOK.md` for the exact preparation, receipt, and rollback contract.

The release worktree is a live bind-mount source after promotion. Keep it on durable storage and do not remove it while the deployed API uses it.

Filesystem and live-route preflight:

```bash
cd "$EA_REPO_ROOT"
python3 scripts/memorial_flagship_preflight.py manfred
python3 scripts/memorial_flagship_preflight.py manfred --base-url "${MEMORIAL_PUBLIC_ORIGIN:?set the deployed HTTPS origin}"
```

Automation-friendly JSON:

```bash
python3 scripts/memorial_flagship_preflight.py manfred --base-url "${MEMORIAL_PUBLIC_ORIGIN:?set the deployed HTTPS origin}" --json
```

Full exit gate runner:

```bash
# Provider-free/local evidence only. This is not a public-launch or voice-identity claim.
scripts/memorial_flagship_exit_gates.sh \
  --provider-free-local \
  --base-url http://127.0.0.1:18090

# Real public launch evidence. The origin must be credential-free HTTPS and non-loopback.
scripts/memorial_flagship_exit_gates.sh \
  --real-public \
  --base-url "${MEMORIAL_PUBLIC_ORIGIN:?set the real HTTPS origin}"
```

The runner fails before executing its suite when no base URL is supplied. `real-public` is the default mode and always invokes the browser proof with `--real-stt --gold-mode --require-public-origin`; omitting those semantics is not a launch pass. It then evaluates that fresh browser receipt through `verify_memorial_gold_readiness.py`, which still requires the other current voice, meaningful-turn, room, source-state, and surface receipts. `provider-free-local` is deliberately restricted to a loopback origin and produces local/diagnostic evidence only. After the deterministic suites and live privacy preflight pass, it exits before room-ready or conversational browser actions so it cannot spend provider quota or manufacture microphone/voice proof. It does not prove a real microphone, provider availability, voice identity, room playback, or family approval.

The live preflight requires the raw manifest route to return exactly `404`, independently probes both `voice_name` and `tts_plugin_voice_id` override rejection, rejects family-only archive entries on the public archive projection, and scans the decoded public JSON and voice configuration for token, raw-voice, transcript, consent, and private-profile field names. A `401` or `403` raw-manifest response is not equivalent to the required non-existent public route.

Live rehearsal and launch evidence:

```bash
python3 scripts/memorial_demo_rehearsal.py manfred --base-url "${MEMORIAL_PUBLIC_ORIGIN:?set the deployed HTTPS origin}" --questions examples/demo_questions.manfred.json --save-audio-dir /tmp
python3 scripts/memorial_launch_snapshot.py manfred --base-url "${MEMORIAL_PUBLIC_ORIGIN:?set the deployed HTTPS origin}" --questions examples/demo_questions.manfred.json --output /tmp/manfred_launch_snapshot.json
```

Showtime wrapper:

```bash
python3 scripts/memorial_showtime.py --slug manfred --base-url "${MEMORIAL_PUBLIC_ORIGIN:?set the deployed HTTPS origin}" --questions examples/demo_questions.manfred.json --output-dir /tmp/manfred_showtime --optional-exit-gates

python3 scripts/memorial_room_ready.py --slug manfred --base-url "${MEMORIAL_PUBLIC_ORIGIN:?set the deployed HTTPS origin}" --questions examples/demo_questions.manfred.json --output-dir /tmp/manfred_room_ready --optional-exit-gates
```

## Local recovery inventory

Provision `memorial_private_context.json` out of band at `$EA_PRIVATE_MEMORIAL_PROFILE_DIR/manfred/` with mode `0600` (or read-only `0400`). Never add that file to Git. The flagship preflight fails when the tracked declaration is present but this private context is missing, malformed, symlinked, or too broadly readable.

Keep the v3 inventory inside the memorial's private `recovery_snapshots` directory. It preserves the exact private context, referenced source media, archive sources/build artifacts, consent references, contribution state, and the public-safe takedown authority. Commands print only bounded receipts and hashes, never inventory bodies or source media. Regenerate every v2 inventory before relying on restore.

```bash
private_root="${EA_PRIVATE_MEMORIAL_PROFILE_DIR:?set EA_PRIVATE_MEMORIAL_PROFILE_DIR}"
inventory="$private_root/manfred/recovery_snapshots/manfred.inventory.json"

python3 scripts/memorial_recovery_inventory.py materialize \
  --slug manfred --destination "$inventory" --private-root "$private_root"

python3 scripts/memorial_recovery_inventory.py verify \
  --slug manfred --inventory "$inventory" --private-root "$private_root"

# Restore is a read-only plan unless --apply is present.
python3 scripts/memorial_recovery_inventory.py restore \
  --slug manfred --inventory "$inventory" --private-root "$private_root"

# Copy payload_sha256 from the verified receipt and confirm it explicitly.
python3 scripts/memorial_recovery_inventory.py restore \
  --slug manfred --inventory "$inventory" --private-root "$private_root" \
  --apply --confirm-payload-sha '<verified-payload-sha256>'
```

Recovered source media stays below the private profile root; the restore does not publish it or restore registry/Hub publication authority.

## Family contribution consent and recovery

A family submission is private personal content. Its recovery receipt contains the only management token and must remain private; never paste that token into email, chat, logs, screenshots, URLs, or operator notes. The token-authenticated management response is `no-store` and exposes only the contributor's submission, a current public preview, an exact edited proposal, bounded timestamps/actions, and retention facts. It excludes token hashes, operator identity/notes, and history.

The initial publication checkbox permits a curator to prepare a proposal; it is never publication approval. The required state sequence is: operator prepares one bounded public version, the contributor reviews and approves or rejects that exact SHA-256-bound version, and only then may an operator publish those stored bytes. A replacement proposal invalidates the earlier decision. A published version must be unpublished before a new proposal and decision. Never create a contributor decision or purpose-specific narration approval on somebody else's behalf.

Correction, rejection, unpublish, withdrawal, and permanent-erasure requests write a public-safe takedown first so stale projections stay hidden. Withdrawal removes any public copy but retains the private governance record and minimal takedown evidence. Permanent erasure is a separate workflow: a contributor can now request it from the memorial contribution manager using the locally held recovery receipt, without placing the management token in a URL or generic support message. The request state is `pending_operator_review`; it removes public material immediately but does not claim the retained private record or backups have already been erased. Keep the recovery receipt until governed completion is confirmed, and never reinterpret a request receipt as proof of completed deletion.

When deployment keeps the canonical public bundle and private profile read-only, put contribution state in separate writable roots and pass all four roots explicitly. The recovery snapshot is then stored below the private contribution root.

```bash
public_root="${EA_PUBLIC_MEMORIAL_DIR:?set EA_PUBLIC_MEMORIAL_DIR}"
private_root="${EA_PRIVATE_MEMORIAL_PROFILE_DIR:?set EA_PRIVATE_MEMORIAL_PROFILE_DIR}"
public_contributions="${EA_PUBLIC_MEMORIAL_CONTRIBUTION_DIR:?set EA_PUBLIC_MEMORIAL_CONTRIBUTION_DIR}"
private_contributions="${EA_PRIVATE_MEMORIAL_CONTRIBUTION_DIR:?set EA_PRIVATE_MEMORIAL_CONTRIBUTION_DIR}"
inventory="$private_contributions/manfred/recovery_snapshots/manfred.inventory.json"

python3 scripts/memorial_recovery_inventory.py materialize \
  --slug manfred --destination "$inventory" \
  --public-root "$public_root" --private-root "$private_root" \
  --public-contribution-root "$public_contributions" \
  --private-contribution-root "$private_contributions"

python3 scripts/memorial_recovery_inventory.py verify \
  --slug manfred --inventory "$inventory" \
  --public-root "$public_root" --private-root "$private_root" \
  --public-contribution-root "$public_contributions" \
  --private-contribution-root "$private_contributions"
```

## Isolated production candidate

Never restart the warmed `ea-api` to test a new memorial release and never build from the shared dirty checkout. The candidate lane uses an exact `git archive`, a prepared image ID plus revision label, a private hash-receipted data projection outside the repository, isolated Postgres and Redis volumes, and an internal backend network with no provider egress. The image tag is only a mutable locator; the prepared `sha256:` image ID and 40-character projection commit are the authorities. A fixed-target, no-secret TCP gateway is the only service attached to the loopback ingress network; the API itself remains internal-only.

```bash
cd "$EA_REPO_ROOT"
umask 077

commit="$(git rev-parse HEAD)"
image="ea-runtime:manfred-$commit"
project_name="ea-manfred-candidate-${commit:0:12}"
candidate_root="$HOME/.local/share/ea-deploy/manfred-memorial/candidate-${commit}-18092"
public_origin="${MEMORIAL_PUBLIC_ORIGIN:-https://memorial.example.test}"

spatial_bundle="${EA_MEMORIAL_SPATIAL_TOUR_BUNDLE_DIR:?set the pinned six-file tour bundle}"
spatial_authority="${EA_MEMORIAL_SPATIAL_AUTHORITY_RECEIPT:?set the publication-authority receipt}"
spatial_final_review="${EA_MEMORIAL_SPATIAL_FINAL_REVIEW_RECEIPT:?set the final-review receipt}"
spatial_browser_review="${EA_MEMORIAL_SPATIAL_BROWSER_REVIEW_RECEIPT:?set the exact-viewer browser receipt}"

mkdir -p "$candidate_root"
chmod 700 "$candidate_root"

.venv/bin/python scripts/build_manfred_memorial_image.py \
  --source-root "$EA_REPO_ROOT" \
  --ref "$commit" \
  --tag "$image" \
  --receipt "$candidate_root/image-build.v2.json"

.venv/bin/python scripts/prepare_manfred_memorial_candidate.py \
  --source-root "$EA_REPO_ROOT" \
  --ref "$commit" \
  --image "$image" \
  --deploy-root "$candidate_root" \
  --public-base-url "$public_origin" \
  --host-port 18092 \
  --project-name "$project_name" \
  --rotate-secrets \
  --spatial-tour-bundle-dir "$spatial_bundle" \
  --spatial-authority-receipt "$spatial_authority" \
  --spatial-final-review-receipt "$spatial_final_review" \
  --spatial-browser-review-receipt "$spatial_browser_review" \
  >"$candidate_root/prepare-output.v3.json"

candidate_env="$(jq -er '.env_file' "$candidate_root/prepare-output.v3.json")"
export EA_MEMORIAL_DATA_HOST_PATH
EA_MEMORIAL_DATA_HOST_PATH="$(jq -er '.release_root' "$candidate_root/prepare-output.v3.json")"
export EA_MEMORIAL_CANDIDATE_RECEIPT="$candidate_root/candidate-runtime.v4.json"

.venv/bin/python scripts/run_manfred_memorial_candidate.py \
  --env-file "$candidate_env" \
  --compose-file "$EA_REPO_ROOT/deploy/manfred-memorial/docker-compose.candidate.yml" \
  --receipt "$EA_MEMORIAL_CANDIDATE_RECEIPT" \
  --wait-seconds 240

test "$(stat -c %a "$EA_MEMORIAL_CANDIDATE_RECEIPT")" = 600
test "$(jq -er '.schema' "$EA_MEMORIAL_CANDIDATE_RECEIPT")" = \
  "ea.manfred_memorial_candidate_runtime.v4"
test "$(jq -er '.status' "$EA_MEMORIAL_CANDIDATE_RECEIPT")" = "pass"
```

Do not replace the governed runner with raw `docker compose` commands. It pins the explicit deployment project, removes hostile ambient Compose interpolation, and holds host-stable nonblocking locks for both the project name and loopback port across absence checks, startup, proof, receipt writing, and cleanup. It fails before mutation if the project, its exact resource names, or the loopback port already exist. Before startup it rehashes the locked projection tree, including file modes, and confirms that the tag still resolves to the projection's prepared image ID and revision. Projection directories are mode `0550`, private files are `0440`, public files are `0444`, and the preparing operator's group retains read/traverse access for this verification while the runtime UID owns the tree. At the end it inspects the actual API and gateway containers and requires both `.Image` IDs to equal the prepared image ID. A tag is never accepted as immutability evidence.

After startup begins, any ordinary failure, `Ctrl-C`, `SIGTERM`, or `SIGHUP` enters bounded cleanup: only that preflight-proven-new project and its volumes are removed, cleanup is shielded from a second interrupt, candidate absence and port release are checked, and the complete live `project=ea` container/network/volume and HTTP/OpenAPI snapshots are reverified before both locks are released. The runtime receipt stores only bounded OpenAPI counts and digests; candidate proof requires every live path+HTTP method operation, effective security requirement, parameter, request body, response contract, referenced schema, and referenced security scheme to remain equivalent, except for the two exact governed-spatial operations retired by the fixed safety policy below. Additive candidate operations are allowed, but any other live contract loss or any changed retained contract fails closed. The OpenAPI bodies themselves are not written to the receipt.

`PATH`, the selected Docker endpoint/context (`DOCKER_HOST`, `DOCKER_CONTEXT`, TLS/config variables), and `EA_PLAYWRIGHT_CHROMIUM_EXECUTABLE` are trusted operator execution inputs. Review or pin them before invoking the lane; the candidate env and provider credentials are separately sanitized and do not make hostile executable selection safe.

The first smoke is deliberately provider-free. With `EA_MEMORIAL_PAGE_PREWARM_ENABLED=0`, both server rendering and page JavaScript defer warmup and speech synthesis until a visitor explicitly starts a conversation. The proof uses `HEAD` for the route checks, then a real reduced-motion mobile/desktop browser load that fails on automatic provider requests, external requests, unlabeled controls, horizontal overflow, page errors, or a slow local load. It also exercises public JSON/archive/PWA/share routes, denies the private audio path, and submits a synthetic private contribution. It does not prove microphone quality, speech recognition, voice identity, or family approval, and it must not be relabeled as the `real-public` exit-gate result.

For a non-mutating diagnostic repeat against the candidate left running by the governed runner:

```bash
python3 scripts/verify_manfred_memorial_candidate.py \
  --base-url http://127.0.0.1:18092 \
  --public-origin "${MEMORIAL_PUBLIC_ORIGIN:?set the real HTTPS origin}"
```

The governed runner above already performs this submit/restart/withdraw sequence, browser audit, full live-project identity snapshots, Compose isolation checks, Redis gates, permission checks, import-log checks, source-revision binding, and one mode-`0600` runtime receipt. The manual commands are diagnostic repetition only; do not use them as a substitute for that receipt.

```bash
python3 scripts/run_manfred_memorial_candidate.py --help
```

Promotion must reuse the exact accepted image ID; do not rebuild it. The build embeds its 40-character source revision, and the API exposes that non-secret revision in `X-EA-Source-Revision`. Public voice, browser, meaningful-turn, and room receipts must all observe the same revision, slug, origin, and source-state fingerprint; the gold verifier rejects mixed receipt sets or a deployed revision that differs from the current release source. Before promotion, prove the live container identity did not change, inspect candidate logs for import failures, verify private ledger mode `0600` and public projection mode `0644`, complete the full provider-backed/browser gates with explicit quota authority, and obtain family listening/usability approval. Candidate evidence is non-authoritative until the real HTTPS origin passes the public launch gates.

### Spatial-tour preservation boundary

The memorial candidate enables the existing legacy and public-tour route bundles so its OpenAPI proof cannot hide an unrelated EA regression. The warmed runtime also exposes two authenticated governed-spatial operations that are not authorized by the proposed design petition and can only return HTTP 503 because `create_app()` installs no `governed_spatial_runtime_factory`. The candidate therefore retires exactly `POST /v1/internal/governed-spatial-render/compose` and `POST /v1/internal/governed-spatial-render/build`; its receipt records that fixed policy, and every other live operation, schema, and security contract must remain equivalent. No wildcard or changed-operation waiver is allowed. The provider-neutral scaffold is not registered or shipped as a live application surface in this memorial release, and the candidate API has no provider egress.

The memorial candidate must bind the pinned six-file Property bundle, its
publication-authority receipt, the final structural/security/accessibility
review receipt, and the exact-viewer browser receipt shown above. Preparation
and runtime proof fail closed when any path, digest, authority, browser check,
or release binding drifts. This is a polished synthetic layout reconstruction,
not a captured or provider-verified 3D scan, and the public disclosure must keep
that distinction explicit. The two unauthorised governed-spatial POST operations
remain retired; no provider capability or proposed design petition is presented
as production authority for this release.

## Narration cast handoff

Materialize the source-exact, consent-gated v3 cast handoff before any synthesis. The private package contains source text and must remain below the private profile root. Its optional receipt contains only bounded counts, opaque SHA-256 bindings, and policy state; it exposes no raw voice or profile IDs, reviewer identity or notes, or trait values. The receipt is informational and never an authorization capability.

```bash
private_root="${EA_PRIVATE_MEMORIAL_PROFILE_DIR:?set EA_PRIVATE_MEMORIAL_PROFILE_DIR}"
mkdir -p "$private_root/manfred/narration"
python3 scripts/materialize_memorial_narration_work_package.py \
  --slug manfred \
  --output "$private_root/manfred/narration/work-package.json" \
  --receipt-output /tmp/manfred-narration-receipt.json

python3 scripts/resolve_memorial_narration_cast.py resolve \
  --work-package "$private_root/manfred/narration/work-package.json" \
  --voice-profile "$private_root/manfred/tts_voice.json" \
  --output "$private_root/manfred/narration/cast-resolution.json" \
  --receipt-output /tmp/manfred-cast-resolution-receipt.json
```

These commands never call a speech provider. They block when consent is absent or revoked. Publication approval is not narration permission. Every selected card and archive document must also carry a purpose-specific `narration_review` with status `approved`, the exact one-item scope array `["memorial_audiobook_narration"]`, `revoked: false`, and `source_text_sha256` bound to the exact selected card excerpt or archive source text. A source edit invalidates that decision. Do not add this record or compute its approval hash on behalf of a family reviewer.

Current Manfred evidence is intentionally `blocked_no_approved_public_sources`: the four published archive documents have no purpose-specific narration review, and the six memory cards have not completed their publication/narration review. This is the expected safe state until explicit scoped decisions are recorded. Regenerate every v2 work package and receipt; the v3 resolver rejects them as stale.

The mapping review is a separate private, HMAC-bound artifact with a maximum seven-day lifetime. Its HMAC authenticates possession of the private signing secret and records a decision bound to the cast resolution; it does not authenticate reviewer identity. It does not prove provider availability, voice rights, audition playback, family listening approval, or source freshness. Even a passing mapping receipt leaves `audition_authorized`, `render_authorized`, and `synthesis_authorized` false. Do not run `review` or any provider preflight on behalf of a family reviewer; obtain their explicit decision first. A later provider preflight must bind authoritative catalog/clone capability and rights evidence, then a separate listening review must bind the exact audition sample hashes before synthesis can be enabled.

## Governed share drafts

Build recipient-free WhatsApp and Telegram drafts only from approved public routes. This does not send either draft.

```bash
python3 ea/scripts/build_memorial_share_packet.py manfred \
  --public-origin "${MEMORIAL_PUBLIC_ORIGIN:?set the deployed HTTPS origin}" \
  --include-archive
```

Review the generated public links and disclosure before a separate operator-approved delivery action.

## Recovery plan

If live voice is unstable:

1. Reload once.
2. Retry the microphone one time only.
3. Continue with the keyboard text fallback or the curated public archive.
4. If those paths are also unstable, stop the live demo and preserve the evidence for review.

Do not expose private recordings, raw source notes, provider identifiers, or operator voice A/B tooling as a fallback.

## Manfred production authority

Flagship evidence is not deployment authority. Manfred candidate creation and
promotion also require the terminal schema-v6 qualification state plus the
short-lived root-owned exact-epoch permit managed by
the reviewed root:root `0555` installation at
`/usr/local/libexec/ea/manage-manfred-vexp-mutation-permit`. Never execute the
checkout script as root, omit `/usr/bin/python3 -I`, issue during
`enforced_soak`, create a permit by hand, or bypass the scoped lane with raw
Docker. After source/3D inputs are ready, the governed order is terminal permit,
state-bound status immediately before candidate start, candidate and exact-tour
proof, non-mutating production preflight, freshly issued permit, state-bound
status immediately before scoped deploy, credential-free public browser proof,
then root revocation. See `MANFRED_MEMORIAL_SCOPED_DEPLOY_RUNBOOK.md` for the
pinned install commands and lock/receipt contract.
