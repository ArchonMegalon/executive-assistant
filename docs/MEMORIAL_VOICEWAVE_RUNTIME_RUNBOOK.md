# Memorial VoiceWave Runtime Runbook

Use this lane when you want a real bounded `VoiceWave.ai` studio flow for Manfred instead of only a workspace screenshot.

Current status:
- `VoiceWave` is wired into the memorial TTS route for `manfred` in source
- the active memorial voice can be `voicewave_clone`
- the explicit compose override `docker-compose.voicewave-runtime.yml` enables the public memorial routers and requires the deployed source revision
- `scripts/voicewave_memorial_voice.py` is a host-side operator CLI; its Dockerized Playwright worker runs from the host, not from inside `ea-api`

What this script can do:
- inspect the visible `My Clones` inventory
- create a new custom Manfred clone from a reference clip
- render a short Manfred line and export a real WAV

Script:

```bash
cd "$EA_REPO_ROOT"
python3 scripts/voicewave_memorial_voice.py --help
```

Credential slots:
- `VOICEWAVE_LOGIN_EMAIL`
- `VOICEWAVE_LOGIN_PASSWORD`

## 1. Inspect clone inventory

```bash
python3 scripts/voicewave_memorial_voice.py catalog \
  --voice-label "Manfred Hoza Memorial"
```

Output:

```text
.codex-studio/published/voicewave_provider/voicewave_catalog.generated.json

Set `VOICEWAVE_MEMORIAL_OUTPUT_ROOT` when production should write somewhere else.
Inside the running container, writable fallback paths are used automatically when the repo-local output is not available:
- `/data/artifacts/voicewave_provider`
- `/tmp/voicewave_provider`
```

This proves whether the requested clone is already visible in `My Clones`.

## 2. Create a Manfred clone

Default reference audio currently uses the strongest curated late-interview clip already living in the memorial profile:

```text
memorial_data/private_memorial_profiles/manfred/voice_profile/optimization/candidates/oSQ9FhFc4YI-01440s-28.wav
```

Run:

```bash
python3 scripts/voicewave_memorial_voice.py clone \
  --slug manfred \
  --voice-label "Manfred Hoza Memorial"
```

Optional explicit reference:

```bash
python3 scripts/voicewave_memorial_voice.py clone \
  --slug manfred \
  --voice-label "Manfred Hoza Memorial" \
  --reference-audio /path/to/clean-manfred-sample.wav
```

Output:

```text
.codex-studio/published/voicewave_provider/voicewave_clone_create.generated.json
```

If the clone already exists, the script now reuses it instead of silently creating duplicates.

## 3. Render a real Manfred sample

```bash
python3 scripts/voicewave_memorial_voice.py render \
  --voice-label "Manfred Hoza Memorial" \
  --text "Ich bin da. Sprich klar und direkt mit mir."
```

Outputs:

```text
.codex-studio/published/voicewave_provider/voicewave_render.generated.json
.codex-studio/published/voicewave_provider/voicewave_render.latest.wav
.codex-studio/published/voicewave_provider/voicewave_render.latest.png
```

## 4. Reproducible live runtime deploy

The live memorial route depends on a small compose override that enables the
public memorial routers and stamps the exact committed source revision. Deploy
from a clean tree so `EA_SOURCE_REVISION` cannot claim a commit while the image
contains uncommitted source:

```bash
cd "$EA_REPO_ROOT"

test -z "$(git status --porcelain)" || {
  echo "Refusing memorial deploy from a dirty worktree." >&2
  exit 1
}
EA_SOURCE_REVISION="$(git rev-parse --verify HEAD^{commit})" || exit 1
test -n "$EA_SOURCE_REVISION" || exit 1
export EA_SOURCE_REVISION

docker compose \
  -f docker-compose.yml \
  -f docker-compose.voicewave-runtime.yml \
  config --quiet

docker compose \
  -f docker-compose.yml \
  -f docker-compose.voicewave-runtime.yml \
  up -d --build --force-recreate ea-api
```

This override contributes:
- `EA_ENABLE_PUBLIC_MEMORIALS=${EA_ENABLE_PUBLIC_MEMORIALS:-1}`
- required pass-through `EA_SOURCE_REVISION` with no fallback
- `EA_UI_SERVICE_SHARED_TEMP_ROOT=${EA_UI_SERVICE_SHARED_TEMP_ROOT:-/data/artifacts/browseract_ui_worker_shared}`
- `VOICEWAVE_RUNTIME_TMP_ROOT=${VOICEWAVE_RUNTIME_TMP_ROOT:-/data/artifacts/voicewave_runtime_tmp}`

It deliberately does not mount `/var/run/docker.sock`. The VoiceWave studio
automation shells out to Docker only from the host-side operator CLI. Mounting
the host Docker socket into the API would give the service host-level control
without an in-container caller that needs it.

Live checks:

```bash
curl -sS http://127.0.0.1:8090/memorials/manfred/voice-config

curl -sS \
  -H 'content-type: application/json' \
  -d '{"text":"Ich bin da. Sprich direkt mit mir."}' \
  http://127.0.0.1:8090/memorials/manfred/speech-synthesize \
  -o /tmp/manfred-voicewave-check.wav
```

## Practical interpretation

- `catalog` is the fastest truth check for whether the clone exists.
- `clone` is the operator step that creates the missing custom voice asset.
- `render` is the bounded runtime proof that the clone is actually usable and exportable.

Important:
- this is still a studio-backed lane, not a native low-latency TTS API
- source integration still needs live route and provider proof after each deploy; latency must be judged operationally
- the compose override is part of the runtime contract for public-router enablement and source-revision provenance
- run `catalog`, `clone`, and `render` on the Docker host; do not run the operator CLI inside `ea-api`
