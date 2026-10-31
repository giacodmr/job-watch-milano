-- M47: isolated v2 full-inventory staging. v1 tables/contract are untouched.
CREATE TABLE catalog_ingest_v2_runs (
 id TEXT PRIMARY KEY NOT NULL CHECK(length(id)=74 AND id GLOB 'ingest-v2:*'),
 commit_sha TEXT NOT NULL CHECK(length(commit_sha)=40),
 manifest_digest TEXT NOT NULL CHECK(length(manifest_digest)=64),
 projection_digest TEXT NOT NULL CHECK(length(projection_digest)=64),
 ledger_digest TEXT NOT NULL CHECK(length(ledger_digest)=64),
 catalog_content_digest TEXT NOT NULL CHECK(length(catalog_content_digest)=64),
 plan_digest TEXT NOT NULL CHECK(length(plan_digest)=64),
 expected_revision INTEGER NOT NULL CHECK(expected_revision>=0),
 total_chunks INTEGER NOT NULL CHECK(total_chunks BETWEEN 1 AND 100000),
 record_count INTEGER NOT NULL CHECK(record_count>0),
 inventory_digest TEXT NOT NULL CHECK(length(inventory_digest)=64),
 principal_digest TEXT NOT NULL CHECK(length(principal_digest)=64),
 run_digest TEXT NOT NULL CHECK(length(run_digest)=64),
 state TEXT NOT NULL DEFAULT 'RECEIVING' CHECK(state='RECEIVING')
);
-- statement-breakpoint
CREATE TABLE catalog_ingest_v2_chunks (
 run_id TEXT NOT NULL REFERENCES catalog_ingest_v2_runs(id),
 chunk_index INTEGER NOT NULL CHECK(chunk_index>=0),
 chunk_digest TEXT NOT NULL CHECK(length(chunk_digest)=64),
 idempotency_key TEXT NOT NULL UNIQUE CHECK(length(idempotency_key)=64),
 record_count INTEGER NOT NULL CHECK(record_count BETWEEN 1 AND 40),
 records_json TEXT NOT NULL CHECK(length(records_json) BETWEEN 2 AND 49152 AND json_valid(records_json)),
 PRIMARY KEY(run_id,chunk_index)
);
-- statement-breakpoint
CREATE TABLE catalog_ingest_v2_archive_runs (
 id TEXT PRIMARY KEY NOT NULL,
 commit_sha TEXT NOT NULL,manifest_digest TEXT NOT NULL,projection_digest TEXT NOT NULL,
 ledger_digest TEXT NOT NULL,catalog_content_digest TEXT NOT NULL,plan_digest TEXT NOT NULL,
 expected_revision INTEGER NOT NULL,total_chunks INTEGER NOT NULL,record_count INTEGER NOT NULL,
 inventory_digest TEXT NOT NULL,principal_digest TEXT NOT NULL,run_digest TEXT NOT NULL,
 archived_at INTEGER NOT NULL DEFAULT (unixepoch())
);
-- statement-breakpoint
CREATE TABLE catalog_ingest_v2_archive_chunks (
 run_id TEXT NOT NULL REFERENCES catalog_ingest_v2_archive_runs(id),
 chunk_index INTEGER NOT NULL,chunk_digest TEXT NOT NULL,idempotency_key TEXT NOT NULL UNIQUE,
 record_count INTEGER NOT NULL,PRIMARY KEY(run_id,chunk_index)
);
-- statement-breakpoint
CREATE TRIGGER catalog_ingest_v2_run_immutable BEFORE UPDATE ON catalog_ingest_v2_runs
 BEGIN SELECT RAISE(ABORT,'immutable_v2_run'); END;
-- statement-breakpoint
CREATE TRIGGER catalog_ingest_v2_chunk_immutable BEFORE UPDATE ON catalog_ingest_v2_chunks
 BEGIN SELECT RAISE(ABORT,'immutable_v2_chunk'); END;
-- statement-breakpoint
CREATE TRIGGER catalog_ingest_v2_archive_run_immutable BEFORE UPDATE ON catalog_ingest_v2_archive_runs
 BEGIN SELECT RAISE(ABORT,'immutable_v2_archive'); END;
-- statement-breakpoint
CREATE TRIGGER catalog_ingest_v2_archive_chunk_immutable BEFORE UPDATE ON catalog_ingest_v2_archive_chunks
 BEGIN SELECT RAISE(ABORT,'immutable_v2_archive_chunk'); END;
