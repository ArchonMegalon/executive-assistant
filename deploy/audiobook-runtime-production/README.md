# Governed audiobook production preparation

This directory defines a production-shaped audiobook handoff that remains inert
until a separate governed consumer approves and executes it. The checked-in
overlay keeps worker services paused at zero replicas with an idle command. It
cannot consume a queue, call a provider, publish an artifact, send a message,
build an image, pull an image, or mutate the live `ea-api`.

Preparation binds the committed base Compose file, WhatsApp overlay, and this
production-stage overlay to the expected source revision and immutable image
evidence. Private rendered Compose and evidence inputs must remain regular,
single-link operator-owned files with mode `0600`.

```bash
python3 scripts/verify_audiobook_runtime_production_stage.py \
  --baseline-compose-json /private/operator/baseline.json \
  --staged-compose-json /private/operator/staged.json \
  --expected-revision "$SOURCE_REVISION" \
  --expected-image "$IMMUTABLE_IMAGE" \
  --expected-image-id "$IMAGE_ID" \
  --compose-version "$COMPOSE_VERSION" \
  --provenance /private/operator/provenance.json \
  --sbom /private/operator/sbom.json \
  --receipt /private/operator/production-stage-prepared.json
```

A prepared receipt is not a bearer grant. Activation requires explicit approval
and runtime-enforced queue, provider, credit, transport, recipient, send,
expiry, revocation, rollback, and post-activation controls.
