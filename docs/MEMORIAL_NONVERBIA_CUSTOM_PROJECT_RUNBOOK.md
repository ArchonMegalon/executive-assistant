# Memorial Nonverbia Custom Project Runbook

Use this lane after the generic provider check when you want to inspect a specific Nonverbia project instead of the workspace in the abstract.

## Purpose

- log into Nonverbia
- open a named custom project or project URL
- capture the visible project surface
- score whether the project looks like a plausible Manfred video/avatar fit

## Run

```bash
cd /docker/EA
python3 scripts/analyze_nonverbia_custom_project.py \
  --project-name "Manfred Memorial" \
  --project-url "https://app.nonverbia.com/projects/your-project-id" \
  --fit-keyword memorial \
  --fit-keyword avatar \
  --fit-keyword camera
```

Credential resolution order:

- `NONVERBIA_LOGIN_EMAIL` / `NONVERBIA_LOGIN_PASSWORD`
- `/docker/EA/ea/.env`
- `/docker/EA/.env`

## Output

Writes:

```text
/docker/fleet/state/chummer6/avatar_presenter_provider/nonverbia_custom_project_analysis.generated.json
```

Key fields:

- `authenticated_workspace_detected`
- `render_status`
- `ui_failure_code`
- `analysis.project_found`
- `analysis.fit_score`
- `analysis.fit_verdict`

## Verdicts

- `strong_fit`: project tokens matched and avatar/video markers are visible
- `possible_fit`: login succeeded and some relevant markers are visible
- `weak_fit`: login succeeded but the project surface does not strongly support the intended lane
- `blocked`: login or project inspection failed
