# Public Feedback and Roadmap Signal Model

This EA-local product note defines how Chummer may use ProductLift as a public feedback and roadmap signal intake surface.

## Boundary

ProductLift can collect, cluster, and report public feedback.
It is a signal intake surface, not an authority plane.

No public vote, request, label, or trend creates an automatic code change.
Signals must pass through the support and signal OODA loop, design triage, ownership routing, and release governance before they affect canon, queue, docs, or implementation.

## Operating Rules

* Public status is advisory unless backed by an approved release or support-case status event.
* Signal exports must preserve source, timestamp, category, and triage mapping.
* Roadmap labels must not imply funded, scheduled, or committed work unless another approved artifact says so.
* Private support details and campaign-private data must not be copied into public roadmap surfaces.

## Freshness Gate

`PUBLIC_FEEDBACK_SIGNAL_FRESHNESS_GATE.yaml` defines the non-blocking freshness check for this lane.
