# Newsreel and city ticker model

## Purpose

This file defines how BLACK LEDGER turns approved world-state changes into player-safe, campaign-private, faction-private, or GM-rich world outputs.

The newsreel lane exists to make the city feel alive without leaking spoilers or confusing rendered media with canonical truth.

## Canonical rule

The world talks back through approved summaries.
Those summaries are downstream of Chummer-owned truth.

Rendered ticker cards, host clips, bulletins, and social cuts do not become world truth by themselves.

## Source truth

Valid source objects are:

- `WorldTick`
- `ResolutionReport`
- `IntelReport`
- `DistrictPressure`
- `OperationIntent`
- `JobPacket`

Every news item must link back to one or more approved source objects.

## Spoiler policy

Every published item must carry both audience and spoiler-class posture.

```yaml
spoiler_policy:
  player_safe_summary:
    allows:
      - visible district pressure
      - public rumors
      - already-public service disruption
    forbids:
      - hidden employer identity
      - unrevealed runner betrayal
      - exact payout details
  campaign_private_aftermath:
    allows:
      - table-earned fallout
      - contact shifts already visible to the campaign
  gm_private_detail:
    allows:
      - full causal chain
      - unpublished branches
      - rejected publication candidates
```

Every player-safe item must record a `redaction_basis`.
No public-safe render may reveal names, motives, or rewards that only exist in GM-private or faction-secret source material.

## News item model

```yaml
news_reel_item:
  id: news_00088
  world_tick_ref: tick_seattle_0007
  audience: public_player_safe
  headline: Tacoma Port Authority denies drone lockdown rumors
  truth_link:
    source: resolution_report
    source_ref: rr_00031
    truth_grade: player_safe_summary
  redaction_basis:
    - hide employer identity
    - hide exact cargo contents
  approval_state: approved
```

## Variants

Allowed audience variants:

- `public`
- `campaign`
- `gm`
- `faction`
- `organizer`

Visibility must remain narrower than or equal to the source objects that support the item.

## Pipeline

1. Fleet drafts a tick packet and candidate publication bundle.
2. Executive Assistant drafts headline and body variants.
3. Hub or the world operator approves truth grade and audience class.
4. Media Factory renders:
   - text ticker
   - PeekShot card
   - vidBoard host reel
   - optional Taja short cut
   - optional MarkupGo bulletin
5. Hub publishes the approved audience variants.

## Hard boundaries

- No public item may reveal GM-only, faction-secret, or organizer-only truth.
- No media render may bypass Hub-owned approval state.
- No social cut may become the only surviving evidence of an event; the source packet must exist first.
- Calendar events, draft intel, or raw AI synthesis are not sufficient publication truth by themselves.

## First proof

The first BLACK LEDGER proof only needs:

- one public-safe city ticker
- one short host-style city update
- one share card

That is enough to prove that the city can talk back without overbuilding a full media season stack.
