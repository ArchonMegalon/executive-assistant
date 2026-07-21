# ORIGIN BOOK STUDIO

Some older uploaded files are no longer available, so this design is self-contained and does not depend on them.

## Product decision

Chummer should keep origin canon, mechanics snapshots, approvals, validation, and export control internal.

Subscribr is the default creative and content-production lane for:

* the real full-story manuscript drafted from the approved origin packet
* chapter-by-chapter scene writing and revision passes for that book
* important-scene and chapter-summary extraction after the book is approved
* narration scripts
* dossier intros
* video-ready scene plans
* creator-facing and player-facing explainer drafts

First Book ai is the premium long-form lane after a packet is already approved.

External providers may help with structure, prose, layout, export, covers, narration, or optional editorial packaging, but they must never own the runner's history.

```text
Runner dossier and origin canon truth
-> approved source packet
-> Subscribr narration, script, or production draft
-> Chummer validation and review
-> optional First Book ai premium book packet
-> chapter and export review
-> EPUB, PDF, DOCX, Markdown, audiobook
```

Internal components:

```text
OriginSourcePacketBuilder
OriginBookStudio
OriginCanonGraph
OriginContinuityAuditor
OriginBookPacketValidator
OriginPublicationRenderer
SubscribrManuscriptLane
OriginPublicationProviderRouter
```

Fundamental rule:

```text
Chummer owns facts, legality, lineage, approvals, and exports.
Subscribr explains approved packets.
First Book ai productizes approved packet sets into premium long-form books or manuals.
The player decides what becomes personal canon.
The GM approves anything that affects campaign canon.
```

Do not ship this as one button that sends a giant prompt to a model and accepts whatever comes back. Long-form runner fiction still needs explicit memory, source packets, continuity checks, chapter review, and packet-to-export validation before anything becomes player or campaign canon.

## Product modes

The flagship release should start with a real full-ebook lane.
Preview material is useful for proofing and early review, but it is not the promised player handoff.

| Mode | Target length | Structure | Use |
| --- | ---: | ---: | --- |
| Origin Preview Packet | 1,500-3,000 words | 2-4 sections | proofing, early review, and table alignment |
| Origin Script Packet | 1,000-3,000 words | modular scenes | narration, video, and explainer drafts |
| Narrative Origin | 10,000-15,000 words | 8-10 chapters | default flagship full-ebook deliverable |
| Runner Memoir | 15,000-25,000 words | 10-14 chapters | deluxe personal edition |
| Intelligence Casefile | 5,000-10,000 words | modular dossier | in-universe file set |

The default flagship lane should be `Narrative Origin`.
`Origin Preview Packet` is not enough for the player-facing promise by itself and must never satisfy a flagship ebook gate.

`Runner Memoir` is the deluxe lane. It is not the default burden placed on every player.

## Narrative styles

```yaml
styles:
  cinematic_third_person:
  first_person_memoir:
  intelligence_dossier:
  oral_history:
  noir_confession:
  mixed_archive:
```

The style changes presentation, not canon truth.

## Canon-first data model

The prose is not the source of truth.

```yaml
OriginBookProject:
  id:
  runner_id:
  campaign_id:
  owner_user_id:
  source_snapshot_id:
  book_spec:
  canon_graph:
  narrative_bible:
  outline:
  chapter_versions:
  continuity_findings:
  approvals:
  publication_artifacts:
  status:
  created_at:
  updated_at:
```

```yaml
OriginCanonGraph:
  identity:
  life_stages:
  events:
  people:
  organizations:
  places:
  possessions:
  augmentations:
  beliefs:
  promises:
  fears:
  secrets:
  debts:
  enemies:
  unresolved_threads:
  game_impact_proposals:
```

```yaml
OriginEvent:
  id:
  title:
  summary:
  start_age:
  end_age:
  start_date:
  end_date:
  location_id:
  participant_ids:
  event_type:
  emotional_valence:
  severity:
  runner_agency:
  immediate_consequence:
  long_term_consequence:
  belief_created_or_changed:
  skill_learned:
  relationship_change:
  secret_created:
  unresolved_thread_id:
  canon_status:
  secrecy:
  narrative_permission:
  source_reference:
```

Critical separation:

```yaml
GameImpactProposal:
  id:
  type: contact | enemy | debt | quality | secret | hook | resource
  narrative_source:
  proposed_value:
  player_approval:
  gm_approval:
  applied_to_character: false
```

A model may suggest that someone from the story should become a contact. It may not add that contact automatically.

## Player experience

Add a dedicated runner workspace:

