# Audiobook runtime candidate configuration

This directory contains an inert, configuration-only projection for reviewing
the four-service audiobook runtime candidate. It is not deployment authority,
a promotion handoff, a rollback mechanism, or an alternate production topology.

Every inherited service is profile-gated, fixed at zero replicas, and configured
with immutable images and `pull_policy: never`. The verifier performs static
Compose validation only; rendered JSON can contain secrets and host paths and
must stay in an operator-private directory.

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.whatsapp-web-session.yml \
  -f deploy/audiobook-runtime-candidate/docker-compose.candidate.yml \
  --profile audiobook-candidate-configuration-only \
  config --format json > /private/operator/candidate.json

python3 scripts/verify_audiobook_runtime_candidate.py \
  --mode configuration \
  --compose-json /private/operator/candidate.json \
  --expected-revision "$EA_AUDIOBOOK_CANDIDATE_REVISION" \
  --expected-image "$EA_AUDIOBOOK_CANDIDATE_IMAGE" \
  --receipt /private/operator/candidate-preflight.json
```

A valid static projection returns `configuration_only` and keeps deployment and
promotion authority false. Runtime execution, provider calls, publication,
credentialed deployment, rollback rehearsal, and live continuity proof remain
separate governed steps.
