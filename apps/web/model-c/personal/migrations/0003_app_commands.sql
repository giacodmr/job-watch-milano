-- APP-owned, additive event and projection layer. Imported tables remain untouched.
-- Every table is physically inside PERSONAL D1; never attach to CATALOG.
CREATE TABLE personal_app_jobs (
 owner_id TEXT NOT NULL REFERENCES personal_owners(owner_id),
 job_id TEXT NOT NULL CHECK(job_id GLOB 'job:*' AND length(job_id)=68),
 captured_title TEXT CHECK(captured_title IS NULL OR length(captured_title)<=1000),
 official_url TEXT,
 last_known_lifecycle TEXT CHECK(last_known_lifecycle IN ('NEW','STILL_OPEN','UPDATED','CLOSED','UNKNOWN')),
 captured_commit TEXT NOT NULL CHECK(length(captured_commit)=40),
 captured_path TEXT NOT NULL CHECK(length(captured_path) BETWEEN 1 AND 300),
 captured_sha256 TEXT NOT NULL CHECK(length(captured_sha256)=64),
 PRIMARY KEY(owner_id,job_id)
);
-- statement-breakpoint
CREATE TABLE personal_app_heads (
 owner_id TEXT PRIMARY KEY NOT NULL REFERENCES personal_owners(owner_id),
 revision INTEGER NOT NULL CHECK(revision>=1)
);
-- statement-breakpoint
CREATE TABLE personal_app_events (
 owner_id TEXT NOT NULL,
 event_id TEXT NOT NULL,
 job_id TEXT NOT NULL,
 operation_id TEXT NOT NULL,
 kind TEXT NOT NULL CHECK(kind IN ('DECISION','SAVED')),
 decision TEXT CHECK(decision IN ('TO_REVIEW','INTERESTED','APPLIED','NOT_INTERESTED')),
 saved_active INTEGER CHECK(saved_active IN (0,1)),
 previous_decision TEXT CHECK(previous_decision IN ('TO_REVIEW','INTERESTED','APPLIED','NOT_INTERESTED')),
 previous_saved INTEGER CHECK(previous_saved IN (0,1)),
 reason_summary TEXT CHECK(reason_summary IS NULL OR length(reason_summary)<=360),
 expected_revision INTEGER NOT NULL CHECK(expected_revision>=0),
 revision INTEGER NOT NULL CHECK(revision>0),
 created_at TEXT NOT NULL CHECK(length(created_at)>=20),
 payload_sha256 TEXT NOT NULL CHECK(length(payload_sha256)=64),
 PRIMARY KEY(owner_id,event_id),UNIQUE(owner_id,operation_id),UNIQUE(owner_id,job_id,revision),
 FOREIGN KEY(owner_id,job_id) REFERENCES personal_app_jobs(owner_id,job_id),
 CHECK((kind='DECISION' AND saved_active IS NULL) OR
       (kind='SAVED' AND decision IS NULL AND saved_active IS NOT NULL))
);
-- statement-breakpoint
CREATE TABLE personal_app_current (
 owner_id TEXT NOT NULL,job_id TEXT NOT NULL,revision INTEGER NOT NULL CHECK(revision>0),
 decision_override INTEGER NOT NULL CHECK(decision_override IN (0,1)),
 decision TEXT CHECK(decision IN ('TO_REVIEW','INTERESTED','APPLIED','NOT_INTERESTED')),
 saved_override INTEGER NOT NULL CHECK(saved_override IN (0,1)),
 saved_active INTEGER NOT NULL CHECK(saved_active IN (0,1)),
 updated_at TEXT NOT NULL,
 PRIMARY KEY(owner_id,job_id),
 FOREIGN KEY(owner_id,job_id) REFERENCES personal_app_jobs(owner_id,job_id)
);
-- statement-breakpoint
CREATE TABLE personal_app_operations (
 owner_id TEXT NOT NULL,operation_id TEXT NOT NULL,
 payload_sha256 TEXT NOT NULL CHECK(length(payload_sha256)=64),
 event_id TEXT NOT NULL,job_id TEXT NOT NULL,
 response_json TEXT NOT NULL,
 PRIMARY KEY(owner_id,operation_id),
 FOREIGN KEY(owner_id,event_id) REFERENCES personal_app_events(owner_id,event_id)
);
-- statement-breakpoint
CREATE TABLE personal_app_assert (valid INTEGER NOT NULL CHECK(valid=1));
-- statement-breakpoint
CREATE TRIGGER personal_app_assert_clear AFTER INSERT ON personal_app_assert
 BEGIN DELETE FROM personal_app_assert; END;
-- statement-breakpoint
CREATE TRIGGER personal_app_events_immutable BEFORE UPDATE ON personal_app_events
 BEGIN SELECT RAISE(ABORT,'immutable_app_event'); END;
-- statement-breakpoint
CREATE TRIGGER personal_app_events_retain BEFORE DELETE ON personal_app_events
 BEGIN SELECT RAISE(ABORT,'permanent_app_event'); END;
-- statement-breakpoint
CREATE TRIGGER personal_app_operations_immutable BEFORE UPDATE ON personal_app_operations
 BEGIN SELECT RAISE(ABORT,'immutable_app_operation'); END;
-- statement-breakpoint
CREATE TRIGGER personal_app_operations_retain BEFORE DELETE ON personal_app_operations
 BEGIN SELECT RAISE(ABORT,'permanent_app_operation'); END;
-- statement-breakpoint
CREATE TRIGGER personal_app_jobs_identity BEFORE UPDATE ON personal_app_jobs
 WHEN NEW.owner_id IS NOT OLD.owner_id OR NEW.job_id IS NOT OLD.job_id
 BEGIN SELECT RAISE(ABORT,'immutable_app_identity'); END;
-- statement-breakpoint
CREATE TRIGGER personal_app_jobs_retain BEFORE DELETE ON personal_app_jobs
 BEGIN SELECT RAISE(ABORT,'permanent_app_identity'); END;
-- statement-breakpoint
CREATE TRIGGER personal_app_current_revision BEFORE UPDATE ON personal_app_current
 WHEN NEW.revision!=OLD.revision+1 OR NEW.owner_id IS NOT OLD.owner_id OR NEW.job_id IS NOT OLD.job_id
 BEGIN SELECT RAISE(ABORT,'app_revision_conflict'); END;
-- statement-breakpoint
CREATE TRIGGER personal_app_heads_revision BEFORE UPDATE ON personal_app_heads
 WHEN NEW.revision!=OLD.revision+1 OR NEW.owner_id IS NOT OLD.owner_id
 BEGIN SELECT RAISE(ABORT,'app_revision_conflict'); END;
-- statement-breakpoint
UPDATE model_c_schema SET version=3 WHERE id=1 AND scope='PERSONAL' AND version=2;
