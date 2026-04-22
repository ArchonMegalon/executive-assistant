# Run application preflight model

## Purpose

This file defines the practical checks that happen between “I want to join” and “the GM accepted you.”

It is the connective tissue between:

- account identity
- runner dossier legality
- community rule environments
- join policies
- schedule fit
- safety acknowledgement
- meeting handoff readiness

## Canonical rule

Run application preflight must be explainable.

It may classify an application as `pass`, `warn`, `fail`, or `blocked`.
It may not silently reject a player through hidden heuristics.

Every failed or warned result needs a visible reason and next safe action.

## Check families

- account claim and participation eligibility
- runner dossier or quickstart selection
- legality against `CommunityRuleEnvironment`
- role or seat fit
- schedule overlap and roster conflict
- table-contract acknowledgement
- content and safety acknowledgement
- meeting-platform readiness
- duplicate commitment or overlapping accepted run detection

## Result model

```yaml
run_application_preflight:
  id: rap_001
  open_run_ref: openrun_001
  applicant_ref: user_456
  selected_runner_ref: dossier_789
  community_rule_environment_ref: cre_shadowcasters_seattle_01
  result: warn
  checks:
    account_claimed: pass
    runner_selected: pass
    rule_environment_legality: warn
    role_fit: pass
    schedule_fit: pass
    table_contract_ack: pass
    meeting_platform_readiness: pass
  warnings:
    - Your runner is legal, but this table prefers matrix support and you are applying as a second face.
  next_safe_actions:
    - apply_anyway
    - switch_to_quickstart_decker
```

## GM-facing output

The GM should see a compact, explainable review summary:

- player identity
- selected runner or quickstart
- legality posture
- missing role fit
- schedule fit
- outstanding warnings

The GM should not have to reverse-engineer why Chummer thinks an applicant is viable.

## Player-facing output

The player should see:

- what passed
- what failed
- whether a quickstart path would fix the issue
- whether the table contract still needs acknowledgement
- whether they are overlapping another accepted run

## First proof gate

**Shadowcasters Open Run 001**

Includes:

1. one dossier application that passes cleanly
2. one dossier application that warns on role fit
3. one non-compliant application with readable rule-environment conflicts
4. one quickstart path that resolves the failure
5. one GM review surface that exposes the same reasons the player saw

Success criterion:

> The GM can make a roster decision quickly, and the player can understand why they passed, warned, or failed without asking for a manual rules ruling first.
