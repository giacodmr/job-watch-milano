-- Local importer shared CATALOG+PERSONAL write reservations. A crash consumes the
-- full bound: no uncertain writes can be reclaimed or silently lost from quota.
CREATE TABLE catalog_write_days (
 day TEXT PRIMARY KEY NOT NULL CHECK(length(day)=10),
 charged INTEGER NOT NULL CHECK(charged>=0 AND charged<=60000)
);
-- statement-breakpoint
CREATE TABLE catalog_write_reservations (
 id TEXT PRIMARY KEY NOT NULL, day TEXT NOT NULL REFERENCES catalog_write_days(day),
 rows_bound INTEGER NOT NULL CHECK(rows_bound>0),
 ceiling INTEGER NOT NULL CHECK(ceiling BETWEEN 1 AND 60000)
);
-- statement-breakpoint
CREATE TRIGGER catalog_write_reserve BEFORE INSERT ON catalog_write_reservations
WHEN coalesce((SELECT charged FROM catalog_write_days WHERE day=NEW.day),0)+NEW.rows_bound>NEW.ceiling
BEGIN SELECT RAISE(ABORT,'write_budget_exhausted'); END;
-- statement-breakpoint
CREATE TRIGGER catalog_write_charge AFTER INSERT ON catalog_write_reservations
BEGIN UPDATE catalog_write_days SET charged=charged+NEW.rows_bound WHERE day=NEW.day; END;
-- statement-breakpoint
CREATE TRIGGER catalog_write_reservations_immutable BEFORE UPDATE ON catalog_write_reservations
BEGIN SELECT RAISE(ABORT,'immutable_write_reservation'); END;
-- statement-breakpoint
CREATE TRIGGER catalog_write_reservations_retain BEFORE DELETE ON catalog_write_reservations
BEGIN SELECT RAISE(ABORT,'permanent_write_reservation'); END;
-- statement-breakpoint
CREATE TRIGGER catalog_write_days_monotone BEFORE UPDATE ON catalog_write_days
WHEN NEW.day IS NOT OLD.day OR NEW.charged<OLD.charged
BEGIN SELECT RAISE(ABORT,'invalid_write_charge'); END;
-- statement-breakpoint
CREATE TRIGGER catalog_write_days_retain BEFORE DELETE ON catalog_write_days
BEGIN SELECT RAISE(ABORT,'permanent_write_charge'); END;
-- statement-breakpoint
UPDATE model_c_schema SET version=3 WHERE id=1;
-- statement-breakpoint
CREATE TABLE catalog_run_proofs (
 run_id TEXT PRIMARY KEY NOT NULL REFERENCES catalog_runs(id),
 manifest_digest TEXT NOT NULL CHECK(length(manifest_digest)=64),
 environment_digest TEXT NOT NULL CHECK(length(environment_digest)=64),
 reference_digest TEXT NOT NULL CHECK(length(reference_digest)=64)
);
-- statement-breakpoint
CREATE TRIGGER catalog_run_proofs_immutable BEFORE UPDATE ON catalog_run_proofs
BEGIN SELECT RAISE(ABORT,'immutable_projection_proof'); END;
-- statement-breakpoint
CREATE TRIGGER catalog_run_proofs_retain BEFORE DELETE ON catalog_run_proofs
BEGIN SELECT RAISE(ABORT,'permanent_projection_proof'); END;
-- statement-breakpoint
CREATE TABLE catalog_import_assert (valid INTEGER NOT NULL CHECK(valid=1));
-- statement-breakpoint
CREATE TRIGGER catalog_import_assert_clear AFTER INSERT ON catalog_import_assert
BEGIN DELETE FROM catalog_import_assert; END;
