# Community rule environments and approval

## Purpose

This file turns living-community rules, review, and approval into one governed product surface instead of three separate chores.

It is the practical bridge between:

- `KARMA FORGE`
- rule-environment truth
- open-run recruitment
- quickstart runner paths
- community review and approval

## Canonical rule

A `CommunityRuleEnvironment` is Chummer-owned product truth.

It composes:

- one base ruleset and source-pack posture
- any allowed house-rule packs or amend packages
- banned or restricted content
- character-approval policy
- join-policy defaults
- export-target posture for play surfaces

It does not replace engine truth.
It narrows or composes existing rule-environment truth through governed packages, approvals, and receipts.

## Why this matters

Living communities do not operate on “base SR6” alone.
They usually need:

- a named rules posture
- allowed and blocked content
- a review policy
- approved character state
- clear exports for PDFs or VTT handoff

Without that bridge, players still have to guess whether their runner is valid for one table or season.

## Data model

```yaml
community_rule_environment:
  id: cre_shadowcasters_seattle_01
  community_ref: shadowcasters_network
  season_ref: season_seattle_001
  world_ref: seattle_shared_01
  base_rule_environment_ref: sr6_shadowcasters_seattle
  source_packs:
    - sr6_core
    - sr6_companion_allowed
  house_rule_packs:
    - shadowcasters_season_01_house_rules
  banned_content:
    - preview_ware_alpha
    - deprecated_matrix_technique_set
  approval_policy:
    mode: character_review_required
    reviewer_role: organizer_or_character_curator
    renewal_trigger: ruleset_or_amend_change
  join_policy_defaults:
    preset_ref: beginner_one_shot
  export_targets:
    - pdf
    - foundry
    - roll20
  quickstart_policy:
    approved_packs_allowed: true
  ownership:
    truth_owner: chummer6-hub
```

## Approval loop

1. Operator publishes or activates a `CommunityRuleEnvironment`.
2. Player selects a runner dossier or quickstart runner pack.
3. Chummer evaluates legality and conflict reasons against the active community environment.
4. Reviewer approves, rejects, or requests changes with a receipt-bearing decision.
5. Open-run application preflight reuses the same environment and approval state instead of inventing a second legality path.

## Player-facing promise

The user should be able to see:

> Your runner is legal for base SR6, but not yet legal for Shadowcasters Seattle Season 01.
> Here are the three conflicts, the blocked tags, and the next safe action.

That message is the product value.
Anything fuzzier is not good enough.

## Mobile and no-PC posture

Community rule environments must support a real “no Windows PC yet” path.

That means:

- quickstart runners can be community-approved
- legality conflicts are readable on mobile
- application preflight can pass or fail without desktop-only tooling
- accepted players can still receive the right exports and session packet later

## First proof gate

**Seattle Open Run 001**

Includes:

1. one published `CommunityRuleEnvironment`
2. one review-required player runner
3. one approved quickstart runner pack
4. one readable conflict explanation for a non-compliant dossier
5. one open-run application that consumes the same environment and approval receipt

Success criterion:

> A player can tell whether their runner is valid for this community before the GM has to manually inspect the sheet in Discord.