-- statement-breakpoint
CREATE TRIGGER catalog_ingest_v2_archive_run_retain BEFORE DELETE ON catalog_ingest_v2_archive_runs
 BEGIN SELECT RAISE(ABORT,'retained_v2_archive'); END;
-- statement-breakpoint
CREATE TRIGGER catalog_ingest_v2_archive_chunk_retain BEFORE DELETE ON catalog_ingest_v2_archive_chunks
 BEGIN SELECT RAISE(ABORT,'retained_v2_archive_chunk'); END;
-- statement-breakpoint
CREATE TRIGGER catalog_ingest_v2_archive_guard BEFORE INSERT ON catalog_ingest_v2_archive_runs
 WHEN NOT EXISTS (
  SELECT 1 FROM catalog_ingest_v2_runs r
  JOIN catalog_runs p ON p.id=r.id AND p.state='PUBLISHED'
  JOIN catalog_run_proofs pr ON pr.run_id=p.id
  JOIN catalog_ingest_journal j ON j.run_id=r.id AND j.phase='COMPLETED'
  WHERE r.id=NEW.id AND r.run_digest=NEW.run_digest AND r.principal_digest=NEW.principal_digest
   AND r.inventory_digest=NEW.inventory_digest AND r.record_count=NEW.record_count
   AND r.total_chunks=NEW.total_chunks AND r.expected_revision=NEW.expected_revision
   AND r.commit_sha=NEW.commit_sha AND r.manifest_digest=NEW.manifest_digest
   AND r.projection_digest=NEW.projection_digest AND r.ledger_digest=NEW.ledger_digest
   AND r.catalog_content_digest=NEW.catalog_content_digest AND r.plan_digest=NEW.plan_digest
   AND p.observed_commit=r.commit_sha AND p.projection_digest=r.projection_digest
   AND p.expected_revision=r.expected_revision AND pr.manifest_digest=r.manifest_digest
   AND NOT EXISTS (SELECT 1 FROM catalog_head h WHERE h.scope='catalog' AND h.run_id=r.id)
 ) BEGIN SELECT RAISE(ABORT,'v2_archive_not_terminal'); END;
-- statement-breakpoint
CREATE TRIGGER catalog_ingest_v2_archive_chunk_guard BEFORE INSERT ON catalog_ingest_v2_archive_chunks
 WHEN NOT EXISTS (
  SELECT 1 FROM catalog_ingest_v2_chunks c JOIN catalog_ingest_v2_archive_runs r ON r.id=c.run_id
  WHERE c.run_id=NEW.run_id AND c.chunk_index=NEW.chunk_index AND c.chunk_digest=NEW.chunk_digest
    AND c.idempotency_key=NEW.idempotency_key AND c.record_count=NEW.record_count
 ) BEGIN SELECT RAISE(ABORT,'v2_archive_chunk_unverified'); END;
-- statement-breakpoint
CREATE TRIGGER catalog_ingest_v2_chunk_retain BEFORE DELETE ON catalog_ingest_v2_chunks
 WHEN NOT EXISTS (
  SELECT 1 FROM catalog_ingest_v2_archive_chunks a
  JOIN catalog_ingest_v2_archive_runs r ON r.id=a.run_id
  JOIN catalog_ingest_journal j ON j.run_id=a.run_id AND j.phase='COMPLETED'
  WHERE a.run_id=OLD.run_id AND a.chunk_index=OLD.chunk_index
   AND a.chunk_digest=OLD.chunk_digest AND a.idempotency_key=OLD.idempotency_key
   AND a.record_count=OLD.record_count
   AND NOT EXISTS(SELECT 1 FROM catalog_head h WHERE h.scope='catalog' AND h.run_id=OLD.run_id)
 ) BEGIN SELECT RAISE(ABORT,'retained_v2_chunk'); END;
-- statement-breakpoint
CREATE TRIGGER catalog_ingest_v2_run_retain BEFORE DELETE ON catalog_ingest_v2_runs
 WHEN NOT EXISTS (
  SELECT 1 FROM catalog_ingest_v2_archive_runs a WHERE a.id=OLD.id
   AND a.run_digest=OLD.run_digest AND a.principal_digest=OLD.principal_digest
   AND a.inventory_digest=OLD.inventory_digest AND a.total_chunks=OLD.total_chunks
   AND a.record_count=OLD.record_count AND a.commit_sha=OLD.commit_sha
   AND a.manifest_digest=OLD.manifest_digest AND a.projection_digest=OLD.projection_digest
   AND a.ledger_digest=OLD.ledger_digest AND a.catalog_content_digest=OLD.catalog_content_digest
   AND a.plan_digest=OLD.plan_digest AND a.expected_revision=OLD.expected_revision
   AND NOT EXISTS(SELECT 1 FROM catalog_ingest_v2_chunks c WHERE c.run_id=OLD.id)
   AND NOT EXISTS(SELECT 1 FROM catalog_head h WHERE h.scope='catalog' AND h.run_id=OLD.id)
 ) BEGIN SELECT RAISE(ABORT,'retained_v2_run'); END;
