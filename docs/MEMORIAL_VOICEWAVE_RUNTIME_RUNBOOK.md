# Memorial VoiceWave Runtime Runbook

Use this lane when you want a real bounded `VoiceWave.ai` studio flow for Manfred instead of only a workspace screenshot.

Current status:
- `VoiceWave` is now wired into the live memorial TTS route for `manfred`
- the active memorial voice can be `voicewave_clone`
- live runtime needs the compose override `docker-compose.voicewave-runtime.yml` because the studio worker still shells out to a Dockerized Playwright lane

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

The live memorial route now depends on a small compose override so `ea-api` can start the bounded Playwright worker:

```bash
cd "$EA_REPO_ROOT"
docker compose \
  -f docker-compose.yml \
  -f docker-compose.voicewave-runtime.yml \
  up -d --build --force-recreate ea-api
```

This override contributes only:
- `/var/run/docker.sock` into `ea-api`
- `EA_UI_SERVICE_SHARED_TEMP_ROOT=${EA_UI_SERVICE_SHARED_TEMP_ROOT:-/data/artifacts/browseract_ui_worker_shared}`
- `VOICEWAVE_RUNTIME_TMP_ROOT=${VOICEWAVE_RUNTIME_TMP_ROOT:-/data/artifacts/voicewave_runtime_tmp}`

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
- it now works in the live memorial route, but latency must still be judged operationally
- the compose override is part of the runtime contract until a provider-native API lane replaces the Dockerized studio worker
