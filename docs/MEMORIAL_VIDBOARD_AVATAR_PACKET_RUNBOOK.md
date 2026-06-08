# Memorial VidBoard Avatar Packet Runbook

## Purpose

Prepare a real VidBoard render packet from the existing public memorial bundle before any provider export exists.

This lane does not pretend VidBoard is already live. It only packages:

- the public memorial portrait
- a short segment from a public original archive audio clip
- optional local transcript evidence
- the exact fail-closed provider instruction

## Generate the packet

```bash
cd /docker/EA

python3 scripts/prepare_memorial_vidboard_avatar_packet.py \
  --slug manfred \
  --base-url http://127.0.0.1:8090 \
  --start-seconds 0 \
  --duration-seconds 14
```

Default output:

- `/docker/fleet/state/chummer6/avatar_presenter_provider/manfred_vidboard_avatar_packet/packet.generated.json`
- `/docker/fleet/state/chummer6/avatar_presenter_provider/manfred_vidboard_avatar_packet/README.md`

## What the packet contains

- copied portrait image from the public memorial bundle
- extracted WAV segment from the public memorial audio clip
- transcript from `/memorials/{slug}/speech-transcribe` when `--base-url` is provided
- provider instruction:
  - use the supplied portrait
  - use the supplied original archive audio only
  - do not invent or rewrite Manfred copy

## Operator step

Use that packet inside VidBoard to export a real talking-photo clip.

This repo does not currently bypass VidBoard login captcha. The packet is there so the manual provider step is short and bounded instead of improvised.

## Publish after export

Once the real VidBoard clip exists locally:

```bash
cd /docker/EA

python3 scripts/publish_memorial_video_call_avatar.py \
  --slug manfred \
  --provider vidboard \
  --asset /path/to/manfred-vidboard-avatar.mp4
```

That publish step still requires a real `VERIFIED_PROVIDER` proof file.