```text
Runner
└── Origin
    ├── Life Map
    ├── Book Studio
    ├── Canon
    ├── Review
    └── Editions
```

Core flow:

1. Book setup
2. explicit source selection
3. Life Map timeline
4. story-arc proposals
5. hierarchical outline
6. incremental drafting and review
7. ebook packaging with fitted cover art
8. full ebook handoff
9. three-portrait shortlist
10. voice choice for optional audiobook
11. important-scene summary board
12. one chosen cinematic scene request

The player must see exactly what source material is being processed, what is excluded, and what still needs approval.

## Flagship player handoff contract

The player-facing promise is explicit:

1. Chummer freezes the approved origin packet and source snapshot.
2. Subscribr drafts the real full story manuscript from that approved packet.
3. Chummer runs continuity, humanization, and chapter review until the manuscript is accepted.
4. Magicfit renders the fitting cover art for that accepted story.
5. Chummer packages and hands over the finished ebook with that cover embedded.
6. Only after ebook handoff, Chummer unlocks exactly three story-fit portrait options.
7. The player chooses one portrait as the edition face.
8. The player can request the audiobook in the voice they choose.
9. Chummer presents important chapter or scene summaries from the approved book.
10. The player chooses one summarized scene for one bounded cinematic render with the selected character visible in it.

The player must receive the finished ebook before portraits, audio, or cinema unlock.
The cover belongs to the ebook handoff itself.
The portrait choice, voice choice, and scene choice all stay downstream from the same approved manuscript.

Implementation gate:

```text
FullStoryVerified
  requires Subscribr full-story manuscript receipt plus an ebook-length chaptered manuscript artifact.

EbookHandoffReady
  requires the accepted manuscript, fitted cover, packaged ebook, scoped read/share handoff, and import receipt.

Portrait, audiobook voice, and cinematic scene controls
  must bind to EbookHandoffReady, not merely to BookArtifactVerified or fitted-cover booleans.
```

If the ebook handoff receipt is missing, the user may see that the story is in progress, but they must not be allowed to choose portraits, request an audiobook voice, or request a cinematic render.

## Media follow-through

After the manuscript is approved:

* `Magicfit` is the preferred visual lane for the cover art that ships with the ebook
* `Magicfit` is the preferred visual lane for the three portrait options
* the player chooses one portrait after reading the story
* audiobook request happens after ebook handoff and includes explicit voice choice
* Chummer presents the important scenes or chapters as summaries from the approved book
* the player chooses one scene for the bounded cinematic render with the character visible in it

The full story remains the anchor artifact.
The cover belongs to the ebook handoff, not a detached later asset. Portraits, audio, and cinema are downstream packages from that same approved book.

## Generation pipeline

```text
Snapshot
-> narrative bible
-> hierarchical outline
-> scene writing packets
-> incremental drafting
-> continuity audit
-> revision passes
-> publication
```

Recommended units:

```yaml
scene_length: 400-900 words
chapter_length: 1200-2200 words
```

Every scene should checkpoint memory, update timeline state, and run local consistency checks before the chapter continues.

Every chapter should run:

```yaml
audits:
  - canon
  - temporal
  - relationship
  - repetition
  - memory summary
```

Run an additional mid-book audit because long narrative systems commonly drift in the middle if continuity is not checked explicitly.

## Continuity system

Memory layers:

```yaml
memory:
  immutable_canon:
  timeline:
  entity_state:
  chapter_summary:
  unresolved_threads:
  style_memory:
```

Continuity findings:

```yaml
ContinuityFinding:
  category:
    - identity
    - temporal
    - spatial
    - causal
    - relationship
    - physical_state
    - knowledge
    - object_inventory
    - augmentation
    - secrecy
    - terminology
    - game_mechanics
  severity:
    - hard
    - probable
    - stylistic
  evidence:
  conflicting_evidence:
  suggested_resolution:
  requires_user_decision:
```

No published edition may ship with a hard continuity finding.

## Provider architecture

Provider-neutral interface:

```csharp
public interface IOriginBookModelProvider
{
    Task<NarrativeBible> CreateBibleAsync(...);
    Task<BookOutline> CreateOutlineAsync(...);
    Task<SceneDraft> DraftSceneAsync(...);
    Task<MemoryDelta> ExtractMemoryAsync(...);
    Task<IReadOnlyList<ContinuityFinding>> AuditAsync(...);
    Task<SceneDraft> ReviseAsync(...);
    Task<string> TranslateAsync(...);
}
```

Long books need resumable background jobs, scene checkpoints, retries, provider failover, pause, cancel, and partial-edit survival after restart.

## Privacy and campaign safety

