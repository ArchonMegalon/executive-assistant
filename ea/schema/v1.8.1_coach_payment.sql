-- R1: Coach Event Detection Rules
CREATE TABLE IF NOT EXISTS briefing_links (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_person TEXT NOT NULL,
    target_person TEXT NOT NULL,
    rule_type TEXT NOT NULL,
    config_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(source_person, target_person, rule_type)
);

INSERT INTO briefing_links (source_person, target_person, rule_type, config_json)
VALUES ('elisabeth', 'tibor.girschele', 'coach_event_append', '{"qualifying_keywords": ["coaching", "coach", "mentoring"], "max_items_per_briefing": 2}')
ON CONFLICT DO NOTHING;

-- R2: Person / IV Role Cache
CREATE TABLE IF NOT EXISTS person_profiles (
    person_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant TEXT NOT NULL,
    normalized_name TEXT NOT NULL,
    full_name TEXT NOT NULL,
    organization TEXT NULL,
    role_title TEXT NULL,
    emails_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    aliases_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    source_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    confidence NUMERIC(4,3) NULL,
    last_verified_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(tenant, normalized_name, organization)
);

-- R3: Generated Coach Briefings
CREATE TABLE IF NOT EXISTS coach_briefings (
    coach_briefing_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant TEXT NOT NULL,
    source_person TEXT NOT NULL,
    source_event_id TEXT NOT NULL,
    subject_name TEXT NOT NULL,
    subject_org TEXT NULL,
    subject_role TEXT NULL,
    status TEXT NOT NULL DEFAULT 'drafted',
    content_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    artifact_id UUID NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(source_person, source_event_id)
);
