# Manfred Memorial Flagship Runbook

## Purpose

This runbook matches the current public memorial product as it exists now: a minimal, conversation-first surface with install support and no public archive, source profile, or voice A/B controls on the landing page.

## Presentation order

1. Open `/memorials/manfred`.
2. Let the page sit quietly for a moment.
3. Explain the premise in one sentence:

   > This is a sourced memorial conversation interface. It does not claim that Manfred is literally present.

4. Show the minimal surface:
   The page should only emphasize `Sprich mit der Erinnerung`, the short interaction hint, and the install affordance when available.
5. Start one short conversation turn.
6. Let Manfred answer fully once.
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

- first-person tone remains stable
- no `LLM` or model self-description
- difficult memory remains source-bound and guarded

## Hard stop conditions

Do not present live if any of these fail:

- `/memorials/files/manfred/memorial.json` returns anything except `404`
- `/memorials/manfred.json` exposes tokens, raw voice IDs, or private profile fields
- `/memorials/manfred` still shows removed public sections such as archive, recordings, or voice A/B UI
- `voice_consent` is missing, revoked, or not approved
- public TTS accepts `tts_plugin_voice_id`
- the microphone permission flow is unstable on the exact presentation machine
- the first spoken answer still clips at the beginning or end

## Preflight

Filesystem and live-route preflight:

```bash
cd "$EA_REPO_ROOT"
python3 scripts/memorial_flagship_preflight.py manfred
python3 scripts/memorial_flagship_preflight.py manfred --base-url "${MEMORIAL_PUBLIC_ORIGIN:-https://memorial.example.test}"
```

Automation-friendly JSON:

```bash
python3 scripts/memorial_flagship_preflight.py manfred --base-url "${MEMORIAL_PUBLIC_ORIGIN:-https://memorial.example.test}" --json
```

Full exit gate runner:

```bash
scripts/memorial_flagship_exit_gates.sh
```

Live rehearsal and launch evidence:

```bash
python3 scripts/memorial_demo_rehearsal.py manfred --base-url "${MEMORIAL_PUBLIC_ORIGIN:-https://memorial.example.test}" --questions examples/demo_questions.manfred.json --save-audio-dir /tmp
python3 scripts/memorial_launch_snapshot.py manfred --base-url "${MEMORIAL_PUBLIC_ORIGIN:-https://memorial.example.test}" --questions examples/demo_questions.manfred.json --output /tmp/manfred_launch_snapshot.json
```

Showtime wrapper:

```bash
python3 scripts/memorial_showtime.py --slug manfred --base-url "${MEMORIAL_PUBLIC_ORIGIN:-https://memorial.example.test}" --questions examples/demo_questions.manfred.json --output-dir /tmp/manfred_showtime --optional-exit-gates

python3 scripts/memorial_room_ready.py --slug manfred --base-url "${MEMORIAL_PUBLIC_ORIGIN:-https://memorial.example.test}" --questions examples/demo_questions.manfred.json --output-dir /tmp/manfred_room_ready --optional-exit-gates
```

## Local recovery inventory

Provision `memorial_private_context.json` out of band at `$EA_PRIVATE_MEMORIAL_PROFILE_DIR/manfred/` with mode `0600` (or read-only `0400`). Never add that file to Git. The flagship preflight fails when the tracked declaration is present but this private context is missing, malformed, symlinked, or too broadly readable.

Keep the v2 inventory inside the memorial's private `recovery_snapshots` directory. It preserves the exact private context, referenced source media, archive sources/build artifacts, consent references, and contribution state. Commands print only bounded receipts and hashes, never inventory bodies or source media.

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

Never restart the warmed `ea-api` to test a new memorial release and never build from the shared dirty checkout. The candidate lane uses an exact `git archive`, an immutable image tag and revision label, a private hash-receipted data projection outside the repository, isolated Postgres and Redis volumes, and an internal backend network with no provider egress. A fixed-target, no-secret TCP gateway is the only service attached to the loopback ingress network; the API itself remains internal-only.

