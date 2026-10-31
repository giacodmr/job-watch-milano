-- PR #41: APP-origin facts isolated from immutable imported GitHub data.
-- Explicit APP overrides take precedence, including decision revocation and SAVED removal.
CREATE TABLE personal_app_job_state (
 owner_id TEXT NOT NULL REFERENCES personal_owners(owner_id),
 job_id TEXT NOT NULL CHECK(job_id GLOB 'job:*' AND length(job_id)=68),
 revision INTEGER NOT NULL CHECK(revision>0),
 decision_touched INTEGER NOT NULL CHECK(decision_touched IN (0,1)),
 decision TEXT CHECK(decision IN ('TO_REVIEW','INTERESTED','APPLIED','NOT_INTERESTED')),
 decision_at TEXT,
 decision_reason TEXT CHECK(length(decision_reason)<=360),
 saved_touched INTEGER NOT NULL CHECK(saved_touched IN (0,1)),
 saved_active INTEGER NOT NULL CHECK(saved_active IN (0,1)),
 updated_at TEXT NOT NULL,
 PRIMARY KEY(owner_id,job_id),
 CHECK(decision_touched=1 OR decision IS NULL),
 CHECK(saved_touched=1 OR saved_active=0)
);
-- statement-breakpoint
CREATE TABLE personal_app_events (
 owner_id TEXT NOT NULL, id TEXT NOT NULL, job_id TEXT NOT NULL,
 operation_id TEXT NOT NULL, command TEXT NOT NULL CHECK(command IN ('DECISION','SAVED')),
 action TEXT NOT NULL, previous_value TEXT, next_value TEXT,
 reason TEXT CHECK(length(reason)<=360),
 expected_revision INTEGER NOT NULL CHECK(expected_revision>=0),
 result_revision INTEGER NOT NULL CHECK(result_revision=expected_revision+1),
 occurred_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
 origin TEXT NOT NULL DEFAULT 'APP' CHECK(origin='APP'),
 PRIMARY KEY(owner_id,id),
 UNIQUE(owner_id,operation_id),
 FOREIGN KEY(owner_id,job_id) REFERENCES personal_app_job_state(owner_id,job_id)
);
-- statement-breakpoint
CREATE TABLE personal_app_operations (
 owner_id TEXT NOT NULL REFERENCES personal_owners(owner_id),
 operation_id TEXT NOT NULL,
 job_id TEXT NOT NULL,
 command TEXT NOT NULL CHECK(command IN ('DECISION','SAVED')),
 payload_hash TEXT NOT NULL CHECK(length(payload_hash)=64 AND payload_hash NOT GLOB '*[^0-9a-f]*'),
 event_id TEXT NOT NULL,
 result_json TEXT NOT NULL CHECK(json_valid(result_json)),
 PRIMARY KEY(owner_id,operation_id),
 FOREIGN KEY(owner_id,event_id) REFERENCES personal_app_events(owner_id,id)
);
-- statement-breakpoint
CREATE TABLE personal_app_owner_epochs (
 owner_id TEXT PRIMARY KEY REFERENCES personal_owners(owner_id),
 epoch INTEGER NOT NULL CHECK(epoch>=1)
);
-- statement-breakpoint
-- A failed CAS must ABORT the entire D1.batch, never silently skip its UPDATE.
CREATE TABLE personal_app_cas_guard (valid INTEGER NOT NULL CHECK(valid=1));
-- statement-breakpoint
CREATE TRIGGER personal_app_cas_guard_clear AFTER INSERT ON personal_app_cas_guard
BEGIN DELETE FROM personal_app_cas_guard; END;
-- statement-breakpoint
CREATE TRIGGER personal_app_events_immutable BEFORE UPDATE ON personal_app_events
BEGIN SELECT RAISE(ABORT,'immutable_app_event'); END;
-- statement-breakpoint
CREATE TRIGGER personal_app_events_retain BEFORE DELETE ON personal_app_events
BEGIN SELECT RAISE(ABORT,'immutable_app_event'); END;
-- statement-breakpoint
CREATE TRIGGER personal_app_operations_immutable BEFORE UPDATE ON personal_app_operations
BEGIN SELECT RAISE(ABORT,'immutable_app_operation'); END;
-- statement-breakpoint
CREATE TRIGGER personal_app_operations_retain BEFORE DELETE ON personal_app_operations
BEGIN SELECT RAISE(ABORT,'immutable_app_operation'); END;
-- statement-breakpoint
CREATE TRIGGER personal_app_state_identity BEFORE UPDATE ON personal_app_job_state
WHEN NEW.owner_id!=OLD.owner_id OR NEW.job_id!=OLD.job_id OR NEW.revision!=OLD.revision+1
BEGIN SELECT RAISE(ABORT,'app_revision_conflict'); END;
-- statement-breakpoint
CREATE TRIGGER personal_app_state_retain BEFORE DELETE ON personal_app_job_state
BEGIN SELECT RAISE(ABORT,'permanent_app_state'); END;
-- statement-breakpoint
UPDATE model_c_schema SET version=3 WHERE id=1 AND scope='PERSONAL' AND version=2;
