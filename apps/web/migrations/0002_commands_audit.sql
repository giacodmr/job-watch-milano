CREATE TABLE commands (
  id TEXT PRIMARY KEY,
  actor_ref TEXT NOT NULL,
  idempotency_key TEXT NOT NULL UNIQUE,
  payload_sha256 TEXT NOT NULL CHECK (length(payload_sha256) = 64),
  type TEXT NOT NULL CHECK (type IN ('user_decision','request_semantic_review')),
  job_id TEXT NOT NULL REFERENCES jobs(id),
  expected_commit_sha TEXT NOT NULL CHECK (length(expected_commit_sha) = 40),
  expected_manifest_sha256 TEXT NOT NULL CHECK (length(expected_manifest_sha256) = 64),
  expected_fingerprint TEXT NOT NULL,
  decision TEXT CHECK (decision IN ('TO_REVIEW','INTERESTED','APPLIED','NOT_INTERESTED')),
  reason_summary TEXT CHECK (length(reason_summary) <= 360),
  rejection_reason TEXT CHECK (rejection_reason IN ('TOO_SENIOR','SALARY_TOO_LOW','WRONG_FUNCTION','WRONG_LOCATION','FIXED_TERM','PURE_SALES','TOO_TECHNICAL','DOMAIN_GAP','OTHER')),
  status TEXT NOT NULL DEFAULT 'QUEUED' CHECK (status IN ('QUEUED','VALIDATED','DISPATCHED','APPLIED','CONFIRMED','RETRY_WAIT','CONFLICT','FAILED','CANCELLED','BLOCKED_UNSUPPORTED')),
  request_id TEXT UNIQUE,
  github_run_id TEXT,
  attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
  next_attempt_at TEXT,
  applied_commit_sha TEXT CHECK (applied_commit_sha IS NULL OR length(applied_commit_sha) = 40),
  receipt_sha256 TEXT CHECK (receipt_sha256 IS NULL OR length(receipt_sha256) = 64),
  confirmation_snapshot_id TEXT REFERENCES sync_snapshots(id),
  error_code TEXT,
  revision INTEGER NOT NULL DEFAULT 1 CHECK (revision > 0),
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  CHECK (type != 'user_decision' OR decision IS NOT NULL),
  CHECK (type != 'request_semantic_review' OR (decision IS NULL AND reason_summary IS NULL AND rejection_reason IS NULL)),
  CHECK (decision IS NOT 'NOT_INTERESTED' OR (reason_summary IS NOT NULL AND length(trim(reason_summary)) > 0 AND rejection_reason IS NOT NULL)),
  CHECK (status NOT IN ('APPLIED','CONFIRMED') OR (applied_commit_sha IS NOT NULL AND receipt_sha256 IS NOT NULL)),
  CHECK (status != 'CONFIRMED' OR confirmation_snapshot_id IS NOT NULL)
);
-- statement-breakpoint
CREATE INDEX commands_queue ON commands(status, next_attempt_at, created_at);
-- statement-breakpoint
CREATE TABLE audit_log (
  id TEXT PRIMARY KEY,
  event_code TEXT NOT NULL,
  actor_ref TEXT NOT NULL,
  entity_type TEXT NOT NULL CHECK (entity_type IN ('command','snapshot','job','access')),
  entity_id TEXT NOT NULL,
  command_id TEXT REFERENCES commands(id),
  snapshot_id TEXT REFERENCES sync_snapshots(id),
  content_sha256 TEXT CHECK (content_sha256 IS NULL OR length(content_sha256) = 64),
  occurred_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
-- statement-breakpoint
CREATE INDEX audit_log_entity ON audit_log(entity_type, entity_id, occurred_at);
-- statement-breakpoint
CREATE TRIGGER audit_no_update BEFORE UPDATE ON audit_log
BEGIN SELECT RAISE(ABORT, 'audit_append_only'); END;
-- statement-breakpoint
CREATE TRIGGER audit_no_delete BEFORE DELETE ON audit_log
BEGIN SELECT RAISE(ABORT, 'audit_append_only'); END;
-- statement-breakpoint
CREATE TRIGGER commands_start_queued BEFORE INSERT ON commands
WHEN NEW.status != 'QUEUED'
BEGIN SELECT RAISE(ABORT, 'command_must_start_queued'); END;
-- statement-breakpoint
CREATE TRIGGER commands_transition BEFORE UPDATE OF status ON commands
WHEN NEW.status != OLD.status AND NOT (
  (OLD.status = 'QUEUED' AND NEW.status IN ('VALIDATED','CONFLICT','FAILED','CANCELLED','BLOCKED_UNSUPPORTED')) OR
  (OLD.status = 'VALIDATED' AND NEW.status IN ('DISPATCHED','RETRY_WAIT','CONFLICT','FAILED','CANCELLED')) OR
  (OLD.status = 'DISPATCHED' AND NEW.status IN ('APPLIED','RETRY_WAIT','CONFLICT','FAILED')) OR
  (OLD.status = 'APPLIED' AND NEW.status IN ('CONFIRMED','CONFLICT','FAILED')) OR
  (OLD.status = 'RETRY_WAIT' AND NEW.status IN ('VALIDATED','CONFLICT','FAILED','CANCELLED')))
BEGIN SELECT RAISE(ABORT, 'invalid_command_transition'); END;
-- statement-breakpoint
CREATE TRIGGER commands_confirm_snapshot BEFORE UPDATE OF status ON commands
WHEN NEW.status = 'CONFIRMED' AND
  (SELECT state FROM sync_snapshots WHERE id = NEW.confirmation_snapshot_id) != 'CONFIRMED'
BEGIN SELECT RAISE(ABORT, 'command_snapshot_not_confirmed'); END;
-- statement-breakpoint
CREATE TRIGGER commands_payload_immutable BEFORE UPDATE ON commands
WHEN NEW.id IS NOT OLD.id OR NEW.actor_ref IS NOT OLD.actor_ref OR
  NEW.idempotency_key IS NOT OLD.idempotency_key OR NEW.payload_sha256 IS NOT OLD.payload_sha256 OR
  NEW.type IS NOT OLD.type OR NEW.job_id IS NOT OLD.job_id OR
  NEW.expected_commit_sha IS NOT OLD.expected_commit_sha OR NEW.expected_manifest_sha256 IS NOT OLD.expected_manifest_sha256 OR
  NEW.expected_fingerprint IS NOT OLD.expected_fingerprint OR NEW.decision IS NOT OLD.decision OR
  NEW.reason_summary IS NOT OLD.reason_summary OR NEW.rejection_reason IS NOT OLD.rejection_reason
BEGIN SELECT RAISE(ABORT, 'command_payload_immutable'); END;
-- statement-breakpoint
UPDATE schema_metadata SET version = 2 WHERE id = 1;