Default posture:

```yaml
visibility: private_player
external_processing: disabled_until_consent
public_sharing: false
```

Never send GM-only notes, other players' private data, payment data, credentials, or copied sourcebook prose to an external provider.

Generate different editions from the canon graph itself:

```yaml
editions:
  player_private:
  player_and_gm:
  table_safe:
  public_safe:
```

Do not redact final prose by brittle string replacement.

## Publishing pipeline

Required exports:

```yaml
outputs:
  - Markdown
  - DOCX
  - PDF
  - EPUB
  - JSON project archive
```

Later deluxe outputs:

```yaml
deluxe_outputs:
  - MP3 chapters
  - M4B audiobook
  - cover variants
  - chapter illustrations
  - optional media-overlay EPUB
```

## Existing tool posture

Chummer still owns the book.

```yaml
First_Book_AI:
  role: benchmark and operator experiment
  not_runtime_truth: true

Syllabbles:
  role:
    - ebook packaging
    - audiobook packaging
    - MP3/M4B export
    - cover experiments

Unmixr:
  role:
    - narration
    - pronunciation workflow

FlipLink:
  role:
    - private and public-safe browser presentation

Prompt_Architects:
  role:
    - prompt-template development

Poppy:
  role:
    - operator ideation

First_Book_ai:
  role:
    - premium long-form editorial presentation
    - chaptered dossier book or anthology lane
    - DOCX, PDF, EPUB, and Markdown export lane
    - bounded secondary output, never canon truth

BrowserAct_manual_export:
  role:
    - browser fallback for export capture when direct provider APIs are weak or absent
    - bounded secondary output, never canon truth
```

## Premium posture

First Book ai belongs on the premium branch, not the canonical branch.

```yaml
free:
  included:
    - Origin Dossier
    - Origin Script Packet
    - Markdown

premium:
  adds:
    - chaptered First Book ai edition
    - optional Runner Memoir render
    - bounded editorial packaging experiments
    - DOCX
    - PDF
    - EPUB
```

Rules:

* First Book ai may render a deluxe edition from approved Chummer canon.
* First Book ai must not become the source of runner history.
* First Book ai output remains optional and rejectable.
* No First Book ai prose invention may mutate the runner, campaign canon, or game state automatically.
* BrowserAct fallback export capture may assist when needed, but it does not become provider truth or publication truth.

## Repo ownership

```yaml
chummer6_core:
  owns:
    - OriginCanonGraph
    - timeline
    - approvals
    - game-impact proposals
    - continuity constraints

chummer6_ui:
  owns:
    - Life Map
    - Book Studio
    - outline editor
    - manuscript editor
    - canon inspector
    - diff and review UI

chummer6_hub:
  owns:
    - generation jobs
    - cloud sync
    - edition sharing
    - GM approval workflow

chummer6_media_factory:
  owns:
    - cover assets
    - chapter art
    - audiobook
    - trailer generation
    - publication packaging
```

## Implementation phases

1. Canon and Life Map
2. Planning
3. Drafting
4. Continuity and revision
5. Publication
6. Audiobook and deluxe editions
7. Living editions

Required first release:

* Origin Dossier
* Narrative Origin
* Life Map
* sample chapter approval
* chapter-by-chapter generation
* canon inspector
* continuity audit
* Markdown, DOCX, PDF, and EPUB export

## Quality gate

Must pass:

```yaml
must_pass:
  - zero hard canon contradictions
  - zero GM-secret leaks
  - zero unapproved game-state changes
  - every chapter advances the arc
  - every act contains runner agency
  - voice remains stable
  - all locked text preserved
  - all unresolved threads intentional
  - EPUB validates
  - accessibility metadata present
  - PDF navigation works
  - player approval complete
```

Final verdict:

```text
ORIGIN_BOOK_STUDIO_READY
```

Not ready if the product is merely:

```text
send runner data to model
-> receive long text
-> export PDF
```

## Developer directive

Implement Origin Book Studio as a canon-first, provider-neutral, hierarchical long-form generation system.

The model may propose arcs, outlines, scene drafts, memory deltas, critique, and revisions.

The model may not:

* alter runner statistics
* create canonical contacts or enemies automatically
* expose GM-only material
* reproduce sourcebook prose
* publish without approval

Chummer must own canon, permissions, secrets, continuity findings, editions, and publication state.

## References

This document is the canonical long-form design for Chummer's book-generation lane.

Related product documents:

* `products/chummer/horizons/origin-dossier.md`
* `products/chummer/horizons/alice.md`
* `products/chummer/public-guide/HORIZONS/origin-dossier.md`
