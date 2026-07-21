# Live Action Economy And Turn Assist

**Product:** Chummer6 / SR Campaign OS
**Design area:** Build, Play, GM Runboard, Mobile Table Sheet
**Status:** Proposal / release-gated loop

## North star

At any moment in combat, Chummer tells every player and the GM what that actor can still do.

This lane is one slice of the broader live-session turn companion defined in `LIVE_SESSION_TURN_COMPANION.md`.
It must improve live-turn resolution without turning the phone surface into a compressed builder.

## Why this matters

SR6 action economy is valuable product territory:

* it is easy to misremember under pressure
* it changes from turn to turn
* it benefits from receipts instead of table folklore

This is a trust loop, not a VTT replacement.

## Explain contract

This lane is a flagship explain-every-value route under `EXPLAIN_EVERY_VALUE_AND_GROUNDED_FOLLOW_UP.md`.
Every visible major/minor count, conversion, action affordance, and between-turn warning must support packet-backed quick explain, source-anchor posture, and bounded `why?`, `why not?`, and `what if I spend this now?` follow-up.

## Core object

```yaml
ActionBudgetResult:
  actor_ref: runner_or_npc_ref
  round_ref: run_round_ref
  rule_environment_ref: campaign_rule_env_ref
  major:
    base: 1
    available: 1
    spent: 0
  minor:
    computed: 4
    turn_start_cap: 5
    available: 4
    spent: 0
  conversions:
    can_spend_four_minor_for_anytime_major: true
    can_hold_converted_major_before_turn: false
  explanation_packet_ref: action_budget_current_packet
  counterfactual_actions:
    - spend_four_minor_for_full_defense
  affordances:
    - action_key: full_defense
      timing: anytime
      state: available
      cost:
        minor: 4
  receipts:
    - source_anchor_ref: sr6_core_minor_actions
```

## User surfaces

### Player

```text
Your turn
  1 Major
  4 Minor

You can still:
  Attack
  Move
  Take Cover
  Reload
  Full Defense

[Explain 4 Minor]
```

The player surface may also expose:

* current health or stun posture
* ammo or charge posture for the active action
* active modifiers with source-backed labels
* quick odds for the current action
* digital roll or manual physical-roll entry

### Between turns

```text
Before your next turn:
  You can still spend 4 Minor for Full Defense.
  If you do, you will begin your next turn with no Minor Actions remaining.
```

### GM Runboard

```text
Grunt Group A
  6 members
  3 wounded
  2 suppressed
  1 action-budget warning
```

## Required rules truth

`chummer6-core` owns:

* `ActionBudgetResult`
* `ActionAffordance`
* `TurnLedgerDelta`
* `ExplanationPacket` and bounded counterfactual packets for action-budget truth
* official SR6 edge-case tests for minor action count, turn-start cap, and conversion behavior

`chummer6-ui-kit` may own generic bars, chips, or cards.
It must not own action math.

## First release gate

```text
player_completes_sr6_combat_round_with_action_budget
```

Exit:

* one player and one GM can complete one SR6 combat round
* action receipts remain visible during and between turns
* quick explain can defend why an affordance is available, unavailable, or timing-limited
* a bounded counterfactual such as spending 4 Minor for Full Defense can be previewed without mutating current truth blindly
* the user can resolve the action with either digital rolling or manual physical-roll entry
* mook/grunt state is summarized without requiring a full tactical map
