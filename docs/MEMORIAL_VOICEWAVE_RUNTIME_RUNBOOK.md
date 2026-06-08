# Memorial VoiceWave Runtime Runbook

Use this lane when you want a real bounded `VoiceWave.ai` studio flow for Manfred instead of only a workspace screenshot.

What this script can do:
- inspect the visible `My Clones` inventory
- create a new custom Manfred clone from a reference clip
- render a short Manfred line and export a real WAV

Script:

```bash
cd /docker/EA
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
/docker/fleet/state/chummer6/voicewave_provider/voicewave_catalog.generated.json
```

This proves whether the requested clone is already visible in `My Clones`.

## 2. Create a Manfred clone

Default reference audio currently uses the strongest curated late-interview clip already living in the memorial profile:

```text
/docker/EA/memorial_data/private_memorial_profiles/manfred/voice_profile/optimization/candidates/oSQ9FhFc4YI-01440s-28.wav
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
/docker/fleet/state/chummer6/voicewave_provider/voicewave_clone_create.generated.json
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
/docker/fleet/state/chummer6/voicewave_provider/voicewave_render.generated.json
/docker/fleet/state/chummer6/voicewave_provider/voicewave_render.latest.wav
/docker/fleet/state/chummer6/voicewave_provider/voicewave_render.latest.png
```

## Practical interpretation

- `catalog` is the fastest truth check for whether the clone exists.
- `clone` is the operator step that creates the missing custom voice asset.
- `render` is the bounded runtime proof that the clone is actually usable and exportable.

Important:
- this is a studio-automation lane, not a low-latency live memorial TTS adapter
- it is useful right now for proof, comparison, and sample generation
- only move it into live memorial runtime after latency and provider reliability are separately proven
