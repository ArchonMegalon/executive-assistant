# Manfred Memorial Flagship Launch

This launch note tracks the current memorial flagship state after the public page was reduced to a conversation-only surface.

## Current public flagship

The public memorial now intentionally centers on:

- `Sprich mit der Erinnerung`
- the minimal interaction hint
- install support
- the live conversation loop

It intentionally does **not** surface archive browsing, public recordings, source profile panels, or public voice A/B tooling on the landing page.

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

Archive generation and FlipLink publishing still exist, but they are now supporting infrastructure rather than part of the public landing-page demo.

Build archive documents:

```bash
cd "$EA_REPO_ROOT"
python3 scripts/build_memorial_archive_documents.py manfred
```

Publish approved public documents:

```bash
python3 scripts/publish_memorial_fliplink_publications.py manfred --public-only
```
