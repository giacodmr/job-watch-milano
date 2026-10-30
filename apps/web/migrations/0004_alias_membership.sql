-- Alias membership is versioned too: aliases introduced by an incomplete future
-- import must never leak into a previously confirmed detail view.
CREATE TABLE snapshot_job_aliases (
  snapshot_id TEXT NOT NULL REFERENCES sync_snapshots(id),
  alias_key TEXT NOT NULL REFERENCES job_aliases(alias_key),
  job_id TEXT NOT NULL REFERENCES jobs(id),
  PRIMARY KEY (snapshot_id,alias_key)
);
-- statement-breakpoint
CREATE INDEX snapshot_job_aliases_job ON snapshot_job_aliases(snapshot_id,job_id);
-- statement-breakpoint
UPDATE schema_metadata SET version=4 WHERE id=1;
