# Executive Assistant review checklist

Use this review context in the mirrored `executive-assistant` repo.

## EA-specific focus

- Flag any change that turns assistant-local prompts, helpers, or memory into canonical Chummer product truth as P1.
- Flag any change that makes EA the first-line support inbox or canonical case database as P1.
- Flag any change that stores user, account, group, reward, entitlement, install, or release truth in EA as P1.
- Flag any guide/help generation path that bypasses mirrored design canon as P1.

## Boundary check

Reject if the change:

- invents queue, milestone, blocker, or contract truth locally
- bypasses Hub, Fleet, or design ownership splits
- treats provider/runtime telemetry as product authority
- takes merge, release-channel, install, or update-feed authority that belongs elsewhere

## Review summary

Every substantive review should answer:

- canon fit: pass/fail
- boundary fit: pass/fail
- telemetry/runtime fit: pass/fail
- mirror fit: pass/fail
- required design follow-up: yes/no
