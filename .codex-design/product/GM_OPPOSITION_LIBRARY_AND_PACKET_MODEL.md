# GM opposition library and packet model

## Purpose

This file defines the reusable opposition and encounter-prep layer that turns BLACK LEDGER pressure into tangible session material.

## Canonical rule

An `OppositionPacket` is a reusable, export-ready prep object.

It should be:

- rule-environment aware
- faction or pressure aware when relevant
- reusable across runs
- exportable to play surfaces
- readable as a GM prep packet even outside a VTT

It does not replace bespoke NPC authoring.
It gives GMs a practical starting point fast.

## Packet families

- ganger squad
- corp security team
- spirit or ritual cell
- drone team
- elite named asset
- beginner one-shot opposition bundle

## Data model

```yaml
opposition_packet:
  id: opp_renraku_response_team_01
  type: corp_security_team
  professional_rating: 3
  faction_ref: renraku
  rule_environment_ref: sr6_community_hub_seattle
  heat_triggers:
    - matrix_heat_4
    - security_heat_3
  exports:
    - foundry
    - roll20
    - pdf
  contents:
    - stat_block_bundle
    - gear_bundle
    - tactics_notes
    - player_safe_hint_bundle
```

## BLACK LEDGER tie-in

World pressure should produce prep hooks, not only flavor text.

Example:

> Tacoma matrix heat hit 4.
> Renraku response team packet is now available for this run.

That is the difference between a cool world map and a useful one.

## GM-facing value

The GM should be able to:

- attach an opposition packet to a `JobPacket`
- export it to a VTT
- print or save it as a prep packet
- reuse it across beginner or season runs

## First proof gate

**Seattle Open Run 001**

Includes:

1. one beginner opposition packet
2. one faction-linked response packet
3. one PDF export
4. one VTT-facing export
5. one run packet that references the packet directly

Success criterion:

> BLACK LEDGER world pressure produces a concrete prep artifact a GM can use immediately.
