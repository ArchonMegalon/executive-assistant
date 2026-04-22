# Feedback Progress Emailit Workflow

Implement the Chummer reporter-progress mail contract from:

- `/docker/chummercomplete/chummer-design/products/chummer/FEEDBACK_PROGRESS_EMAIL_WORKFLOW.yaml`

Required runtime posture:

- queue reporter mail through EA `connector.dispatch`
- send through Emailit
- preserve sent receipts in the EA delivery outbox
- require receipt metadata to carry:
  - `stage_id`
  - `case_id`
  - `recipient`
  - `from_email`
  - `subject`
  - `provider`

Required sender identity:

- from: `Wageslave <wageslave@chummer.run>`
- reply-to: `support@chummer.run`

Required stage sequence:

1. `request_received`
2. `audited_decision`
3. `fix_available`

Decision awards:

- accepted / known-issue / needs-info: `Clad Feedbacker`
- rejected / deferred: `Denied`

Fail closed if:

- sent Emailit receipt is missing
- sender drifts away from `wageslave@chummer.run`
- `audited_decision` omits reason or ETA posture
- `fix_available` omits a release-truth-backed download or update route
