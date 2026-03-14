# Chummer6 Visual Prompts

This file is the art-direction contract for generated Chummer6 guide images.

The short version: every image should show a real moment, and every image should hide one small troll easter egg in-world.

## Generation workflow

Use the image pipeline in this order:

1. Remote render a contextual scene, not a concept poster.
2. Inject a second art-direction instruction set for scene integrity and troll placement so the image keeps telling a story instead of inventing fake signage.
3. Normalize the output back to the target banner size.
4. QA the scene for context, legibility, and accidental text.
5. Apply the deterministic troll postpass only if the prompt-only path still loses the motif.
6. QA again before copying into the repo.

Why the postpass exists as a fallback:

- some remote models still hallucinate fake UI text
- some remote models hide tiny easter eggs in mushy lighting
- the troll motif needs to survive the pipeline, not just the prompt

The worker now supports targeted rerenders so one bad banner does not force a full pack rerun.

## Variation ledger

The guide should not keep discovering the same four leather jackets around the same table.

Every accepted render should write a scene-ledger row with:

- target path
- composition family
- cast signature
- subject
- mood
- easter egg kind
- provider
- prompt hash

Use that ledger before rerendering:

- do not reuse the same composition family on adjacent major pages when a different camera grammar would work
- do not let `safehouse_table` become the default answer for every product truth page
- if a new image shares composition with a recent one, force a different cast count, focal prop cluster, and camera distance
- at least one-third of the major banners should be prop-led, street-led, or environment-led instead of people-around-table scenes

## Style epochs

One full regeneration pass should share one style family on purpose.

Each pass gets one active style epoch with:

- style family name
- palette
- lighting model
- realism mode
- lens grammar
- texture treatment
- signage treatment
- troll motif material style
- weather bias
- humor ceiling

Inside one pass, every page should inherit that style epoch.

Inside that same pass, every page still needs a distinct:

- scene family
- cast count
- camera grammar
- prop cluster
- focal action
- troll motif type

The next full pass should deliberately switch to a different style epoch instead of rerolling the same look forever.

## Visual constitution

- Show a scene, not a concept poster.
- Give the image one focal action, one readable prop cluster, and one secondary clue.
- Keep the world grounded: table play, desks, alleys, labs, archives, shops, transit, cheap neon, expensive mistakes.
- Prefer props that explain the feature before the third paragraph does.
- Use symbol-first signage and unreadable paperwork. If the scene wants a joke sign, make it a pictogram, partial scribble, or crossed-out mascot, not crisp words.
- Avoid abstract UI wallpaper, floating icon soup, generic skylines, and brochure-cover posing.
- Diegetic overlays are fine if they appear attached to actual screens, AR views, or surfaces.
- No readable titles, no watermarks, no giant centered logos.
- No repeated medium-wide table huddles unless the page explicitly depends on that exact social geometry.
- A table scene is one scene family, not the default answer for truth, trust, or tension.

## Composition families

Use real scene families and rotate them on purpose:

- `over_shoulder_receipt`
- `solo_operator`
- `safehouse_table`
- `group_table`
- `dossier_desk`
- `archive_room`
- `simulation_lab`
- `workshop_bench`
- `service_rack`
- `street_front`
- `transit_checkpoint`
- `horizon_boulevard`
- `district_map`
- `desk_still_life`

Hard rules:

- no adjacent major pages with the same composition family
- no more than two table-huddle families across the top-level guide cluster
- `Horizons index` must be environment-first
- `ALICE` may never be another social table scene
- `JACKPOINT` should prefer dossier / evidence / desk grammar
- `Core` should prefer proof-on-props or over-shoulder receipt grammar over faces
- `WHAT_CHUMMER6_IS` should prefer one trust moment or over-shoulder proof, not another three-person confrontation

## Troll easter egg rule

Every generated Chummer6 image should include one small recurring troll motif.

The motif should feel diegetic:

- jacket pin
- stitched patch
- sticker on a phone, case, lamp post, or tray
- wax seal or dossier stamp
- tattoo
- transit ad or CRT mascot
- rude crossed-out troll pictogram on a door or service panel
- a real troll in the classic Chummer stance somewhere in the scene

The motif must be:

- visible on a README-scale banner
- secondary, not the main subject
- inside the safe crop
- not cropped to the edge
- integrated into the scene instead of pasted on top

## Prompt constitution

Use this language in prompts:

```text
Create a grounded cinematic 16:9 cyberpunk scene for a human-facing product guide.
Show a real moment, not an abstract infographic.
Include one clear focal action, one readable prop cluster, and one secondary story clue.
Include one small recurring Chummer troll motif in-world, visible but secondary, inside the safe crop area.
The troll motif must feel diegetic: a pin, patch, sticker, stamp, tattoo, ad, screen mascot, or background figure in the classic Chummer stance.
Do not center it. Do not make it the subject. Do not crop it out.
No abstract UI boxes floating in empty space. No generic wallpaper. No giant clean logo splash. No random text overlays.
Any signage, paperwork, or labels must be icon-first, blurred, cropped, or otherwise unreadable.
```

