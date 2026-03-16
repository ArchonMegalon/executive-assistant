# Next Session Handoff

Date: 2026-03-16
Workspace focus: `/docker/EA`

## What changed in this session

- Fixed the live `ea-coder-best` failure mode where the default public alias entered the fast lane and then got trapped on Magicx-only candidates.
- Kept `ea-coder-best` biased toward Magicx when the fast lane is healthy, but added fallback candidates from the configured provider order so the alias can degrade to 1min instead of returning a 502.
- Confirmed that the live `/v1/models` surface already advertises `ea-coder-best`; the Codex-side “model metadata not found” warning is a client-side generic-metadata fallback for a custom alias, not an EA model-list omission.
- Rebuilt and restarted the live `ea-api`, `ea-worker`, and `ea-scheduler` containers after the routing fix.

## Files changed

- [ea/app/services/responses_upstream.py](/docker/EA/ea/app/services/responses_upstream.py)
  - for `DEFAULT_PUBLIC_MODEL`, fast-lane routing now prepends `magixai` but also appends the configured provider order, allowing fallback to `onemin`
- [tests/test_responses_upstream.py](/docker/EA/tests/test_responses_upstream.py)
  - updated candidate expectations for the default public model
  - added regression coverage proving `ea-coder-best` falls back to `onemin` when Magicx is unavailable

## What was verified

- Targeted upstream regression tests passed:
  - `PYTHONPATH=ea ./.venv/bin/python -m pytest -q tests/test_responses_upstream.py -k 'default_public_model or blank_requested_model or magicx_unavailable'`
  - result: `3 passed`
- Live provider health confirms Magicx is currently degraded
  - detail observed:
    - primary `aimagicx.com` endpoints timing out
    - beta endpoints returning `405`
- Live default-alias smoke now succeeds:
  - request:
    - `POST /v1/responses`
    - `model = "ea-coder-best"`
    - `input = "Reply with exactly OK"`
    - `max_output_tokens = 16`
    - `store = false`
  - result:
    - `status = completed`
    - `upstream_provider = onemin`
    - `upstream_model = gpt-5`
    - `output_text = OK`

## Current operational reading

- `ea-coder-best` now works as a resilient public default alias:
  - preferred path: Magicx fast lane
  - degraded fallback: 1min
- `ea-coder-fast` and explicit easy-lane Codex profiles are still Magicx-first and should be treated as sensitive to Magicx health.
- The Codex-side metadata warning for `ea-coder-best` is still expected unless the client is taught richer alias metadata or you switch to a model name the client already knows natively.

## First checks next session

1. Check live provider health:
   - `curl -sS -H "X-EA-Principal-ID: tibor" http://127.0.0.1:8090/v1/responses/_provider_health`
2. If Magicx is still degraded, prefer:
   - `ea-coder-best`
   - `ea-coder-hard`
   - `ea-onemin-coder`
   over `ea-coder-fast`
3. If the Codex metadata warning becomes worth fixing, treat it as a client-integration task, not an EA `/v1/models` bug.
4. If you change default alias semantics again, rerun both:
   - the targeted upstream regression test
   - the live `ea-coder-best` smoke

## Repo state at handoff

- `/docker/EA`: clean after commit except for local secrets in [`.env`](/docker/EA/.env), which are intentionally not tracked
- Live EA containers have already been rebuilt with this slice
