# Memorial Flagship v5 Room-Ready Pack

The repo now already has the v4 showtime wrapper on main. This pack adds final audio QA and room-readiness orchestration.

## Files

- `scripts/memorial_audio_probe.py`
- `scripts/memorial_room_ready.py`
- `ea/tests/test_memorial_audio_probe_contracts.py`
- `ea/tests/test_memorial_room_ready_contracts.py`
- `docs/MEMORIAL_ROOM_READY_PROCEDURE.md`
- `docs/MEMORIAL_EXECUTIVE_BRIEF.md`
- `docs/MEMORIAL_LIVE_FAILURE_CARD.md`
- `examples/room_ready.env.example`

## Run

```bash
cd /docker/EA/ea
python3 scripts/memorial_room_ready.py \
  --slug manfred \
  --base-url https://myexternalbrain.com \
  --questions ../examples/demo_questions.manfred.json \
  --output-dir /tmp/manfred_room_ready \
  --optional-exit-gates
```

This wraps the existing showtime command and then probes the generated demo TTS audio for duration, lead-in silence, tail silence, RMS, and clipping.
