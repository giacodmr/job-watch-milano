-- M46: isolated service-ingestion STAGING ONLY. No publication path, no
-- modifying existing catalog_head or PERSONAL schema. Strictly additive.
CREATE TABLE catalog_ingest_runs (
  id TEXT PRIMARY KEY NOT NULL CHECK(length(id)=71 AND id LIKE 'ingest:%'),
  commit_sha TEXT NOT NULL CHECK(length(commit_sha)=40),
  manifest_digest TEXT NOT NULL CHECK(length(manifest_digest)=64),
  projection_digest TEXT NOT NULL CHECK(length(projection_digest)=64),
  plan_digest TEXT NOT NULL CHECK(length(plan_digest)=64),
  expected_revision INTEGER NOT NULL CHECK(expected_revision>=0),
  total_chunks INTEGER NOT NULL CHECK(total_chunks BETWEEN 1 AND 64),
  principal_digest TEXT NOT NULL CHECK(length(principal_digest)=64),
  run_digest TEXT NOT NULL CHECK(length(run_digest)=64),
  state TEXT NOT NULL DEFAULT 'RECEIVING' CHECK(state='RECEIVING')
);
-- statement-breakpoint
CREATE TABLE catalog_ingest_chunks (
  run_id TEXT NOT NULL REFERENCES catalog_ingest_runs(id),
  chunk_index INTEGER NOT NULL CHECK(chunk_index BETWEEN 0 AND 63),
  chunk_digest TEXT NOT NULL CHECK(length(chunk_digest)=64),
  idempotency_key TEXT NOT NULL CHECK(length(idempotency_key)=64),
  record_count INTEGER NOT NULL CHECK(record_count BETWEEN 1 AND 16),
  records_json TEXT NOT NULL CHECK(length(records_json) BETWEEN 2 AND 12288),
  PRIMARY KEY(run_id,chunk_index),
  UNIQUE(idempotency_key),
  CHECK(json_valid(records_json))
);
-- statement-breakpoint
CREATE TRIGGER catalog_ingest_run_immutable BEFORE UPDATE ON catalog_ingest_runs
BEGIN SELECT RAISE(ABORT,'immutable_ingest_run'); END;
-- statement-breakpoint
CREATE TRIGGER catalog_ingest_run_retain BEFORE DELETE ON catalog_ingest_runs
BEGIN SELECT RAISE(ABORT,'retained_ingest_run'); END;
-- statement-breakpoint
CREATE TRIGGER catalog_ingest_chunk_immutable BEFORE UPDATE ON catalog_ingest_chunks
BEGIN SELECT RAISE(ABORT,'immutable_ingest_chunk'); END;
-- statement-breakpoint
CREATE TRIGGER catalog_ingest_chunk_retain BEFORE DELETE ON catalog_ingest_chunks
BEGIN SELECT RAISE(ABORT,'retained_ingest_chunk'); END;
-- statement-breakpoint
UPDATE model_c_schema SET version=5 WHERE id=1;
