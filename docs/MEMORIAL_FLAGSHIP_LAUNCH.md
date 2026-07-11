# Manfred Memorial Flagship Launch

This launch note tracks the source-first memorial flagship and its accessible conversation surface.

## Current public flagship

The public memorial intentionally combines:

- curated, explicitly public memories and sources
- a visible synthetic-voice and audio-processing disclosure
- microphone conversation with interruption and recovery
- a keyboard-only text conversation fallback
- a private-by-default family contribution and withdrawal journey
- install support and a discoverable public document archive

Private recordings, family notes, raw transcripts, provider identifiers, consent records, and operator voice-review tooling are never projected onto the public page.

## Preflight and exit gates

Run the preflight:

```bash
cd "$EA_REPO_ROOT"
python3 scripts/memorial_flagship_preflight.py manfred
python3 scripts/memorial_flagship_preflight.py manfred --base-url "${MEMORIAL_PUBLIC_ORIGIN:-https://memorial.example.test}"
```

Run the live rehearsal and snapshot:

```bash
python3 scripts/memorial_demo_rehearsal.py manfred --base-url "${MEMORIAL_PUBLIC_ORIGIN:-https://memorial.example.test}" --questions examples/demo_questions.manfred.json --save-audio-dir /tmp
python3 scripts/memorial_launch_snapshot.py manfred --base-url "${MEMORIAL_PUBLIC_ORIGIN:-https://memorial.example.test}" --questions examples/demo_questions.manfred.json --output /tmp/manfred_launch_snapshot.json
```

Run the one-command showtime wrapper:

```bash
python3 scripts/memorial_showtime.py --slug manfred --base-url "${MEMORIAL_PUBLIC_ORIGIN:-https://memorial.example.test}" --questions examples/demo_questions.manfred.json --output-dir /tmp/manfred_showtime --optional-exit-gates
```

Final room-ready pass right before the presentation:

```bash
python3 scripts/memorial_room_ready.py --slug manfred --base-url "${MEMORIAL_PUBLIC_ORIGIN:-https://memorial.example.test}" --questions examples/demo_questions.manfred.json --output-dir /tmp/manfred_room_ready --optional-exit-gates
```

Run the full memorial exit gates:

```bash
scripts/memorial_flagship_exit_gates.sh
```

## Supporting docs

- [MEMORIAL_FLAGSHIP_RUNBOOK.md](MEMORIAL_FLAGSHIP_RUNBOOK.md)
- [MEMORIAL_GO_NO_GO_CHECKLIST.md](MEMORIAL_GO_NO_GO_CHECKLIST.md)

## Archive publishing

Archive generation creates contained public HTML/PDF artifacts and a public-only registry. Built, approved public HTML can be served through the memorial's internal archive route without a paid provider. FlipLink is optional and must only replace that route after it returns a real, non-placeholder HTTPS publication URL.

Build archive documents:

```bash
cd "$EA_REPO_ROOT"
python3 ea/scripts/build_memorial_archive_documents.py manfred
```

Publish approved public documents:

```bash
python3 ea/scripts/publish_memorial_fliplink_publications.py manfred --public-only
```
