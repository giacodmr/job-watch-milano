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
CREATE TRIGGER catalog_ingest_journal_guard BEFORE INSERT ON catalog_ingest_journal
BEGIN
  SELECT CASE WHEN NEW.sequence=0 THEN RAISE(ABORT,'journal_start_via_run_only')
    WHEN NOT EXISTS(SELECT 1 FROM catalog_ingest_runs WHERE id=NEW.run_id)
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
