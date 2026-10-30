-- Preserve 0001 and legacy rows without inventing missing values. Fresh writes
-- require V1 membership and both source proofs; old unknowns block publication.
ALTER TABLE catalog_vacancy_current ADD COLUMN needs_analysis INTEGER CHECK(needs_analysis IN (0,1));
-- statement-breakpoint
ALTER TABLE catalog_stage_vacancies ADD COLUMN needs_analysis INTEGER CHECK(needs_analysis IN (0,1));
-- statement-breakpoint
ALTER TABLE catalog_company_current ADD COLUMN config_id TEXT CHECK(length(config_id)<=1000);
-- statement-breakpoint
ALTER TABLE catalog_company_current ADD COLUMN tier TEXT CHECK(length(tier)<=1000);
-- statement-breakpoint
ALTER TABLE catalog_company_current ADD COLUMN priority TEXT CHECK(length(priority)<=1000);
-- statement-breakpoint
ALTER TABLE catalog_company_current ADD COLUMN membership TEXT CHECK(membership IN ('ACTIVE','CANDIDATE','HISTORICAL'));
-- statement-breakpoint
ALTER TABLE catalog_stage_companies ADD COLUMN config_id TEXT CHECK(length(config_id)<=1000);
-- statement-breakpoint
ALTER TABLE catalog_stage_companies ADD COLUMN tier TEXT CHECK(length(tier)<=1000);
-- statement-breakpoint
ALTER TABLE catalog_stage_companies ADD COLUMN priority TEXT CHECK(length(priority)<=1000);
-- statement-breakpoint
ALTER TABLE catalog_stage_companies ADD COLUMN membership TEXT CHECK(membership IN ('ACTIVE','CANDIDATE','HISTORICAL'));
-- statement-breakpoint
ALTER TABLE catalog_source_current ADD COLUMN coverage_origin_id TEXT REFERENCES catalog_origins(id);
-- statement-breakpoint
ALTER TABLE catalog_stage_sources ADD COLUMN coverage_origin_id TEXT REFERENCES catalog_origins(id);
-- statement-breakpoint
CREATE TRIGGER catalog_company_current_membership_insert BEFORE INSERT ON catalog_company_current WHEN NEW.membership IS NULL
BEGIN SELECT RAISE(ABORT,'company_membership_required'); END;
-- statement-breakpoint
CREATE TRIGGER catalog_company_current_membership_update BEFORE UPDATE ON catalog_company_current WHEN NEW.membership IS NULL
BEGIN SELECT RAISE(ABORT,'company_membership_required'); END;
-- statement-breakpoint
CREATE TRIGGER catalog_stage_companies_membership BEFORE INSERT ON catalog_stage_companies WHEN NEW.membership IS NULL
BEGIN SELECT RAISE(ABORT,'company_membership_required'); END;
-- statement-breakpoint
CREATE TRIGGER catalog_source_coverage_insert BEFORE INSERT ON catalog_source_current WHEN NEW.coverage_origin_id IS NULL
BEGIN SELECT RAISE(ABORT,'coverage_origin_required'); END;
-- statement-breakpoint
CREATE TRIGGER catalog_source_coverage_update BEFORE UPDATE ON catalog_source_current WHEN NEW.coverage_origin_id IS NULL
BEGIN SELECT RAISE(ABORT,'coverage_origin_required'); END;
-- statement-breakpoint
CREATE TRIGGER catalog_stage_sources_coverage BEFORE INSERT ON catalog_stage_sources
WHEN NOT EXISTS(SELECT 1 FROM catalog_origins WHERE id=NEW.coverage_origin_id AND run_id=NEW.run_id)
BEGIN SELECT RAISE(ABORT,'coverage_origin_must_match_run'); END;
-- statement-breakpoint
CREATE TRIGGER catalog_stage_queue_payload BEFORE INSERT ON catalog_stage_vacancies WHEN NEW.operation!='UPSERT' AND NEW.needs_analysis IS NOT NULL
BEGIN SELECT RAISE(ABORT,'unexpected_queue_payload'); END;
-- statement-breakpoint
CREATE TRIGGER catalog_head_metadata_insert BEFORE INSERT ON catalog_head
WHEN EXISTS(SELECT 1 FROM catalog_company_current WHERE membership IS NULL) OR EXISTS(SELECT 1 FROM catalog_source_current WHERE coverage_origin_id IS NULL)
BEGIN SELECT RAISE(ABORT,'catalog_metadata_incomplete'); END;
-- statement-breakpoint
CREATE TRIGGER catalog_head_metadata_update BEFORE UPDATE ON catalog_head
WHEN EXISTS(SELECT 1 FROM catalog_company_current WHERE membership IS NULL) OR EXISTS(SELECT 1 FROM catalog_source_current WHERE coverage_origin_id IS NULL)
BEGIN SELECT RAISE(ABORT,'catalog_metadata_incomplete'); END;
-- statement-breakpoint
UPDATE model_c_schema SET version=2 WHERE id=1;
