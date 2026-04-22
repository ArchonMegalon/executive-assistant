# World contracts reserved

## Purpose

`Chummer.World.Contracts` is reserved for BLACK LEDGER and campaign-adjacent world-state semantics.

The package is already referenced in `CONTRACT_SETS.yaml`.
This file makes the near-term reservation explicit so later repos do not source-copy or smuggle world-state DTOs into unrelated contract families.

## Canonical rule

World-state, mission-market, and world-tick semantics belong in `Chummer.World.Contracts`.

They must not be redefined inside:

- `Chummer.Campaign.Contracts`
- `Chummer.Control.Contracts`
- `Chummer.Media.Contracts`
- repo-local DTO folders

Campaign, control, and media layers may consume or project world objects.
They may not redefine the semantic family.

## Reserved DTO candidates

The first reserved object family is:

- `WorldFrame`
- `Region`
- `District`
- `DistrictPressure`
- `WorldMapMarker`
- `Faction`
- `FactionSeat`
- `StrategicResourcePool`
- `ResearchProject`
- `SpecialAsset`
- `OperationIntent`
- `HeatProfile`
- `IntelReport`
- `IntelReviewDecision`
- `JobSeed`
- `JobPacket`
- `RunPlan`
- `ResolutionReport`
- `WorldTick`
- `NewsReel`
- `NewsReelItem`
- `WorldContributionCredit`

## Adjacent object candidates

While BLACK LEDGER is still proving practical open-run and shared-world value, the following objects may begin adjacent to the world lane before later package splits:

- `OpenRun`
- `JoinPolicy`
- `RunApplication`
- `RunApplicationPreflight`
- `MeetingHandoff`
- `ObserverConsent`
- `TableContract`
- `QuickstartRunnerPack`
- `OppositionPacket`

`CommunityRuleEnvironment` composes long-lived rule-environment truth and therefore stays adjacent to `Chummer.Campaign.Contracts` rather than moving into `Chummer.World.Contracts`.

## Ownership posture

Initial semantic owner:

- `chummer6-hub`

Primary consumers:

- `chummer6-hub`
- `chummer6-ui`
- `chummer6-mobile`
- `chummer6-media-factory`
- `fleet`
- `executive-assistant`

Forbidden source copies:

- `chummer6-core`
- `chummer6-ui`
- `chummer6-mobile`
- `chummer6-media-factory`
- `chummer6-hub-registry`

## Boundary notes

- `RunPlan` belongs to world and mission workflow truth, even when a calendar projection exists.
- `ResolutionReport` belongs to world consequence truth, even when campaign workspace projections consume it.
- `NewsReel` and `NewsReelItem` belong to world publication semantics, even when rendered by media-factory.
- `IntelReport` is not world truth until an authorized review or adoption path promotes it.
