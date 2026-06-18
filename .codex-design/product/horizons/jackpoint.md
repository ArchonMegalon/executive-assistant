# JACKPOINT

## Explanation video

[Watch the JACKPOINT 90-second deep dive](https://chummer.run/media/horizons/jackpoint-90s-deepdive.mp4) - MP4 with AAC audio. [Captions](https://chummer.run/media/horizons/jackpoint-90s-deepdive.vtt).

## The problem

Players and GMs want dossiers, recaps, primers, and narrated briefings, but most content tools either invent details or strip away where the facts came from.

## What it would do

JACKPOINT would turn approved session material into dossiers, recaps, narrated briefings, evidence rooms, share cards, and creator packs.
It is the short-to-medium-form publishing studio, not a replacement for full books.

## Likely owners

* `chummer6-hub`
* `chummer6-hub-registry`
* `chummer6-media-factory`

## Key tool posture

* `MarkupGo` - document/render adapter lane
* `vidBoard` - structured presenter-video and multilingual briefing lane
* `Soundmadeseen` - narrated recap and briefing media lane
* `Unmixr AI` - candidate voice lane until proven
* `PeekShot` - preview/share-card adapter
* `Documentation.AI` - downstream docs/help projection
* `Paperguide` - cited grounding helper
* `Mootion` - bounded video support
* `First Book ai` - bounded overflow support when the artifact lane needs long-form carryover

## What has to be true first

* a fact trail that survives formatting
* approval states
* registry and media working together cleanly
* source classification
* reliable publication workflows

## What is ready now

JACKPOINT is now a shipped first-party briefing lane.
The public rail exposes real dossier and mission-brief packets on markdown and JSON routes plus a named receipt at `/jackpoint/receipts/briefing-network.json`.
The signed-in rail is no longer generic account spillover; it has a named desk at `/account/jackpoint`, a named redirect lane at `/account/jackpoint/open`, and publication detail routes at `/account/jackpoint/{publicationId}`.
Typed publication APIs are first-class too:

* `/api/v1/campaign-spine/me/publications`
* `/api/v1/campaign-spine/me/publications/{publicationId}`

## Boundary

JACKPOINT is a publication-safe briefing and dossier lane.
It does not claim GM-private spoiler authority on the public rail, and it does not hand publication truth to external narration or asset hosts.
