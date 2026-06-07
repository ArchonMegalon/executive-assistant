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
cd /docker/EA/ea
python3 scripts/memorial_flagship_preflight.py manfred
python3 scripts/memorial_flagship_preflight.py manfred --base-url https://myexternalbrain.com
```

Run the live rehearsal and snapshot:

```bash
python3 scripts/memorial_demo_rehearsal.py manfred --base-url https://myexternalbrain.com --questions ../examples/demo_questions.manfred.json --save-audio-dir /tmp
python3 scripts/memorial_launch_snapshot.py manfred --base-url https://myexternalbrain.com --questions ../examples/demo_questions.manfred.json --output /tmp/manfred_launch_snapshot.json
```

Run the full memorial exit gates:

```bash
/docker/EA/scripts/memorial_flagship_exit_gates.sh
```

## Supporting docs

- [MEMORIAL_FLAGSHIP_RUNBOOK.md](/docker/EA/docs/MEMORIAL_FLAGSHIP_RUNBOOK.md)
- [MEMORIAL_GO_NO_GO_CHECKLIST.md](/docker/EA/docs/MEMORIAL_GO_NO_GO_CHECKLIST.md)

## Archive publishing

Archive generation and FlipLink publishing still exist, but they are now supporting infrastructure rather than part of the public landing-page demo.

Build archive documents:

```bash
cd /docker/EA/ea
python3 scripts/build_memorial_archive_documents.py manfred
```

Publish approved public documents:

```bash
python3 scripts/publish_memorial_fliplink_publications.py manfred --public-only
```
