-- UTC timestamps use YYYY-MM-DDTHH:MM:SSZ. No job-description storage.
-- Complete statements below are separated for the local D1 tests.
CREATE TABLE schema_metadata (id INTEGER PRIMARY KEY CHECK (id = 1), version INTEGER NOT NULL);
-- statement-breakpoint
INSERT INTO schema_metadata VALUES (1, 1);
-- statement-breakpoint
CREATE TABLE sync_snapshots (
  id TEXT PRIMARY KEY,
  repository TEXT NOT NULL CHECK (repository = 'giacodmr/job-watch-milano'),
  commit_sha TEXT NOT NULL CHECK (length(commit_sha) = 40),
  manifest_sha256 TEXT NOT NULL CHECK (length(manifest_sha256) = 64),
  contract_version INTEGER NOT NULL CHECK (contract_version = 1),
  state TEXT NOT NULL DEFAULT 'STAGING' CHECK (state IN ('STAGING','CONFIRMED','FAILED')),
  expected_chunks INTEGER NOT NULL CHECK (expected_chunks > 0),
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  confirmed_at TEXT CHECK (confirmed_at IS NULL OR (length(confirmed_at) = 20 AND substr(confirmed_at,20) = 'Z')),
  UNIQUE (repository, commit_sha, manifest_sha256),
  CHECK ((state = 'CONFIRMED') = (confirmed_at IS NOT NULL))
);
-- statement-breakpoint
CREATE TABLE sync_chunks (
  snapshot_id TEXT NOT NULL REFERENCES sync_snapshots(id),
  chunk_index INTEGER NOT NULL CHECK (chunk_index >= 0),
  content_sha256 TEXT NOT NULL CHECK (length(content_sha256) = 64),
  row_count INTEGER NOT NULL CHECK (row_count >= 0),
  imported_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  PRIMARY KEY (snapshot_id, chunk_index)
);
-- statement-breakpoint
CREATE TABLE companies (
  id TEXT PRIMARY KEY,
  config_id TEXT UNIQUE,
  canonical_name TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
-- statement-breakpoint
CREATE TABLE company_versions (
  company_id TEXT NOT NULL REFERENCES companies(id),
  snapshot_id TEXT NOT NULL REFERENCES sync_snapshots(id),
  tier TEXT,
  monitoring_priority TEXT,
  career_url TEXT,
  membership TEXT NOT NULL CHECK (membership IN ('ACTIVE','CANDIDATE','HISTORICAL')),
  source_path TEXT NOT NULL,
  source_sha256 TEXT NOT NULL CHECK (length(source_sha256) = 64),
  observed_at TEXT NOT NULL CHECK (length(observed_at) = 20 AND substr(observed_at,20) = 'Z'),
  PRIMARY KEY (company_id, snapshot_id)
);
-- statement-breakpoint
CREATE TABLE sources (
  id TEXT PRIMARY KEY,
  company_id TEXT NOT NULL REFERENCES companies(id),
  source_key TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  UNIQUE (company_id, source_key),
  UNIQUE (id, company_id)
);
-- statement-breakpoint
CREATE TABLE source_versions (
  source_id TEXT NOT NULL REFERENCES sources(id),
  snapshot_id TEXT NOT NULL REFERENCES sync_snapshots(id),
  ats_family TEXT,
  inventory_url TEXT,
  coverage TEXT CHECK (coverage IN ('VERIFIED','PARTIAL','FAILED','NOT_CHECKED')),
  source_path TEXT NOT NULL,
  source_sha256 TEXT NOT NULL CHECK (length(source_sha256) = 64),
  observed_at TEXT NOT NULL CHECK (length(observed_at) = 20 AND substr(observed_at,20) = 'Z'),
  PRIMARY KEY (source_id, snapshot_id)
);
-- statement-breakpoint
CREATE TABLE jobs (
  id TEXT PRIMARY KEY,
  company_id TEXT NOT NULL REFERENCES companies(id),
  origin_job_key TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  UNIQUE (id, company_id)
);
-- statement-breakpoint
CREATE TABLE job_aliases (
  alias_key TEXT PRIMARY KEY,
  job_id TEXT NOT NULL REFERENCES jobs(id),
  snapshot_id TEXT NOT NULL REFERENCES sync_snapshots(id),
  resolution TEXT NOT NULL CHECK (resolution IN ('EXACT_KEY','PYTHON_RESOLVED','MANUAL_CONFIRMED')),
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
-- statement-breakpoint
CREATE TABLE job_versions (
  job_id TEXT NOT NULL,
  company_id TEXT NOT NULL,
  snapshot_id TEXT NOT NULL REFERENCES sync_snapshots(id),
  source_id TEXT,
  batch TEXT NOT NULL CHECK (batch IN ('jw1','jw2','jw3','jw4')),
  upstream_source_id TEXT NOT NULL,
  title TEXT,
  location TEXT,
  canonical_url TEXT,
  apply_url TEXT,
  fingerprint TEXT,
  lifecycle TEXT NOT NULL CHECK (lifecycle IN ('NEW','STILL_OPEN','UPDATED','CLOSED','UNKNOWN')),
  first_seen_at TEXT,
  last_seen_at TEXT,
  source_path TEXT NOT NULL,
  source_sha256 TEXT NOT NULL CHECK (length(source_sha256) = 64),
  observed_at TEXT NOT NULL CHECK (length(observed_at) = 20 AND substr(observed_at,20) = 'Z'),
  PRIMARY KEY (job_id, snapshot_id),
  FOREIGN KEY (job_id, company_id) REFERENCES jobs(id, company_id),
  FOREIGN KEY (source_id, company_id) REFERENCES sources(id, company_id)
);
-- statement-breakpoint
CREATE TABLE semantic_reviews (
  id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL REFERENCES jobs(id),
  snapshot_id TEXT NOT NULL REFERENCES sync_snapshots(id),
  fingerprint TEXT NOT NULL,
  analysis_method TEXT NOT NULL CHECK (analysis_method IN ('chatgpt_semantic','chatgpt_semantic_title_metadata','chatgpt_semantic_full_jd','chatgpt_semantic_triage')),
  decision TEXT,
  fit_score REAL,
  reportable INTEGER CHECK (reportable IN (0,1)),
  rationale_summary TEXT CHECK (length(rationale_summary) <= 360),
  evidence_state TEXT NOT NULL CHECK (evidence_state IN ('FULL','HISTORICAL_SHORTENED')),
  analyzed_at TEXT NOT NULL,
  source_path TEXT NOT NULL,
  source_sha256 TEXT NOT NULL CHECK (length(source_sha256) = 64),
  result_sha256 TEXT NOT NULL CHECK (length(result_sha256) = 64),
  UNIQUE (job_id, result_sha256)
);
-- statement-breakpoint
CREATE TABLE user_decisions (
  id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL REFERENCES jobs(id),
  snapshot_id TEXT NOT NULL REFERENCES sync_snapshots(id),
  decision TEXT NOT NULL CHECK (decision IN ('TO_REVIEW','INTERESTED','APPLIED','NOT_INTERESTED')),
  fingerprint TEXT,
  reason_summary TEXT CHECK (length(reason_summary) <= 360),
  rejection_reason TEXT CHECK (rejection_reason IN ('TOO_SENIOR','SALARY_TOO_LOW','WRONG_FUNCTION','WRONG_LOCATION','FIXED_TERM','PURE_SALES','TOO_TECHNICAL','DOMAIN_GAP','OTHER')),
  decided_at TEXT NOT NULL,
  source_path TEXT NOT NULL,
  source_sha256 TEXT NOT NULL CHECK (length(source_sha256) = 64),
  result_sha256 TEXT NOT NULL CHECK (length(result_sha256) = 64),
  UNIQUE (job_id, result_sha256)
);
-- statement-breakpoint
CREATE TABLE pipeline_runs (
  id TEXT PRIMARY KEY,
  snapshot_id TEXT NOT NULL REFERENCES sync_snapshots(id),
  github_run_id TEXT,
  github_run_attempt INTEGER CHECK (github_run_attempt > 0),
  workflow_path TEXT,
  pipeline_run_id TEXT,
  collection_status TEXT,
  health_status TEXT,
  daily_complete INTEGER CHECK (daily_complete IN (0,1)),
  full_semantic_complete INTEGER CHECK (full_semantic_complete IN (0,1)),
  started_at TEXT,
  completed_at TEXT,
  source_path TEXT NOT NULL,
  source_sha256 TEXT NOT NULL CHECK (length(source_sha256) = 64),
  UNIQUE (github_run_id, github_run_attempt, snapshot_id)
);
-- statement-breakpoint
CREATE TABLE sync_checkpoints (
  scope TEXT PRIMARY KEY,
  snapshot_id TEXT NOT NULL REFERENCES sync_snapshots(id),
  revision INTEGER NOT NULL CHECK (revision >= 1),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
-- statement-breakpoint
CREATE INDEX job_versions_filters ON job_versions(snapshot_id, batch, lifecycle, company_id);
-- statement-breakpoint
CREATE INDEX job_versions_source ON job_versions(source_id, snapshot_id);
-- statement-breakpoint
CREATE INDEX semantic_reviews_history ON semantic_reviews(job_id, analyzed_at DESC);
-- statement-breakpoint
CREATE INDEX user_decisions_history ON user_decisions(job_id, decided_at DESC);
-- statement-breakpoint
CREATE INDEX pipeline_runs_snapshot ON pipeline_runs(snapshot_id);
-- statement-breakpoint
CREATE INDEX job_aliases_job ON job_aliases(job_id);
-- statement-breakpoint
CREATE TRIGGER checkpoint_confirmed_insert BEFORE INSERT ON sync_checkpoints
WHEN (SELECT state FROM sync_snapshots WHERE id = NEW.snapshot_id) != 'CONFIRMED'
BEGIN SELECT RAISE(ABORT, 'snapshot_not_confirmed'); END;
-- statement-breakpoint
CREATE TRIGGER checkpoint_confirmed_update BEFORE UPDATE ON sync_checkpoints
WHEN (SELECT state FROM sync_snapshots WHERE id = NEW.snapshot_id) != 'CONFIRMED'
BEGIN SELECT RAISE(ABORT, 'snapshot_not_confirmed'); END;
-- statement-breakpoint
CREATE TRIGGER snapshot_confirm_chunks BEFORE UPDATE OF state ON sync_snapshots
WHEN NEW.state = 'CONFIRMED' AND (
  (SELECT count(*) FROM sync_chunks WHERE snapshot_id = NEW.id) != NEW.expected_chunks OR
  (SELECT min(chunk_index) FROM sync_chunks WHERE snapshot_id = NEW.id) != 0 OR
  (SELECT max(chunk_index) FROM sync_chunks WHERE snapshot_id = NEW.id) != NEW.expected_chunks - 1)
BEGIN SELECT RAISE(ABORT, 'snapshot_chunks_incomplete'); END;
-- statement-breakpoint
CREATE TRIGGER snapshot_starts_staging BEFORE INSERT ON sync_snapshots
WHEN NEW.state != 'STAGING'
BEGIN SELECT RAISE(ABORT, 'snapshot_must_start_staging'); END;
-- statement-breakpoint
CREATE TRIGGER snapshot_terminal BEFORE UPDATE ON sync_snapshots
WHEN OLD.state != 'STAGING'
BEGIN SELECT RAISE(ABORT, 'snapshot_is_terminal'); END;
