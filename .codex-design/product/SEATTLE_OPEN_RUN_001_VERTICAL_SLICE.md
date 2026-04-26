# Seattle Open Run 001 vertical slice

## Purpose

This file is the concrete execution slice for the practical BLACK LEDGER and COMMUNITY HUB expansion.

It exists to prevent scope drift.

## Canonical rule

The first proof must be a real run loop, not a giant shared-world simulation.

That means:

- one world
- one community rule environment
- one open run
- one real application path
- one scheduling handoff
- one prep packet
- one resolution and world-memory result

If this slice does not feel useful, the broader horizon should not widen.

## Slice promise

> A player can find a beginner-friendly run, apply with a legal runner or quickstart, get scheduled cleanly, play the session, and see the city remember the outcome.

## Included objects

- `WorldFrame`
- `JobPacket`
- `OpenRun`
- `CommunityRuleEnvironment`
- `RunApplication`
- `RunApplicationPreflight`
- `TableContract`
- `QuickstartRunnerPack`
- `SchedulingReceipt`
- `MeetingHandoff`
- `OppositionPacket`
- `ResolutionReport`
- one public-safe news item
- one typed reputation event

## Required flow

1. World operator or GM has one Seattle world frame and one governed job packet.
2. GM opens that job as an `OpenRun`.
3. The run binds to one `CommunityRuleEnvironment`.
4. The run publishes with one visible `TableContract`.
5. Player applies with either:
   - one approved living dossier, or
   - one approved quickstart runner pack.
6. Chummer runs explainable preflight.
7. GM accepts or waitlists.
8. Lunacal records one scheduling receipt.
9. Chummer reveals one Discord or Teams handoff.
10. GM receives one opposition packet and one player-safe handout export.
11. GM closes the session through one `ResolutionReport`.
12. BLACK LEDGER updates one visible world-memory surface.
13. One player-safe news or recap artifact is generated.
14. One bounded seasonal-honor or runner-legend event is recorded.

## Non-goals

- no full faction-seat season
- no broad public LFG market
- no automated moderation scoring
- no default-on observer recording
- no cross-city shared-world sprawl
- no “replace Discord/VTT” ambition

## Success criteria

- A player can understand whether they fit the table before GM review.
- A mobile-first player can apply through a quickstart path.
- A GM can publish, staff, prep, schedule, and close the run without spreadsheet glue.
- The meeting platform and VTT stay projection-only.
- The finished run leaves visible world memory.

## Failure signals

- the GM still needs manual Discord legality review
- rule conflicts are only discovered after acceptance
- quickstarts feel like second-class fake runners
- scheduling receipts and meeting handoff disagree
- the result does not visibly change the map or recap surface

## Owning repos

- `chummer6-hub`
- `chummer6-ui`
- `chummer6-mobile`
- `fleet`
- `executive-assistant`
- `chummer6-media-factory`

## Companion canon

- `OPEN_RUNS_AND_COMMUNITY_HUB.md`
- `COMMUNITY_RULE_ENVIRONMENTS_AND_APPROVAL.md`
- `RUN_APPLICATION_PREFLIGHT_MODEL.md`
- `QUICKSTART_RUNNER_AND_PREGEN_FLOW.md`
- `GM_OPPOSITION_LIBRARY_AND_PACKET_MODEL.md`
- `VTT_HANDOFF_AND_PLAY_SURFACE_EXPORTS.md`
- `SESSION_ZERO_AND_TABLE_CONTRACT_MODEL.md`
- `BEGINNER_GM_AUTOPILOT.md`
