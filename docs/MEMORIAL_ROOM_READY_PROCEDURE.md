# Memorial Room-Ready Procedure

This is the final step before opening the memorial in front of people.

## Command

```bash
cd /docker/EA/ea
python3 scripts/memorial_room_ready.py \
  --slug manfred \
  --base-url https://myexternalbrain.com \
  --questions ../examples/demo_questions.manfred.json \
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
