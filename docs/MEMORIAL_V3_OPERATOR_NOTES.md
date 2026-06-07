# Memorial V3 Operator Notes

## What v3 adds

The current repo already has the flagship preflight and exit gates. V3 adds the operator/rehearsal layer on top:

- `ea/scripts/memorial_demo_rehearsal.py`
- `ea/scripts/memorial_launch_snapshot.py`
- `tests/test_memorial_demo_rehearsal_contracts.py`
- `tests/e2e/test_memorial_flagship_operator_tools.py`
- `examples/demo_questions.manfred.json`

## Why this exists

The public memorial is now conversation-first. That means the launch risk is less about public archive UI and more about:

- the landing page still being minimal
- the chat staying in-character
- difficult-memory questions staying guarded
- public TTS behaving correctly
- having one timestamped proof bundle before presenting

## Operator run order

```bash
cd /docker/EA/ea
python3 scripts/memorial_flagship_preflight.py manfred
python3 scripts/memorial_flagship_preflight.py manfred --base-url https://myexternalbrain.com
python3 scripts/memorial_demo_rehearsal.py manfred --base-url https://myexternalbrain.com --questions ../examples/demo_questions.manfred.json --save-audio-dir /tmp
python3 scripts/memorial_launch_snapshot.py manfred --base-url https://myexternalbrain.com --questions ../examples/demo_questions.manfred.json --output /tmp/manfred_launch_snapshot.json
```

## Notes

- Do not lead with FlipLink or archive browsing.
- Do not expose source-profile, candidate, or voice A/B surfaces on the public page.
- Stop the live demo after the difficult-memory guardrail check. Do not keep improvising once the product point is proven.
