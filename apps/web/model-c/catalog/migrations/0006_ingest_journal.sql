-- M47: additive durable, append-only transition evidence. M46 wire contract
-- and M46 immutable run/chunk rows remain unchanged.
CREATE TABLE catalog_ingest_journal (
  run_id TEXT NOT NULL,
  sequence INTEGER NOT NULL CHECK(sequence>=0),
  phase TEXT NOT NULL CHECK(phase IN (
    'RECEIVING','COMPLETE','VERIFIED','PERSONAL_PREPARED',
    'CATALOG_PUBLISHED','PERSONAL_RECONCILED','COMPLETED',
    'RECOVERY_REQUIRED','CONFLICT','STALE','UNVERIFIABLE')),
  proof_digest TEXT NOT NULL CHECK(length(proof_digest)=64 AND proof_digest NOT GLOB '*[^0-9a-f]*'),
  previous_digest TEXT NOT NULL CHECK(length(previous_digest)=64 AND previous_digest NOT GLOB '*[^0-9a-f]*'),
  event_digest TEXT NOT NULL CHECK(length(event_digest)=64 AND event_digest NOT GLOB '*[^0-9a-f]*'),
  PRIMARY KEY(run_id,sequence)
);
-- statement-breakpoint
CREATE INDEX catalog_ingest_journal_phase ON catalog_ingest_journal(phase,run_id);
-- statement-breakpoint
INSERT INTO catalog_ingest_journal(run_id,sequence,phase,proof_digest,previous_digest,event_digest)
  SELECT id,0,'RECEIVING',run_digest,
    '0000000000000000000000000000000000000000000000000000000000000000',
    run_digest FROM catalog_ingest_runs;
-- statement-breakpoint
CREATE TRIGGER catalog_ingest_journal_first_guard BEFORE INSERT ON catalog_ingest_journal
WHEN NEW.sequence=0 AND (
  NEW.phase!='RECEIVING' OR
  NEW.previous_digest!='0000000000000000000000000000000000000000000000000000000000000000' OR
  NEW.proof_digest IS NOT (SELECT run_digest FROM catalog_ingest_runs WHERE id=NEW.run_id) OR
  NEW.event_digest IS NOT (SELECT run_digest FROM catalog_ingest_runs WHERE id=NEW.run_id)
)
BEGIN SELECT RAISE(ABORT,'invalid_journal_first_event'); END;
-- statement-breakpoint
CREATE TRIGGER catalog_ingest_journal_guard BEFORE INSERT ON catalog_ingest_journal
WHEN NEW.sequence>0
BEGIN
  SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM catalog_ingest_runs WHERE id=NEW.run_id)
      THEN RAISE(ABORT,'journal_run_missing')
    WHEN NOT EXISTS(SELECT 1 FROM catalog_ingest_journal
      WHERE run_id=NEW.run_id AND sequence=NEW.sequence-1
      AND event_digest=NEW.previous_digest)
      THEN RAISE(ABORT,'journal_chain_conflict')
    WHEN EXISTS(SELECT 1 FROM catalog_ingest_journal
      WHERE run_id=NEW.run_id AND sequence>=NEW.sequence)
      THEN RAISE(ABORT,'journal_sequence_conflict')
    WHEN NOT EXISTS(
      SELECT 1 FROM catalog_ingest_journal j
      WHERE j.run_id=NEW.run_id AND j.sequence=NEW.sequence-1
      AND (
        (j.phase='RECEIVING' AND NEW.phase='COMPLETE') OR
        (j.phase='COMPLETE' AND NEW.phase='VERIFIED') OR
        (j.phase='VERIFIED' AND NEW.phase='PERSONAL_PREPARED') OR
        (j.phase='PERSONAL_PREPARED' AND NEW.phase='CATALOG_PUBLISHED') OR
        (j.phase='CATALOG_PUBLISHED' AND NEW.phase='PERSONAL_RECONCILED') OR
        (j.phase='PERSONAL_RECONCILED' AND NEW.phase='COMPLETED') OR
        (j.phase NOT IN ('COMPLETED','CONFLICT','STALE','UNVERIFIABLE')
         AND NEW.phase IN ('RECOVERY_REQUIRED','CONFLICT','STALE','UNVERIFIABLE'))
      )
    ) THEN RAISE(ABORT,'invalid_journal_transition')
    WHEN NEW.phase='CATALOG_PUBLISHED' AND NOT EXISTS(
      SELECT 1 FROM catalog_head WHERE scope='catalog' AND run_id=NEW.run_id
    ) THEN RAISE(ABORT,'journal_unpublished_catalog')
  END;
