-- Inactive Model C schema. Separate physical PERSONAL database only.
-- No v1 migration/binding/reader is changed.
CREATE TABLE model_c_schema (id INTEGER PRIMARY KEY CHECK(id=1), scope TEXT NOT NULL CHECK(scope='PERSONAL'), version INTEGER NOT NULL CHECK(version>=1));
-- statement-breakpoint
INSERT INTO model_c_schema VALUES (1,'PERSONAL',1);
-- statement-breakpoint
CREATE TABLE personal_owners (owner_id TEXT PRIMARY KEY NOT NULL CHECK(length(owner_id) BETWEEN 1 AND 200));
-- statement-breakpoint
CREATE TABLE personal_job_refs (
 owner_id TEXT NOT NULL REFERENCES personal_owners(owner_id), job_id TEXT NOT NULL CHECK(length(job_id)>0),
 captured_title TEXT CHECK(length(captured_title)<=1000), official_url TEXT,
 last_known_lifecycle TEXT CHECK(last_known_lifecycle IN ('NEW','STILL_OPEN','UPDATED','CLOSED','UNKNOWN')),
 captured_commit TEXT NOT NULL CHECK(length(captured_commit)=40 AND captured_commit NOT GLOB '*[^0-9a-f]*'), captured_path TEXT NOT NULL CHECK(length(captured_path) BETWEEN 1 AND 300),
 captured_sha256 TEXT NOT NULL CHECK(length(captured_sha256)=64 AND captured_sha256 NOT GLOB '*[^0-9a-f]*'), revision INTEGER NOT NULL CHECK(revision>0),
 PRIMARY KEY(owner_id,job_id)
);
-- statement-breakpoint
CREATE TABLE personal_reference_state (
 owner_id TEXT NOT NULL, job_id TEXT NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('SAVED','APPLICATION','DISMISSED')),
 active INTEGER NOT NULL CHECK(active IN (0,1)), revision INTEGER NOT NULL CHECK(revision>0),
 PRIMARY KEY(owner_id,job_id,kind), FOREIGN KEY(owner_id,job_id) REFERENCES personal_job_refs(owner_id,job_id)
);
-- statement-breakpoint
CREATE TABLE personal_decision_events (
 owner_id TEXT NOT NULL, id TEXT NOT NULL, job_id TEXT NOT NULL,
 decision TEXT NOT NULL CHECK(decision IN ('TO_REVIEW','INTERESTED','APPLIED','NOT_INTERESTED')),
 rejection_reason TEXT CHECK(rejection_reason IN ('TOO_SENIOR','SALARY_TOO_LOW','WRONG_FUNCTION','WRONG_LOCATION','FIXED_TERM','PURE_SALES','TOO_TECHNICAL','DOMAIN_GAP','OTHER')),
 reason_summary TEXT CHECK(length(reason_summary)<=360), fingerprint TEXT, decided_at TEXT NOT NULL, result_sha256 TEXT NOT NULL CHECK(length(result_sha256)=64 AND result_sha256 NOT GLOB '*[^0-9a-f]*'),
 source_commit TEXT NOT NULL CHECK(length(source_commit)=40 AND source_commit NOT GLOB '*[^0-9a-f]*'), source_path TEXT NOT NULL CHECK(length(source_path) BETWEEN 1 AND 300),
 source_sha256 TEXT NOT NULL CHECK(length(source_sha256)=64 AND source_sha256 NOT GLOB '*[^0-9a-f]*'),
 PRIMARY KEY(owner_id,id), UNIQUE(owner_id,job_id,result_sha256), UNIQUE(owner_id,job_id,id),
 FOREIGN KEY(owner_id,job_id) REFERENCES personal_job_refs(owner_id,job_id)
);
-- statement-breakpoint
CREATE TABLE personal_decision_current (
 owner_id TEXT NOT NULL, job_id TEXT NOT NULL, event_id TEXT NOT NULL, revision INTEGER NOT NULL CHECK(revision>0),
 PRIMARY KEY(owner_id,job_id), FOREIGN KEY(owner_id,job_id,event_id) REFERENCES personal_decision_events(owner_id,job_id,id)
);
-- statement-breakpoint
CREATE TABLE personal_assessment_events (
 owner_id TEXT NOT NULL REFERENCES personal_owners(owner_id), id TEXT NOT NULL, job_id TEXT NOT NULL,
 fingerprint TEXT NOT NULL, method TEXT NOT NULL CHECK(method IN ('chatgpt_semantic','chatgpt_semantic_title_metadata','chatgpt_semantic_full_jd','chatgpt_semantic_triage')),
 decision TEXT CHECK(length(decision)<=1000), fit_score REAL, reportable INTEGER CHECK(reportable IN (0,1)), summary TEXT CHECK(length(summary)<=360),
 evidence_state TEXT NOT NULL CHECK(evidence_state IN ('FULL','HISTORICAL_SHORTENED')), analyzed_at TEXT NOT NULL,
 result_sha256 TEXT NOT NULL CHECK(length(result_sha256)=64 AND result_sha256 NOT GLOB '*[^0-9a-f]*'),
 source_commit TEXT NOT NULL CHECK(length(source_commit)=40 AND source_commit NOT GLOB '*[^0-9a-f]*'), source_path TEXT NOT NULL CHECK(length(source_path) BETWEEN 1 AND 300),
 source_sha256 TEXT NOT NULL CHECK(length(source_sha256)=64 AND source_sha256 NOT GLOB '*[^0-9a-f]*'),
 PRIMARY KEY(owner_id,id), UNIQUE(owner_id,job_id,result_sha256), UNIQUE(owner_id,job_id,id)
);
-- statement-breakpoint
CREATE TABLE personal_assessment_current (
 owner_id TEXT NOT NULL, job_id TEXT NOT NULL, event_id TEXT NOT NULL, revision INTEGER NOT NULL CHECK(revision>0),
 PRIMARY KEY(owner_id,job_id), FOREIGN KEY(owner_id,job_id,event_id) REFERENCES personal_assessment_events(owner_id,job_id,id)
);
-- statement-breakpoint
CREATE TABLE personal_heads (
 owner_id TEXT PRIMARY KEY NOT NULL REFERENCES personal_owners(owner_id), revision INTEGER NOT NULL CHECK(revision>0),
 context_digest TEXT NOT NULL CHECK(length(context_digest)=64 AND context_digest NOT GLOB '*[^0-9a-f]*'), source_commit TEXT CHECK(source_commit IS NULL OR (length(source_commit)=40 AND source_commit NOT GLOB '*[^0-9a-f]*'))
);
-- statement-breakpoint
CREATE TABLE personal_catalog_receipts (
 id TEXT PRIMARY KEY NOT NULL, catalog_sync_revision INTEGER NOT NULL CHECK(catalog_sync_revision>0),
 catalog_content_revision INTEGER NOT NULL CHECK(catalog_content_revision>0), observed_commit TEXT NOT NULL CHECK(length(observed_commit)=40 AND observed_commit NOT GLOB '*[^0-9a-f]*'),
 ledger_digest TEXT NOT NULL CHECK(length(ledger_digest)=64 AND ledger_digest NOT GLOB '*[^0-9a-f]*'), head_digest TEXT NOT NULL CHECK(length(head_digest)=64 AND head_digest NOT GLOB '*[^0-9a-f]*')
);
-- statement-breakpoint
CREATE TABLE personal_reconciliation (
 owner_id TEXT NOT NULL, job_id TEXT NOT NULL, personal_revision INTEGER NOT NULL CHECK(personal_revision>0),
 state TEXT NOT NULL CHECK(state IN ('PENDING','VERIFIED','CONFLICT')), receipt_id TEXT REFERENCES personal_catalog_receipts(id),
 error_code TEXT CHECK(length(error_code)<=80), PRIMARY KEY(owner_id,job_id),
 FOREIGN KEY(owner_id,job_id) REFERENCES personal_job_refs(owner_id,job_id),
 CHECK(state!='VERIFIED' OR receipt_id IS NOT NULL), CHECK(state!='PENDING' OR receipt_id IS NULL)
);
-- statement-breakpoint
CREATE TABLE personal_audit (
 id TEXT PRIMARY KEY NOT NULL, owner_id TEXT NOT NULL REFERENCES personal_owners(owner_id),
 event_code TEXT NOT NULL CHECK(length(event_code) BETWEEN 1 AND 80), content_digest TEXT CHECK(content_digest IS NULL OR (length(content_digest)=64 AND content_digest NOT GLOB '*[^0-9a-f]*'))
);
-- statement-breakpoint
CREATE TRIGGER personal_owners_immutable BEFORE UPDATE ON personal_owners
BEGIN SELECT RAISE(ABORT,'immutable_identity_or_event'); END;
-- statement-breakpoint
CREATE TRIGGER personal_owners_retain BEFORE DELETE ON personal_owners
BEGIN SELECT RAISE(ABORT,'permanent_identity_or_event'); END;
-- statement-breakpoint
CREATE TRIGGER personal_decision_events_immutable BEFORE UPDATE ON personal_decision_events
BEGIN SELECT RAISE(ABORT,'immutable_identity_or_event'); END;
-- statement-breakpoint
CREATE TRIGGER personal_decision_events_retain BEFORE DELETE ON personal_decision_events
BEGIN SELECT RAISE(ABORT,'permanent_identity_or_event'); END;
-- statement-breakpoint
CREATE TRIGGER personal_assessment_events_immutable BEFORE UPDATE ON personal_assessment_events
BEGIN SELECT RAISE(ABORT,'immutable_identity_or_event'); END;
-- statement-breakpoint
CREATE TRIGGER personal_assessment_events_retain BEFORE DELETE ON personal_assessment_events
BEGIN SELECT RAISE(ABORT,'permanent_identity_or_event'); END;
-- statement-breakpoint
CREATE TRIGGER personal_catalog_receipts_immutable BEFORE UPDATE ON personal_catalog_receipts
BEGIN SELECT RAISE(ABORT,'immutable_identity_or_event'); END;
-- statement-breakpoint
CREATE TRIGGER personal_catalog_receipts_retain BEFORE DELETE ON personal_catalog_receipts
BEGIN SELECT RAISE(ABORT,'permanent_identity_or_event'); END;
-- statement-breakpoint
CREATE TRIGGER personal_audit_immutable BEFORE UPDATE ON personal_audit
BEGIN SELECT RAISE(ABORT,'immutable_identity_or_event'); END;
-- statement-breakpoint
CREATE TRIGGER personal_audit_retain BEFORE DELETE ON personal_audit
BEGIN SELECT RAISE(ABORT,'permanent_identity_or_event'); END;
-- statement-breakpoint
CREATE TRIGGER personal_job_refs_immutable BEFORE UPDATE ON personal_job_refs WHEN NEW.owner_id IS NOT OLD.owner_id OR NEW.job_id IS NOT OLD.job_id
BEGIN SELECT RAISE(ABORT,'immutable_identity_or_event'); END;
-- statement-breakpoint
CREATE TRIGGER personal_job_refs_retain BEFORE DELETE ON personal_job_refs
BEGIN SELECT RAISE(ABORT,'permanent_identity_or_event'); END;
-- statement-breakpoint
CREATE TRIGGER personal_job_refs_revision BEFORE UPDATE ON personal_job_refs WHEN NEW.revision!=OLD.revision+1
BEGIN SELECT RAISE(ABORT,'personal_revision_conflict'); END;
-- statement-breakpoint
CREATE TRIGGER personal_reference_state_immutable BEFORE UPDATE ON personal_reference_state WHEN NEW.owner_id IS NOT OLD.owner_id OR NEW.job_id IS NOT OLD.job_id OR NEW.kind IS NOT OLD.kind
BEGIN SELECT RAISE(ABORT,'immutable_identity_or_event'); END;
-- statement-breakpoint
CREATE TRIGGER personal_reference_state_retain BEFORE DELETE ON personal_reference_state
BEGIN SELECT RAISE(ABORT,'permanent_identity_or_event'); END;
-- statement-breakpoint
CREATE TRIGGER personal_reference_state_revision BEFORE UPDATE ON personal_reference_state WHEN NEW.revision!=OLD.revision+1
BEGIN SELECT RAISE(ABORT,'personal_revision_conflict'); END;
-- statement-breakpoint
CREATE TRIGGER personal_decision_current_immutable BEFORE UPDATE ON personal_decision_current WHEN NEW.owner_id IS NOT OLD.owner_id OR NEW.job_id IS NOT OLD.job_id
BEGIN SELECT RAISE(ABORT,'immutable_identity_or_event'); END;
-- statement-breakpoint
CREATE TRIGGER personal_decision_current_retain BEFORE DELETE ON personal_decision_current
BEGIN SELECT RAISE(ABORT,'permanent_identity_or_event'); END;
-- statement-breakpoint
CREATE TRIGGER personal_decision_current_revision BEFORE UPDATE ON personal_decision_current WHEN NEW.revision!=OLD.revision+1
BEGIN SELECT RAISE(ABORT,'personal_revision_conflict'); END;
-- statement-breakpoint
CREATE TRIGGER personal_assessment_current_immutable BEFORE UPDATE ON personal_assessment_current WHEN NEW.owner_id IS NOT OLD.owner_id OR NEW.job_id IS NOT OLD.job_id
BEGIN SELECT RAISE(ABORT,'immutable_identity_or_event'); END;
-- statement-breakpoint
CREATE TRIGGER personal_assessment_current_retain BEFORE DELETE ON personal_assessment_current
BEGIN SELECT RAISE(ABORT,'permanent_identity_or_event'); END;
-- statement-breakpoint
CREATE TRIGGER personal_assessment_current_revision BEFORE UPDATE ON personal_assessment_current WHEN NEW.revision!=OLD.revision+1
BEGIN SELECT RAISE(ABORT,'personal_revision_conflict'); END;
-- statement-breakpoint
CREATE TRIGGER personal_heads_immutable BEFORE UPDATE ON personal_heads WHEN NEW.owner_id IS NOT OLD.owner_id
BEGIN SELECT RAISE(ABORT,'immutable_identity_or_event'); END;
-- statement-breakpoint
CREATE TRIGGER personal_heads_retain BEFORE DELETE ON personal_heads
BEGIN SELECT RAISE(ABORT,'permanent_identity_or_event'); END;
-- statement-breakpoint
CREATE TRIGGER personal_heads_revision BEFORE UPDATE ON personal_heads WHEN NEW.revision!=OLD.revision+1
BEGIN SELECT RAISE(ABORT,'personal_revision_conflict'); END;
-- statement-breakpoint
CREATE TRIGGER personal_reconciliation_insert_fresh BEFORE INSERT ON personal_reconciliation WHEN NEW.state='VERIFIED' AND NOT EXISTS(SELECT 1 FROM personal_heads WHERE owner_id=NEW.owner_id AND revision=NEW.personal_revision) BEGIN SELECT RAISE(ABORT,'stale_personal_context'); END;
-- statement-breakpoint
CREATE TRIGGER personal_reconciliation_update_fresh BEFORE UPDATE ON personal_reconciliation WHEN NEW.state='VERIFIED' AND NOT EXISTS(SELECT 1 FROM personal_heads WHERE owner_id=NEW.owner_id AND revision=NEW.personal_revision) BEGIN SELECT RAISE(ABORT,'stale_personal_context'); END;
-- statement-breakpoint
CREATE VIEW personal_verified_reconciliation AS SELECT r.* FROM personal_reconciliation r JOIN personal_heads h ON h.owner_id=r.owner_id AND h.revision=r.personal_revision WHERE r.state='VERIFIED';
