# RUNSITE

## Explanation video

[Watch the RUNSITE 90-second deep dive](https://chummer.run/media/horizons/runsite-90s-deepdive.mp4) - MP4 with AAC audio. [Captions](https://chummer.run/media/horizons/runsite-90s-deepdive.vtt).

## The problem

GMs spend too long describing spaces, and players still misread compounds, clubs, hotels, museums, arcologies, and safehouses once the action starts.

## What it would do

Chummer would publish explorable location packs linked to mission briefings.
They could include floor plans, hotspots, route overlays, optional narration, and static map context, but they stay focused on helping you understand the space before the run starts, not on replacing live combat tools or a VTT.
RUNSITE is for briefing, planning, and spatial understanding before things go loud.

## Likely owners

* `chummer6-hub`
* `chummer6-media-factory`

## Key tool posture

* `Crezlo Tours` - primary explorable-tour lane
* `AvoMap` - route and location visualization support
* `PeekShot` - preview/share-card adapter
* `vidBoard` - bounded orientation-host and walkthrough clip lane
* `Soundmadeseen` - optional narration layer
* `BrowserAct` - bounded operator automation and capture fallback

## What has to be true first

* clean media manifests
* permissioned publication links
* preview and embed receipts
* reliable map and render adapters

## What is ready now

RUNSITE is now a shipped first-party prep lane.
The public rail exposes real runsite packs on markdown and JSON routes plus a named receipt at `/runsites/receipts/prep-network.json`.
The signed-in rail is no longer generic workspace spillover; it has a named bench at `/account/runsites`, a named redirect lane at `/account/runsites/open`, and workspace detail routes at `/account/runsites/{workspaceId}`.
Typed prep and run APIs are first-class too:

* `/api/v1/campaign-spine/me/workspace-digests`
* `/api/v1/campaign-spine/me/workspaces/{workspaceId}`
* `/api/v1/campaign-spine/me/workspaces/{workspaceId}/prep-library`
* `/api/v1/campaign-spine/me/runs`
* `/api/v1/campaign-spine/me/runs/{runId}`

## Boundary

RUNSITE is a prep and orientation lane.
It does not claim tactical authority, live-map truth, or VTT replacement status. Route overlays, tours, and host clips stay subordinate to first-party workspace and run truth.