END;
-- statement-breakpoint
CREATE TRIGGER catalog_ingest_journal_immutable BEFORE UPDATE ON catalog_ingest_journal
BEGIN SELECT RAISE(ABORT,'immutable_ingest_journal'); END;
-- statement-breakpoint
CREATE TRIGGER catalog_ingest_journal_retain BEFORE DELETE ON catalog_ingest_journal
BEGIN SELECT RAISE(ABORT,'retained_ingest_journal'); END;
-- statement-breakpoint
CREATE TRIGGER catalog_ingest_run_journal_start AFTER INSERT ON catalog_ingest_runs
BEGIN
  INSERT INTO catalog_ingest_journal
    (run_id,sequence,phase,proof_digest,previous_digest,event_digest)
  VALUES(NEW.id,0,'RECEIVING',NEW.run_digest,
    '0000000000000000000000000000000000000000000000000000000000000000',
    NEW.run_digest);
END;
-- statement-breakpoint
UPDATE model_c_schema SET version=6 WHERE id=1 AND version=5;
-- statement-breakpoint
-- M47: immutable compact archival receipts. Payload bytes are not stored here;
-- replay/conflict is decided by original run/chunk binding and digests.
CREATE TABLE catalog_ingest_archive_runs (
  id TEXT PRIMARY KEY NOT NULL,
  commit_sha TEXT NOT NULL, manifest_digest TEXT NOT NULL,
  projection_digest TEXT NOT NULL,plan_digest TEXT NOT NULL,
  expected_revision INTEGER NOT NULL,total_chunks INTEGER NOT NULL,
  principal_digest TEXT NOT NULL,run_digest TEXT NOT NULL,
  archived_at INTEGER NOT NULL DEFAULT (unixepoch())
);
-- statement-breakpoint
CREATE TABLE catalog_ingest_archive_chunks (
  run_id TEXT NOT NULL REFERENCES catalog_ingest_archive_runs(id),
  chunk_index INTEGER NOT NULL,chunk_digest TEXT NOT NULL,
  idempotency_key TEXT NOT NULL UNIQUE,record_count INTEGER NOT NULL,
  PRIMARY KEY(run_id,chunk_index)
);
-- statement-breakpoint
CREATE TRIGGER catalog_ingest_archive_run_guard BEFORE INSERT ON catalog_ingest_archive_runs
WHEN NOT EXISTS (
  SELECT 1 FROM catalog_ingest_runs r WHERE r.id=NEW.id
    AND r.commit_sha=NEW.commit_sha AND r.manifest_digest=NEW.manifest_digest
    AND r.projection_digest=NEW.projection_digest AND r.plan_digest=NEW.plan_digest
    AND r.expected_revision=NEW.expected_revision AND r.total_chunks=NEW.total_chunks
    AND r.principal_digest=NEW.principal_digest AND r.run_digest=NEW.run_digest
    AND EXISTS(SELECT 1 FROM catalog_ingest_journal j
      WHERE j.run_id=r.id AND j.phase='COMPLETED')
    AND NOT EXISTS(SELECT 1 FROM catalog_head h
      WHERE h.scope='catalog' AND h.run_id=r.id)
)
BEGIN SELECT RAISE(ABORT,'archive_run_not_terminal'); END;
-- statement-breakpoint
CREATE TRIGGER catalog_ingest_archive_chunk_guard BEFORE INSERT ON catalog_ingest_archive_chunks
WHEN NOT EXISTS (
 SELECT 1 FROM catalog_ingest_chunks c JOIN catalog_ingest_archive_runs ar
   ON ar.id=c.run_id WHERE c.run_id=NEW.run_id
   AND c.chunk_index=NEW.chunk_index AND c.chunk_digest=NEW.chunk_digest
   AND c.idempotency_key=NEW.idempotency_key AND c.record_count=NEW.record_count
)
BEGIN SELECT RAISE(ABORT,'archive_chunk_unverified'); END;
-- statement-breakpoint
CREATE TRIGGER catalog_ingest_archive_run_immutable BEFORE UPDATE ON catalog_ingest_archive_runs
BEGIN SELECT RAISE(ABORT,'immutable_archive_run'); END;
-- statement-breakpoint
CREATE TRIGGER catalog_ingest_archive_run_retain BEFORE DELETE ON catalog_ingest_archive_runs
BEGIN SELECT RAISE(ABORT,'retained_archive_run'); END;
-- statement-breakpoint
CREATE TRIGGER catalog_ingest_archive_chunk_immutable BEFORE UPDATE ON catalog_ingest_archive_chunks
BEGIN SELECT RAISE(ABORT,'immutable_archive_chunk'); END;
-- statement-breakpoint
CREATE TRIGGER catalog_ingest_archive_chunk_retain BEFORE DELETE ON catalog_ingest_archive_chunks
BEGIN SELECT RAISE(ABORT,'retained_archive_chunk'); END;
-- statement-breakpoint
DROP TRIGGER catalog_ingest_chunk_retain;
-- statement-breakpoint
CREATE TRIGGER catalog_ingest_chunk_retain BEFORE DELETE ON catalog_ingest_chunks
WHEN NOT EXISTS (
 SELECT 1 FROM catalog_ingest_archive_chunks a
 JOIN catalog_ingest_archive_runs ar ON ar.id=a.run_id
 JOIN catalog_ingest_journal j ON j.run_id=a.run_id AND j.phase='COMPLETED'
 WHERE a.run_id=OLD.run_id AND a.chunk_index=OLD.chunk_index
  AND a.chunk_digest=OLD.chunk_digest
  AND a.idempotency_key=OLD.idempotency_key AND a.record_count=OLD.record_count
  AND NOT EXISTS(SELECT 1 FROM catalog_head h WHERE h.scope='catalog' AND h.run_id=a.run_id)
)
BEGIN SELECT RAISE(ABORT,'retained_ingest_chunk'); END;
-- statement-breakpoint
DROP TRIGGER catalog_ingest_run_retain;
-- statement-breakpoint
CREATE TRIGGER catalog_ingest_run_retain BEFORE DELETE ON catalog_ingest_runs
WHEN NOT EXISTS (
 SELECT 1 FROM catalog_ingest_archive_runs a WHERE a.id=OLD.id
  AND a.commit_sha=OLD.commit_sha AND a.manifest_digest=OLD.manifest_digest
  AND a.projection_digest=OLD.projection_digest AND a.plan_digest=OLD.plan_digest
  AND a.expected_revision=OLD.expected_revision AND a.total_chunks=OLD.total_chunks
  AND a.principal_digest=OLD.principal_digest AND a.run_digest=OLD.run_digest
  AND EXISTS(SELECT 1 FROM catalog_ingest_journal j
    WHERE j.run_id=a.id AND j.phase='COMPLETED')
  AND NOT EXISTS(SELECT 1 FROM catalog_ingest_chunks c WHERE c.run_id=a.id)
  AND NOT EXISTS(SELECT 1 FROM catalog_head h WHERE h.scope='catalog' AND h.run_id=a.id)
)
BEGIN SELECT RAISE(ABORT,'retained_ingest_run'); END;
