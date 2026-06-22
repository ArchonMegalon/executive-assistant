# Memorial Go/No-Go Checklist

## Public surface

- [ ] `/memorials/manfred` loads.
- [ ] The page shows `Sprich mit der Erinnerung`.
- [ ] The page shows `Tippen, sprechen, kurz warten, einfach weiterreden.`
- [ ] The public page does not show `Originalaufnahmen`.
- [ ] The public page does not show `Belegte Erinnerungen`.
- [ ] The public page does not show `Archiv lesen`.
- [ ] The public page does not show voice A/B controls.

## Safety

- [ ] `/memorials/files/manfred/memorial.json` returns `404`.
- [ ] `/memorials/manfred.json` exposes no write/admin tokens.
- [ ] `/memorials/manfred.json` exposes no raw voice identifiers.
- [ ] `/memorials/manfred/voice-config` exposes no raw provider voice identifiers.
- [ ] `/memorials/manfred/speech-synthesize` rejects `tts_plugin_voice_id`.
- [ ] `voice_consent.status == approved`.
- [ ] `voice_consent.scope` contains `synthesize`, `conversation_turn`, and `realtime`.

## Runtime behavior

- [ ] First spoken answer starts cleanly enough to hear the beginning.
- [ ] Spoken answers do not cut off too early at the end.
- [ ] Status text remains conversational and non-technical.
- [ ] No `LLM` / model self-description leaks into answers.
- [ ] Retry button appears on microphone failure and recovers cleanly.

## Archive and data boundaries

- [ ] Public archive JSON contains only public publications.
- [ ] Family/reviewer publications are absent from the public archive payload.
- [ ] No private profile files are present in the public memorial bundle.

## Exit gates

- [ ] `pytest -q tests/test_memorial_archive_registry_public.py tests/test_memorial_flagship_preflight.py tests/test_memorial_security_contracts.py tests/test_providers_api_contracts.py -k 'memorial'`
- [ ] `.venv/bin/pytest -q tests/e2e/test_memorial_browser.py tests/e2e/test_memorial_flagship_exit_gates.py tests/e2e/test_memorial_flagship_operator_tools.py tests/e2e/test_memorial_showtime_cli.py`
- [ ] `pytest -q tests/test_memorial_audio_probe_contracts.py tests/test_memorial_room_ready_contracts.py`
- [ ] `scripts/memorial_flagship_exit_gates.sh`
- [ ] `python3 ea/scripts/memorial_demo_rehearsal.py manfred --base-url "${MEMORIAL_PUBLIC_ORIGIN:-https://memorial.example.test}" --questions examples/demo_questions.manfred.json --save-audio-dir /tmp`
- [ ] `python3 ea/scripts/memorial_launch_snapshot.py manfred --base-url "${MEMORIAL_PUBLIC_ORIGIN:-https://memorial.example.test}" --questions examples/demo_questions.manfred.json --output /tmp/manfred_launch_snapshot.json`
- [ ] `python3 ea/scripts/memorial_showtime.py --slug manfred --base-url "${MEMORIAL_PUBLIC_ORIGIN:-https://memorial.example.test}" --questions examples/demo_questions.manfred.json --output-dir /tmp/manfred_showtime --optional-exit-gates`
- [ ] `python3 ea/scripts/memorial_room_ready.py --slug manfred --base-url "${MEMORIAL_PUBLIC_ORIGIN:-https://memorial.example.test}" --questions examples/demo_questions.manfred.json --output-dir /tmp/manfred_room_ready --optional-exit-gates`
