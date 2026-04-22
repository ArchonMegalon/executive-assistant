# Find and join an open run

Status: future_slice_with_bounded_research

## User goal

Find a real table, understand whether the runner fits, get scheduled cleanly, and arrive in the right session space without stitching together Discord, calendars, rules notes, and exports by hand.

## Entry surfaces

* `chummer.run` public guide and future open-run discovery surfaces
* `chummer6-hub` world map, run board, and scheduling receipts
* `chummer6-mobile` quickstart, application, and readiness surfaces
* `chummer6-ui` GM review, preflight, and prep surfaces

## Happy path

1. The player opens an `OpenRun` from the world map or run board and can see the table contract, community rule environment, and scheduling posture before applying.
2. The player selects either an approved living dossier or an approved quickstart runner pack.
3. Chummer runs explainable preflight over legality, role fit, scheduling, consent, and handoff readiness instead of forcing the GM to reconstruct that logic manually.
4. The GM reviews the same preflight summary the player saw, accepts or waitlists the application, and does not have to reverse-engineer legality from screenshots or chat logs.
5. Hub records one scheduling receipt and one meeting handoff, while Discord, Teams, or a VTT remain projection-only surfaces instead of becoming the run authority.
6. The player receives the session details, any allowed handout or export packet, and the right next-safe-action cues before the game starts.
7. After the run, the GM files a `ResolutionReport`, and the result becomes world-memory instead of disappearing into chat history.

## Failure modes

* If a runner is not legal for the active community rule environment, the player must see the actual conflicts and next safe actions before the GM reviews the application.
* If a quickstart path exists, it must resolve real beginner or mobile-entry friction instead of acting like a second-class fake runner lane.
* If scheduling or meeting handoff drift occurs, Chummer-owned receipts must win and the fix must be visible as a projection repair, not silent data disagreement.
* If Discord, Teams, or a VTT changes state after roster lock, the run, roster, consent, and consequence truth must remain in Chummer.
* If the session closes out, the product must leave visible world-memory artifacts instead of making the table rely on recap-by-chat-scroll.

## Success evidence

* A player can understand fit before GM review.
* A mobile-first player can apply through a quickstart path without a Windows-only requirement.
* The GM can fill the table and prepare the run without spreadsheet glue.
* Scheduling receipts and meeting handoff remain aligned.
* World-memory or player-safe recap surfaces show that the run changed something real.

## Canonical owners

* `chummer6-hub`
* `chummer6-ui`
* `chummer6-mobile`
* `fleet`
* `executive-assistant`
* `chummer6-media-factory`
