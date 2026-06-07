# Memorial v6 Current-Landing Operator Notes

## Why v6 exists

The landing contract changed after the earlier room-ready pack:

- `Simplify memorial landing and harden server TTS routing`
- `Add memorial minimal landing regression`

The minimal landing regression checks for `Gespräch beginnen`, `Am Handy/Desktop installieren`, icon references, and a reduced surface. It intentionally removed the older visible interaction-hint requirement.

## Repo-local adjustment

This repo has already moved one step further: the old hero/title/footer elements are not just CSS-hidden anymore, they may be fully removed from the raw HTML source. The rehearsal script and tests here therefore accept either of these states:

- old sections remain in raw HTML but are hidden by the minimal landing CSS contract
- old sections are fully absent from raw HTML

## Run

```bash
cd /docker/EA/ea
python3 -m pytest -q ../tests/test_memorial_current_landing_contracts.py
python3 scripts/memorial_demo_rehearsal.py manfred \
  --base-url https://myexternalbrain.com \
  --questions ../examples/demo_questions.manfred.current.json \
  --save-audio-dir /tmp
```

Then run room-ready as usual.
