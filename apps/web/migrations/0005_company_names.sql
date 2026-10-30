-- Names belong to an observation, not to the durable identity. Never update
-- companies during staging: that would leak future metadata into the old view.
-- Legacy observations retain NULL and read their original identity name; a
-- schema-4 staging import is hydrated from its validated bundle when resumed.
ALTER TABLE company_versions ADD COLUMN canonical_name TEXT;
-- statement-breakpoint
UPDATE schema_metadata SET version=5 WHERE id=1;
