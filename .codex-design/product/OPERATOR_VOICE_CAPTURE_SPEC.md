# Operator Voice Capture Spec

Operator voice capture is a bounded EA input lane.

Input:

- dictated prompt
- audit note
- dispatch idea
- bug signal
- Karma Forge idea

Transform:

```text
voice transcript
-> redaction
-> structured summary
-> OperatorCapturePacket
-> target repo / next action
```

Forbidden content:

- secrets
- access tokens
- private support data
- private campaign data
- sourcebook text
- raw personal identifiers

Publication authority remains outside this lane.
