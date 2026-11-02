-- Additive CATALOG v7 sidecar: initial bootstrap receipts for a durable
-- one-run, multi-day materialization. Does NOT change v7 readers or activate
-- a remote publisher. The separate Gate B must migrate the remote pilot.
CREATE TABLE catalog_prepared_chunks (
 run_id TEXT NOT NULL REFERENCES catalog_runs(id),
 chunk_index INTEGER NOT NULL CHECK(chunk_index>=0),
 chunk_digest TEXT NOT NULL CHECK(length(chunk_digest)=64 AND chunk_digest NOT GLOB '*[^0-9a-f]*'),
 rows_bound INTEGER NOT NULL CHECK(rows_bound BETWEEN 1 AND 30000),
 PRIMARY KEY(run_id,chunk_index)
);
-- statement-breakpoint
CREATE TRIGGER catalog_prepared_chunk_immutable BEFORE UPDATE ON catalog_prepared_chunks
BEGIN SELECT RAISE(ABORT,'immutable_prepared_chunk'); END;
-- statement-breakpoint
CREATE TRIGGER catalog_prepared_chunk_retain BEFORE DELETE ON catalog_prepared_chunks
BEGIN SELECT RAISE(ABORT,'retained_prepared_chunk'); END;
-- statement-breakpoint
-- Intentionally keep model_c_schema.version=7: this adds isolated preparation
-- metadata only; v2 service contracts and all read schemas are unchanged.
