# Memorial Room-Ready Procedure

This is the final step before opening the memorial in front of people.

## Command

```bash
cd "$EA_REPO_ROOT"
python3 scripts/memorial_room_ready.py \
  --slug manfred \
  --base-url "${MEMORIAL_PUBLIC_ORIGIN:-https://memorial.example.test}" \
  --questions examples/demo_questions.manfred.json \
  --output-dir /tmp/manfred_room_ready \
  --optional-exit-gates
```

Open:

```text
/tmp/manfred_room_ready/room_ready_report.md
/tmp/manfred_room_ready/showtime_report.md
/tmp/manfred_room_ready/audio_probe.md
```

## Decision

- PASS: present live.
- WARN: present only if you understand the warning and accept it.
- FAIL: do not present live.

## Why this exists

The code path is mostly hardened. The remaining risks are room risks:

- browser permission prompts
- speaker output
- clipped first syllable
- awkward tail cutoff
- old landing page cache
- accidental admin or non-flagship surface exposure

The room-ready runner verifies the live endpoint through the existing showtime stack and then probes the fresh demo TTS audio artifact produced in the same run.

## Missed In The First Pass

The first green deploy was not enough. The live voice/STT loop exposed two phrase-level failures that were easy to miss if only the API and broad tests were checked:

- `Ich bin da. Erzähl mir bitte mehr.` could be transcribed as `Bitte nicht. Erzähl mir bitte mehr.`
- `Sag mir bitte in Ruhe, worum es geht.` could be transcribed as unrelated words.

The guarded German contact path now avoids the brittle `Ich bin da` opening and uses:

```text
Sprich ruhig weiter. Ich antworte dir direkt.
```

The final deployed room-ready run passed `voice_roundtrip_validation` and `audio_probe`. The final voice-loop transcript preserved the spoken intent with F1 `0.9231` for both direct TTS and conversation-answer audio:

```text
expected: Sprich ruhig weiter. Ich antworte dir direkt.
actual:   Sprich ruhig weiter, ich antworte direkt.
```

Unmixr is now a verified runtime lane only because a passing JSON roundtrip receipt exists. A missing video-call avatar manifest may still appear as a warning; that is the optional avatar/video lane, not the live voice conversation gate.
