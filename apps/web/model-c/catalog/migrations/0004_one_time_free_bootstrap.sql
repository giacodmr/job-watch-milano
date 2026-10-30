-- Preserve the ordinary <=60k tables and every historical reservation. The only
-- additional allowance is an explicitly requested initial free bootstrap.
CREATE TABLE catalog_initial_bootstrap_reservations (
 id TEXT PRIMARY KEY NOT NULL,
 day TEXT NOT NULL REFERENCES catalog_write_days(day),
 rows_bound INTEGER NOT NULL CHECK(rows_bound BETWEEN 1 AND 95000),
 ceiling INTEGER NOT NULL CHECK(ceiling BETWEEN 1 AND 95000),
 observed_commit TEXT NOT NULL CHECK(length(observed_commit)=40 AND observed_commit NOT GLOB '*[^0-9a-f]*'),
 manifest_digest TEXT NOT NULL CHECK(length(manifest_digest)=64 AND manifest_digest NOT GLOB '*[^0-9a-f]*'),
 projection_digest TEXT NOT NULL CHECK(length(projection_digest)=64 AND projection_digest NOT GLOB '*[^0-9a-f]*')
);
-- statement-breakpoint
CREATE VIEW catalog_write_totals AS
 SELECT d.day,d.charged+coalesce((SELECT sum(b.rows_bound) FROM catalog_initial_bootstrap_reservations b WHERE b.day=d.day),0) AS charged
 FROM catalog_write_days d;
-- statement-breakpoint
DROP TRIGGER catalog_write_reserve;
-- statement-breakpoint
CREATE TRIGGER catalog_write_reserve BEFORE INSERT ON catalog_write_reservations
WHEN coalesce((SELECT charged FROM catalog_write_totals WHERE day=NEW.day),0)+NEW.rows_bound>NEW.ceiling
BEGIN SELECT RAISE(ABORT,'write_budget_exhausted'); END;
-- statement-breakpoint
CREATE TRIGGER catalog_initial_bootstrap_reserve BEFORE INSERT ON catalog_initial_bootstrap_reservations
BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM catalog_head) THEN RAISE(ABORT,'initial_bootstrap_already_published') END;
 SELECT CASE WHEN NEW.day!=strftime('%Y-%m-%d','now') THEN RAISE(ABORT,'initial_bootstrap_day_mismatch') END;
 SELECT CASE WHEN coalesce((SELECT charged FROM catalog_write_totals WHERE day=NEW.day),0)+NEW.rows_bound>NEW.ceiling THEN RAISE(ABORT,'write_budget_exhausted') END;
END;
-- statement-breakpoint
CREATE TRIGGER catalog_initial_bootstrap_immutable BEFORE UPDATE ON catalog_initial_bootstrap_reservations
BEGIN SELECT RAISE(ABORT,'immutable_write_reservation'); END;
-- statement-breakpoint
CREATE TRIGGER catalog_initial_bootstrap_retain BEFORE DELETE ON catalog_initial_bootstrap_reservations
BEGIN SELECT RAISE(ABORT,'permanent_write_reservation'); END;
-- statement-breakpoint
UPDATE model_c_schema SET version=4 WHERE id=1;
