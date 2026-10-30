-- SQLite requires a table rebuild to allow genuinely unassigned historical batches.
-- Existing migration files remain immutable; all existing observations are copied.
CREATE TABLE job_versions_next (
  job_id TEXT NOT NULL,
  company_id TEXT NOT NULL,
  snapshot_id TEXT NOT NULL REFERENCES sync_snapshots(id),
  source_id TEXT,
  batch TEXT CHECK (batch IN ('jw1','jw2','jw3','jw4')),
  upstream_source_id TEXT NOT NULL,
  title TEXT, location TEXT, canonical_url TEXT, apply_url TEXT, fingerprint TEXT,
  lifecycle TEXT NOT NULL CHECK (lifecycle IN ('NEW','STILL_OPEN','UPDATED','CLOSED','UNKNOWN')),
  first_seen_at TEXT, last_seen_at TEXT,
  source_path TEXT NOT NULL,
  source_sha256 TEXT NOT NULL CHECK (length(source_sha256)=64),
  observed_at TEXT NOT NULL CHECK (length(observed_at)=20 AND substr(observed_at,20)='Z'),
  job_key TEXT,
  sort_key TEXT NOT NULL DEFAULT '',
  analysis_status TEXT, analysis_method TEXT,
  needs_analysis INTEGER CHECK (needs_analysis IN (0,1)),
  worker_eligible INTEGER CHECK (worker_eligible IN (0,1)),
  hard_exclusion_reason TEXT,
  fit_score REAL,
  reportable INTEGER CHECK (reportable IN (0,1)),
  effective_user_decision TEXT CHECK (effective_user_decision IN ('TO_REVIEW','INTERESTED','APPLIED','NOT_INTERESTED')),
  technical_status TEXT,
  PRIMARY KEY (job_id,snapshot_id),
  FOREIGN KEY (job_id,company_id) REFERENCES jobs(id,company_id),
  FOREIGN KEY (source_id,company_id) REFERENCES sources(id,company_id)
);
-- statement-breakpoint
INSERT INTO job_versions_next (job_id,company_id,snapshot_id,source_id,batch,upstream_source_id,title,location,canonical_url,apply_url,fingerprint,lifecycle,first_seen_at,last_seen_at,source_path,source_sha256,observed_at)
SELECT job_id,company_id,snapshot_id,source_id,batch,upstream_source_id,title,location,canonical_url,apply_url,fingerprint,lifecycle,first_seen_at,last_seen_at,source_path,source_sha256,observed_at FROM job_versions;
-- statement-breakpoint
DROP TABLE job_versions;
-- statement-breakpoint
ALTER TABLE job_versions_next RENAME TO job_versions;
-- statement-breakpoint
CREATE INDEX job_versions_filters ON job_versions(snapshot_id,batch,lifecycle,company_id);
-- statement-breakpoint
CREATE INDEX job_versions_source ON job_versions(source_id,snapshot_id);
-- statement-breakpoint
CREATE INDEX job_versions_page ON job_versions(snapshot_id,sort_key,job_id);
-- statement-breakpoint
CREATE INDEX job_versions_assessment ON job_versions(snapshot_id,analysis_method,effective_user_decision);
-- statement-breakpoint
ALTER TABLE source_versions ADD COLUMN generated_at TEXT;
-- statement-breakpoint
ALTER TABLE source_versions ADD COLUMN coverage_source_path TEXT;
-- statement-breakpoint
ALTER TABLE source_versions ADD COLUMN coverage_source_sha256 TEXT;
-- statement-breakpoint
ALTER TABLE sync_snapshots ADD COLUMN expected_revision INTEGER NOT NULL DEFAULT 0 CHECK (expected_revision>=0);
-- statement-breakpoint
ALTER TABLE sync_snapshots ADD COLUMN published_revision INTEGER;
-- statement-breakpoint
ALTER TABLE sync_snapshots ADD COLUMN manifest_json TEXT CHECK (manifest_json IS NULL OR json_valid(manifest_json));
-- statement-breakpoint
CREATE TABLE snapshot_semantic_reviews (
  snapshot_id TEXT NOT NULL REFERENCES sync_snapshots(id),
  review_id TEXT NOT NULL REFERENCES semantic_reviews(id),
  PRIMARY KEY (snapshot_id,review_id)
);
-- statement-breakpoint
CREATE TABLE snapshot_user_decisions (
  snapshot_id TEXT NOT NULL REFERENCES sync_snapshots(id),
  decision_id TEXT NOT NULL REFERENCES user_decisions(id),
  PRIMARY KEY (snapshot_id,decision_id)
);
-- statement-breakpoint
CREATE TABLE sync_assertions (value INTEGER NOT NULL CHECK (value=1));
-- statement-breakpoint
CREATE TRIGGER checkpoint_revision_update BEFORE UPDATE ON sync_checkpoints
WHEN NEW.revision != OLD.revision+1
BEGIN SELECT RAISE(ABORT,'checkpoint_revision_conflict'); END;
-- statement-breakpoint
UPDATE schema_metadata SET version=3 WHERE id=1;
