-- V1.9 MetaSurvey Intake Tables
CREATE TABLE IF NOT EXISTS survey_blueprints(
  blueprint_key TEXT PRIMARY KEY,
  description TEXT NOT NULL DEFAULT '',
  spec_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS survey_requests(
  request_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant TEXT NOT NULL,
  blueprint_key TEXT NOT NULL,
  owner TEXT NULL,
  target_name TEXT NULL,
  role_hint TEXT NULL,
  event_id TEXT NULL,
  objective TEXT NOT NULL,
  context_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  status TEXT NOT NULL DEFAULT 'queued',
  deadline_ts TIMESTAMPTZ NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS survey_instances(
  instance_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  request_id UUID NOT NULL REFERENCES survey_requests(request_id),
  provider TEXT NOT NULL DEFAULT 'metasurvey',
  provider_survey_id TEXT NULL,
  public_url TEXT NULL,
  edit_url TEXT NULL,
  hidden_fields_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  status TEXT NOT NULL DEFAULT 'building',
  published_at TIMESTAMPTZ NULL,
  expires_at TIMESTAMPTZ NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS survey_submissions(
  submission_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  instance_id UUID NOT NULL REFERENCES survey_instances(instance_id),
  provider_submission_id TEXT NULL,
  submitted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  raw_payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  normalized_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  score_json JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS intake_insights(
  insight_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant TEXT NOT NULL,
  source_type TEXT NOT NULL,
  source_id TEXT NOT NULL,
  insight_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  confidence NUMERIC(4,3) NOT NULL DEFAULT 0.500,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
