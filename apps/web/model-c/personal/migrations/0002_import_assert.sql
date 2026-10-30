-- Atomic snapshot assertion for local importer append/reconciliation batches.
CREATE TABLE personal_import_assert (valid INTEGER NOT NULL CHECK(valid=1));
-- statement-breakpoint
CREATE TRIGGER personal_import_assert_clear AFTER INSERT ON personal_import_assert
BEGIN DELETE FROM personal_import_assert; END;
-- statement-breakpoint
UPDATE model_c_schema SET version=2 WHERE id=1;