-- statement-breakpoint
DROP TRIGGER catalog_ingest_journal_first_guard;
-- statement-breakpoint
CREATE TRIGGER catalog_ingest_journal_first_guard BEFORE INSERT ON catalog_ingest_journal
 WHEN NEW.sequence=0 AND (
  NEW.phase!='RECEIVING' OR
  NEW.previous_digest!='0000000000000000000000000000000000000000000000000000000000000000' OR
  NEW.proof_digest IS NOT coalesce(
   (SELECT run_digest FROM catalog_ingest_runs WHERE id=NEW.run_id),
   (SELECT run_digest FROM catalog_ingest_v2_runs WHERE id=NEW.run_id)) OR
  NEW.event_digest!=NEW.proof_digest
 ) BEGIN SELECT RAISE(ABORT,'invalid_journal_first_event'); END;
-- statement-breakpoint
DROP TRIGGER catalog_ingest_journal_guard;
-- statement-breakpoint
CREATE TRIGGER catalog_ingest_journal_guard BEFORE INSERT ON catalog_ingest_journal
 WHEN NEW.sequence>0 BEGIN
 SELECT CASE
  WHEN NOT EXISTS(SELECT 1 FROM catalog_ingest_runs WHERE id=NEW.run_id)
   AND NOT EXISTS(SELECT 1 FROM catalog_ingest_v2_runs WHERE id=NEW.run_id)
   THEN RAISE(ABORT,'journal_run_missing')
  WHEN NOT EXISTS(SELECT 1 FROM catalog_ingest_journal
    WHERE run_id=NEW.run_id AND sequence=NEW.sequence-1 AND event_digest=NEW.previous_digest)
   THEN RAISE(ABORT,'journal_chain_conflict')
  WHEN EXISTS(SELECT 1 FROM catalog_ingest_journal
    WHERE run_id=NEW.run_id AND sequence>=NEW.sequence)
   THEN RAISE(ABORT,'journal_sequence_conflict')
  WHEN NOT EXISTS(SELECT 1 FROM catalog_ingest_journal j
    WHERE j.run_id=NEW.run_id AND j.sequence=NEW.sequence-1 AND (
     (j.phase='RECEIVING' AND NEW.phase='COMPLETE') OR
     (j.phase='COMPLETE' AND NEW.phase='VERIFIED') OR
     (j.phase='VERIFIED' AND NEW.phase='PERSONAL_PREPARED') OR
     (j.phase='PERSONAL_PREPARED' AND NEW.phase='CATALOG_PUBLISHED') OR
     (j.phase='CATALOG_PUBLISHED' AND NEW.phase='PERSONAL_RECONCILED') OR
     (j.phase='PERSONAL_RECONCILED' AND NEW.phase='COMPLETED') OR
     (j.phase NOT IN ('COMPLETED','CONFLICT','STALE','UNVERIFIABLE')
       AND NEW.phase IN ('RECOVERY_REQUIRED','CONFLICT','STALE','UNVERIFIABLE'))
   )) THEN RAISE(ABORT,'invalid_journal_transition')
  WHEN NEW.phase='CATALOG_PUBLISHED' AND NOT EXISTS(
   SELECT 1 FROM catalog_head WHERE scope='catalog' AND run_id=NEW.run_id
  ) THEN RAISE(ABORT,'journal_unpublished_catalog')
 END; END;
-- statement-breakpoint
CREATE TRIGGER catalog_ingest_v2_journal_start AFTER INSERT ON catalog_ingest_v2_runs
 BEGIN INSERT INTO catalog_ingest_journal
 (run_id,sequence,phase,proof_digest,previous_digest,event_digest)
 VALUES(NEW.id,0,'RECEIVING',NEW.run_digest,
 '0000000000000000000000000000000000000000000000000000000000000000',NEW.run_digest); END;
-- statement-breakpoint
UPDATE model_c_schema SET version=7 WHERE scope='CATALOG' AND version=6;
