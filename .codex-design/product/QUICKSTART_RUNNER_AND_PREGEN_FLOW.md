# Quickstart runner and pregen flow

## Purpose

This file defines the low-friction entry path for new players and mobile-only users.

The goal is simple:

> A player should be able to join a real run before they master full Shadowrun character creation.

## Canonical rule

Quickstart runners are governed dossiers, not throwaway PDFs.

They must carry:

- an explicit rule environment
- community compatibility posture
- publication or approval state
- a conversion path into a living dossier later

## Why this matters

New players often hit four barriers at once:

- decision-heavy chargen
- gear overload
- community-specific rule changes
- desktop-only tooling expectations

Quickstarts reduce all four.

## Pack model

```yaml
quickstart_runner_pack:
  id: qrp_shadowcasters_starter_decker
  label: Starter Decker
  intended_role: matrix_support
  rule_environment_ref: sr6_shadowcasters_seattle
  community_rule_environment_refs:
    - cre_shadowcasters_seattle_01
  approval_state: preapproved
  surfaces:
    - mobile_apply
    - open_run_join
    - beginner_gm_autopilot
  conversion_policy:
    mode: promote_to_living_dossier_after_session
```

## Player flow

1. Player opens an `OpenRun`.
2. Chummer shows role needs and quickstart options.
3. Player chooses a quickstart runner or their own dossier.
4. Preflight checks legality and schedule.
5. GM accepts or waitlists.
6. After the run, the player can promote the quickstart into a living dossier or retire it.

## GM flow

The GM should be able to say:

> This table needs matrix support.
> Offer the approved starter decker if the applicant does not have one.

That is a practical staffing tool, not just an onboarding nicety.

## Mobile-first posture

Quickstarts are the safest first entry for:

- phone-first players
- new community members
- beginner one-shots
- recruitment pilots where full review would otherwise block sign-up

## First proof gate

**Seattle Open Run 001**

Includes:

1. three approved quickstart runners
2. one mobile application using a quickstart
3. one GM roster recommendation that fills a missing role
4. one post-session conversion path into a living dossier

Success criterion:

> A new player can join a run from mobile without full chargen, and the GM still gets a legal, role-aware roster.
