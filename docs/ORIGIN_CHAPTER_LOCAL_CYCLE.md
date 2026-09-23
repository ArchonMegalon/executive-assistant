# Local Origin chapter execution cycle

`scripts/origin_chapter_cycle.py` composes the existing private First Book
preparation, outline, writer and Hub-result adapters. It advances **one exact
approved job** without an operator copying provider IDs/outlines between phases.
It does not create Hub jobs, select accounts, reserve credits, accept stories,
change a character or publish anything. Hub remains consent/job/reader authority.

## Private input and execution

Use the existing private worker packet with its exact `work_id`,
`execution_admission`, `approved_source` and `setup`. Add:

- `automatic_execution_approved: true` at the packet root;
- `chapter_generation_approved: true` inside `setup`;
- the owned `browser_session`, provider account hash and exact source digest.

Those assertions belong to the trusted local controller/operator, never the
public app or provider output. They cannot substitute for fresh Hub admission.
Input files remain owner-only; do not put tokens or browser cookies in packets.

For the initial book, keep the existing separate approvals:
`framework_generation_approved`, `outline_activation_approved` and
`maximum_book_credits: 1`. Optional `framework_project_discovery_approved: true`
allows the completed framework to be identified without manually copying its
provider ID. Discovery requires the exact retained dispatch session/page, a
unique expected title, the verified provider account, one provider ID and exact
premise/goal/audience. It cannot bind by title alone, leave an active generation,
start a second project or authorize a second credit. A lost/cold dispatch page
still requires explicit reconciliation using the existing project-binding path.

For a later chapter, supply the existing `previous` packet and
`setup.outline_update_approved: true`. The predecessor is not guessed from queue
order or provider slot count. Its exact Hub reader acceptance is checked before
continuing; old chapters and other outline slots remain unchanged. The paid book
is reused. The current chapter itself always stops at `review_required`.

```sh
python3 -m scripts.origin_chapter_cycle \
  --packet-path /private/exact-approved-job.json \
  --hub-origin http://127.0.0.1:15099 --hub-host chummer.run \
  --token-file /private/worker.token --output-root /private/provider-journals \
  --cycles 30 --interval 10
```

Default execution is one non-waiting cycle. Bounded observation accepts at most
120 cycles with 2–60 seconds between them. The loop observes only named in-flight
transitions; it stops on reader approval requirements, reconciliation, unknown
states, transport errors or browser failures. It does not retry uncertain writes.
The root-wide cycle lease is held during observation waits. The controller must
also own the browser session exclusively; do not run older manual adapters in
parallel against that session or use a different journal root for the same book.

Setup, activation, outline saves, advancement and chapter generation retain their
existing separate fsynced dispatch fences. The cycle derives prepared inputs from
those validated journals, not a caller-supplied replacement mapping. A completed
Hub result needs only one GET and no browser. A missing journal after a consumed
admission is reconciliation-only, never permission to regenerate.

## Delivery status and remaining work

This adds phase orchestration, **not a deployed queue service**. Automatic Hub
pending-job intake, bounded provider-account admission and authenticated
predecessor selection still need to be connected. No polling daemon or new
spending policy is enabled by installing this module. The current live browser
authorization remains synthetic-only; this change does not authorize real-user
source uploads to the provider.

Focused tests exercise exact preparation handoffs, next-slot continuation,
one-write fencing, missing/changed Hub authority, acceptance boundaries, finite
observation, lock ownership and project discovery. Simulated-browser tests are
not a new live generation or Android UI proof. Existing signed-Hub chapter
reconciliation can be tested read-only with provider calls and POSTs forbidden.

Android reading/adoption/export, public account routing and local signing/Play
delivery remain separate unfinished work. No new publication claim follows from
a successful cycle.
