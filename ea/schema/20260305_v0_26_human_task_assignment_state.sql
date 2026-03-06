ALTER TABLE human_tasks
ADD COLUMN IF NOT EXISTS assignment_state TEXT NOT NULL DEFAULT 'unassigned';
