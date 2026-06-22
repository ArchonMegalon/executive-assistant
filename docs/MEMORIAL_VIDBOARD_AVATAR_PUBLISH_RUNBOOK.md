# Memorial VidBoard Avatar Publish Runbook

## Purpose

Publish a real, verified talking-avatar clip into a public memorial bundle without overstating provider readiness.

The public route must only render the avatar video when:

- provider proof is already `VERIFIED_PROVIDER`
- the copied asset is present in the memorial bundle
- `video_call_avatar.public_ready` is `true`

If any of those conditions are missing, the page must stay on the portrait fallback.

## Inputs

- verified provider proof:
  - `.codex-studio/published/avatar_presenter_provider/vidboard_AVATAR_PRESENTER_PROVIDER_PROOF.generated.json`
- rendered avatar clip:
  - local `.mp4`, `.webm`, or `.mov`
- poster image:
  - local `.png`, `.jpg`, `.jpeg`, or `.webp`
  - optional; if omitted or the target file does not exist yet, the publish script generates one from the first frame

## Publish

```bash
cd "$EA_REPO_ROOT"

python3 scripts/publish_memorial_video_call_avatar.py \
  --slug manfred \
  --provider vidboard \
  --asset /path/to/manfred-vidboard-avatar.mp4 \
  --poster /path/to/manfred-vidboard-avatar-poster.png
```

Optional overrides:

- `--proof /custom/proof.json`
- `--bundle-root /custom/public_memorials`
- `--provider-label "VidBoard Avatar bereit"`
- `--title "Manfred Hoza als Avatar"`
- `--detail "VidBoard-Clip ist fuer den Video Call eingebunden."`
- `--poster /tmp/manfred-poster.png` to let the script generate that file if it does not exist yet

## Result

The script:

- verifies the proof file is really `VERIFIED_PROVIDER`
- verifies the video has a real video stream, valid dimensions, and at least `1.0s` duration
- copies the video and poster into `memorial_data/public_memorials/{slug}/video/`
- updates `memorial.json` with a `video_call_avatar` block
- writes a publish receipt to:
  - `.codex-studio/published/avatar_presenter_provider/{slug}_video_call_avatar_publish.generated.json`

## Verify

```bash
cd "$EA_REPO_ROOT"
python3 -m pytest -q tests/test_publish_memorial_video_call_avatar.py tests/test_memorial_security_contracts.py
```

Then confirm live route behavior:

```bash
curl -fsS http://127.0.0.1:8090/memorials/manfred | rg "memorial-video-call-avatar-video|VidBoard Avatar bereit"
curl -I http://127.0.0.1:8090/memorials/files/manfred/video/manfred-vidboard-avatar.mp4
```

## Fail-closed rule

Do not hand-edit `memorial.json` to point at an arbitrary local mp4.

The route now ignores and blocks avatar assets unless the manifest also says:

- `provider_key` is set
- `provider_proof_verdict == "VERIFIED_PROVIDER"`
- `public_ready == true`
