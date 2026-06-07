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
cd /docker/EA/ea
python3 scripts/memorial_flagship_preflight.py manfred
python3 scripts/memorial_flagship_preflight.py manfred --base-url https://myexternalbrain.com
```

Automation-friendly JSON:

```bash
python3 scripts/memorial_flagship_preflight.py manfred --base-url https://myexternalbrain.com --json
```

Full exit gate runner:

```bash
/docker/EA/scripts/memorial_flagship_exit_gates.sh
```

Live rehearsal and launch evidence:

```bash
python3 scripts/memorial_demo_rehearsal.py manfred --base-url https://myexternalbrain.com --questions ../examples/demo_questions.manfred.json --save-audio-dir /tmp
python3 scripts/memorial_launch_snapshot.py manfred --base-url https://myexternalbrain.com --questions ../examples/demo_questions.manfred.json --output /tmp/manfred_launch_snapshot.json
```

Showtime wrapper:

```bash
python3 scripts/memorial_showtime.py --slug manfred --base-url https://myexternalbrain.com --questions ../examples/demo_questions.manfred.json --output-dir /tmp/manfred_showtime --optional-exit-gates
```

## Recovery plan

If live voice is unstable:

1. Reload once.
2. Retry the microphone one time only.
3. If the retry still feels unstable, stop the live demo.
4. Explain that the memorial stays consent-gated and can be shown again once the audio path is stable.

Do not fall back to public archive cards, public recordings, or voice A/B preview on the public page. They are intentionally not part of the current flagship surface.
