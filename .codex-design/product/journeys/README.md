# Journey canon

This directory defines the top end-to-end user journeys and failure-mode flows that multiple repos must preserve.

Each journey answers four questions:

1. What is the user trying to do?
2. What must happen when the happy path works?
3. What must happen when confidence breaks?
4. Which repos own the fix?

Current canonical journeys:

* `build-and-inspect-a-character.md`
* `rejoin-after-disconnect.md`
* `continue-on-a-second-claimed-device.md`
* `install-and-update.md`
* `claim-install-and-close-a-support-case.md`
* `run-a-campaign-and-return.md`
* `organize-a-community-and-close-the-loop.md`
* `publish-a-grounded-artifact.md`
* `recover-from-sync-conflict.md`

Rules:

* Journey files are cross-repo behavior canon, not UI mockups.
* Failure modes must name the visible user outcome, not only operator internals.
* If a repo changes a cross-head journey contract, this directory updates before implementation.
* Journey files stay central until mirror tiering gets narrower than the current broad common bundle.