```bash
cd "$EA_REPO_ROOT"
commit="$(git rev-parse HEAD)"
tag="ea-runtime:manfred-${commit:0:12}"
deploy_root="${EA_MANFRED_DEPLOY_ROOT:-$HOME/.local/share/ea-deploy/manfred-memorial}"

python3 scripts/build_manfred_memorial_image.py \
  --ref "$commit" --tag "$tag" \
  --receipt "$deploy_root/image-build.json"

python3 scripts/prepare_manfred_memorial_candidate.py \
  --ref "$commit" --image "$tag" \
  --deploy-root "$deploy_root" \
  --public-base-url "${MEMORIAL_PUBLIC_ORIGIN:?set the real HTTPS origin}" \
  --host-port 18090

candidate_env="$deploy_root/candidate.env"
candidate_compose="deploy/manfred-memorial/docker-compose.candidate.yml"
docker compose --env-file "$candidate_env" -f "$candidate_compose" config -q
docker compose --env-file "$candidate_env" -f "$candidate_compose" up -d --wait
docker compose --env-file "$candidate_env" -f "$candidate_compose" exec -T redis redis-cli ping
```

The first smoke is deliberately provider-free. With `EA_MEMORIAL_PAGE_PREWARM_ENABLED=0`, both server rendering and page JavaScript defer warmup and speech synthesis until a visitor explicitly starts a conversation. The proof uses `HEAD` for the route checks, then a real reduced-motion mobile/desktop browser load that fails on automatic provider requests, external requests, unlabeled controls, horizontal overflow, page errors, or a slow local load. It also exercises public JSON/archive/PWA/share routes, denies the private audio path, and submits a synthetic private contribution. It does not prove microphone quality, speech recognition, voice identity, or family approval.

```bash
contribution_receipt="$deploy_root/candidate-contribution.json"
python3 scripts/verify_manfred_memorial_candidate.py \
  --base-url http://127.0.0.1:18090 \
  --public-origin "${MEMORIAL_PUBLIC_ORIGIN:?set the real HTTPS origin}" \
  --submit-contribution-receipt "$contribution_receipt"

docker compose --env-file "$candidate_env" -f "$candidate_compose" restart api

python3 scripts/verify_manfred_memorial_candidate.py \
  --base-url http://127.0.0.1:18090 \
  --public-origin "${MEMORIAL_PUBLIC_ORIGIN:?set the real HTTPS origin}" \
  --withdraw-contribution-receipt "$contribution_receipt"
```

For the same sequence with live-API identity snapshots, compose isolation checks, Redis gates, permission checks, import-log checks, and one mode-`0600` runtime receipt:

```bash
python3 scripts/run_manfred_memorial_candidate.py \
  --env-file "$candidate_env" \
  --receipt "$deploy_root/receipts/candidate-runtime.json"
```

Promotion must reuse the exact accepted image ID; do not rebuild it. Before promotion, prove the live container identity did not change, inspect candidate logs for import failures, verify private ledger mode `0600` and public projection mode `0644`, complete the full provider-backed/browser gates with explicit quota authority, and obtain family listening/usability approval. Candidate evidence is non-authoritative until the real HTTPS origin passes the public launch gates.

## Narration cast handoff

Materialize the source-exact, consent-gated cast handoff before any synthesis. The private package contains source text and must remain below the private profile root; the optional receipt is provider-safe and contains hashes and trait kinds only.

```bash
private_root="${EA_PRIVATE_MEMORIAL_PROFILE_DIR:?set EA_PRIVATE_MEMORIAL_PROFILE_DIR}"
mkdir -p "$private_root/manfred/narration"
python3 scripts/materialize_memorial_narration_work_package.py \
  --slug manfred \
  --output "$private_root/manfred/narration/work-package.json" \
  --receipt-output /tmp/manfred-narration-receipt.json
```

This command never calls a speech provider. It blocks when consent is absent or revoked. The current approved Manfred sources contain no attributed dialogue, so the real package remains narrator-only until a curator approves quoted dialogue and explicit speaker profiles.

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