Use both symbolic and descriptive phrasing when needed:

- `small recurring Chummer troll motif`
- `front-facing troll figure with curved horns, broad shoulders, heavy arms, and the same squat stance as the Chummer troll mark`

That redundancy helps the motif survive prompt refinement.

## QA check

Use this after generation:

```text
Describe the hidden troll motif and where it appears in the scene.
If no troll motif is clearly visible, fail the image.
If the motif is only implied, cropped, or too tiny to notice on a README banner, fail the image.
```

Also fail the image if:

- it reads like wallpaper instead of a moment
- the focal action is unclear
- fake text becomes a major visual object
- the crop collapses the scene into a random close-up
- the troll lands on a face and accidentally becomes body-horror comedy

## Placement ideas

- Hero and landing scenes: pin on a jacket, transit ad in the midground, sticker on street hardware
- Table scenes: phone-case sticker, jacket pin, dice-bag charm
- Dossier and archive scenes: wax seal, approval stamp, chip-case sticker
- Forge and workshop scenes: shoulder patch, toolbag decal, bench sticker
- Simulation and lab scenes: warning decal on the bench or housing
- Discovery and market scenes: CRT mascot, ad panel, vendor patch
- Street and transit scenes: crossed-out troll pictogram on a side door, service panel, or bar placard

## Composition rules

- `README` hero: product-truth under pressure, ideally over-shoulder receipt proof or street-side stakes, not another generic huddle
- `WHAT_CHUMMER6_IS`: one trust moment with visible receipts, ideally solo or duo with the proof path doing the heavy lifting
- `Core`: over-shoulder or prop-led rules proof, where dice, sheets, traces, and chips carry the scene
- `Mobile`: play-shell continuity in motion, preferably asymmetrical devices or one reconnect moment instead of a posed group
- `Hub`: hosted coordination through racks, control surfaces, or remote-presence seams, not a table in disguise
- `NEXUS-PAN`: reconnect moment anchored around the returning device or operator, not a blurry background support group
- `ALICE`: sim bench / crash chamber / failure trace, never another social huddle
- `JACKPOINT`: dossier workspace first, faces optional
- `KARMA FORGE`: workshop bench or rulesmith station, not a concept slide and not another committee around a table
- `Horizons index`: boulevard/environment shot first, people secondary at most

## Page prompt starters

### Chummer6 hero

```text
Rainy street-side or transit-shelter truth moment where one runner sees the receipt trail that settles a tense rules call. Prefer over-shoulder proof, visible tactile props, and one in-world troll motif on hardware or public signage. Do not default to a committee around a table.
```

### Start Here

```text
A choice-point scene that feels like a subway map for user needs: session lane, proof lane, mod lane, future lane. The troll motif appears as a half-peeled sticker on the panel frame.
```

### What Chummer6 Is

```text
One trustworthy rules-truth moment: a runner gets an answer with receipts, and the proof path is visible enough to keep the scene moving. Prefer one operator plus a proof cluster, or an over-shoulder receipt scene, over another group huddle. The troll motif appears as a pin, sticker, or transit-side decal.
```

### Horizons index

```text
A neon horizon boulevard of future districts and signposts, with each lane hinting at a different table pain. The troll motif appears as a transit ad or distant station mascot.
```

### NEXUS-PAN

```text
Asymmetrical reconnect scene: one phone or handheld device comes back into the session, initiative and effects snap into place, and the table or operator does not have to stop for forensic bookkeeping. Prefer a solo or duo operator frame over another full-table huddle. The troll motif appears as a sticker on the reconnecting device or a nearby service panel.
```

### JACKPOINT

```text
Fixer dossier desk with verified and inferred tags, coffee rings, chip cases, and grounded evidence. The troll motif appears as a wax seal on one envelope.
```

### RULE X-RAY

```text
Dice pool breakdown hovering over a real character sheet like forensic evidence. The troll motif appears as a keychain or dice-bag charm near the bottom third.
```

### KARMA FORGE

```text
Workshop-bench rulesmithing scene with overlay shards, rollback markers, and conflict receipts made physical. Prefer a forge bench, tool wall, or one operator in the act over a whole group staring at a glowing table. The troll motif appears as a stitched patch on an apron or a decal on the bench hardware.
```

## Two-pass fallback

If the prompt-only render loses the troll motif:

1. Generate the scene first.
2. Normalize the output to the target banner crop.
3. Inpaint or composite the troll onto a chosen surface with a very specific material and placement.

This is more reliable than hoping a refinement layer preserves a subtle easter egg every time.

## Tooltip rule

Markdown image titles are for flavor text only during this debug run.

- keep them short
- make them funny when possible
- roast the dev freely if the scene invites it
- 4th-wall jokes are encouraged when they fit the page
- do not paste the full generation prompt into the title
