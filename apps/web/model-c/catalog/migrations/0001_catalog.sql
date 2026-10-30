-- Inactive Model C schema. Separate physical CATALOG database only.
-- No v1 migration/binding/reader is changed.
CREATE TABLE model_c_schema (
 id INTEGER PRIMARY KEY CHECK(id=1), scope TEXT NOT NULL CHECK(scope='CATALOG'),
 version INTEGER NOT NULL CHECK(version>=1)
);
-- statement-breakpoint
INSERT INTO model_c_schema VALUES (1,'CATALOG',1);
-- statement-breakpoint
CREATE TABLE catalog_content_revisions (
 revision INTEGER PRIMARY KEY CHECK(revision>0), content_digest TEXT NOT NULL CHECK(length(content_digest)=64 AND content_digest NOT GLOB '*[^0-9a-f]*'),
 origin_commit TEXT NOT NULL CHECK(length(origin_commit)=40 AND origin_commit NOT GLOB '*[^0-9a-f]*'), origin_manifest_digest TEXT NOT NULL CHECK(length(origin_manifest_digest)=64 AND origin_manifest_digest NOT GLOB '*[^0-9a-f]*')
);
-- statement-breakpoint
CREATE TABLE catalog_ledger_checkpoints (
 revision INTEGER PRIMARY KEY CHECK(revision>0), ledger_digest TEXT NOT NULL CHECK(length(ledger_digest)=64 AND ledger_digest NOT GLOB '*[^0-9a-f]*'),
 identity_count INTEGER NOT NULL CHECK(identity_count>=0), mapping_count INTEGER NOT NULL CHECK(mapping_count>=0)
);
-- statement-breakpoint
CREATE TABLE catalog_runs (
 id TEXT PRIMARY KEY NOT NULL, observed_commit TEXT NOT NULL CHECK(length(observed_commit)=40 AND observed_commit NOT GLOB '*[^0-9a-f]*'),
 projection_digest TEXT NOT NULL CHECK(length(projection_digest)=64 AND projection_digest NOT GLOB '*[^0-9a-f]*'),
 expected_revision INTEGER NOT NULL CHECK(expected_revision>=0),
 content_revision INTEGER NOT NULL REFERENCES catalog_content_revisions(revision),
 ledger_revision INTEGER NOT NULL REFERENCES catalog_ledger_checkpoints(revision),
 expected_chunks INTEGER NOT NULL CHECK(expected_chunks>0),
 expected_companies INTEGER NOT NULL CHECK(expected_companies>=0), expected_sources INTEGER NOT NULL CHECK(expected_sources>=0), expected_vacancies INTEGER NOT NULL CHECK(expected_vacancies>=0),
 state TEXT NOT NULL DEFAULT 'STAGING' CHECK(state IN ('STAGING','READY','PUBLISHED','ABORTED'))
);
-- statement-breakpoint
CREATE TABLE catalog_origins (
 id TEXT PRIMARY KEY NOT NULL, run_id TEXT NOT NULL REFERENCES catalog_runs(id),
 commit_sha TEXT NOT NULL CHECK(length(commit_sha)=40 AND commit_sha NOT GLOB '*[^0-9a-f]*'), source_path TEXT NOT NULL CHECK(length(source_path) BETWEEN 1 AND 300),
 source_sha256 TEXT NOT NULL CHECK(length(source_sha256)=64 AND source_sha256 NOT GLOB '*[^0-9a-f]*'),
 UNIQUE(id,run_id)
);
-- statement-breakpoint
CREATE TABLE catalog_company_identity (id TEXT PRIMARY KEY NOT NULL CHECK(length(id)>0));
-- statement-breakpoint
CREATE TABLE catalog_source_identity (
 id TEXT PRIMARY KEY NOT NULL CHECK(length(id)>0), company_id TEXT NOT NULL REFERENCES catalog_company_identity(id),
 source_key TEXT NOT NULL, UNIQUE(company_id,source_key), UNIQUE(id,company_id)
);
-- statement-breakpoint
CREATE TABLE catalog_vacancy_identity (
 id TEXT PRIMARY KEY NOT NULL CHECK(length(id)>0), company_id TEXT NOT NULL REFERENCES catalog_company_identity(id),
 origin_job_key TEXT NOT NULL UNIQUE, UNIQUE(id,company_id)
);
-- statement-breakpoint
CREATE TABLE catalog_aliases (
 alias_key TEXT PRIMARY KEY NOT NULL, job_id TEXT NOT NULL REFERENCES catalog_vacancy_identity(id),
 resolution TEXT NOT NULL CHECK(resolution IN ('EXACT_KEY','PYTHON_RESOLVED','MANUAL_CONFIRMED'))
);
-- statement-breakpoint
CREATE INDEX catalog_alias_job ON catalog_aliases(job_id);
-- statement-breakpoint
CREATE TABLE catalog_company_current (
 company_id TEXT PRIMARY KEY NOT NULL REFERENCES catalog_company_identity(id), display_name TEXT NOT NULL CHECK(length(display_name)<=1000),
 career_url TEXT, origin_id TEXT NOT NULL REFERENCES catalog_origins(id)
);
-- statement-breakpoint
CREATE TABLE catalog_source_current (
 source_id TEXT PRIMARY KEY NOT NULL, company_id TEXT NOT NULL, ats_family TEXT NOT NULL, inventory_url TEXT,
 coverage TEXT CHECK(coverage IN ('VERIFIED','PARTIAL','FAILED','NOT_CHECKED')), generated_at TEXT,
 origin_id TEXT NOT NULL REFERENCES catalog_origins(id), UNIQUE(source_id,company_id),
 FOREIGN KEY(company_id) REFERENCES catalog_company_current(company_id),
 FOREIGN KEY(source_id,company_id) REFERENCES catalog_source_identity(id,company_id)
);
-- statement-breakpoint
CREATE TABLE catalog_vacancy_current (
 job_id TEXT PRIMARY KEY NOT NULL, company_id TEXT NOT NULL, source_id TEXT,
 kind TEXT NOT NULL CHECK(kind IN ('OPPORTUNITY','AI_QUEUE')),
 lifecycle TEXT NOT NULL CHECK(lifecycle IN ('NEW','STILL_OPEN','UPDATED')),
 title TEXT CHECK(length(title)<=1000), location TEXT CHECK(length(location)<=1000),
 canonical_url TEXT, apply_url TEXT, fingerprint TEXT, batch TEXT CHECK(batch IN ('jw1','jw2','jw3','jw4')),
 first_seen_at TEXT, last_seen_at TEXT, worker_eligible INTEGER CHECK(worker_eligible IN (0,1)), technical_status TEXT,
 origin_id TEXT NOT NULL REFERENCES catalog_origins(id),
 FOREIGN KEY(job_id,company_id) REFERENCES catalog_vacancy_identity(id,company_id),
 FOREIGN KEY(source_id,company_id) REFERENCES catalog_source_current(source_id,company_id),
 FOREIGN KEY(company_id) REFERENCES catalog_company_current(company_id)
);
-- statement-breakpoint
CREATE INDEX catalog_vacancy_page ON catalog_vacancy_current(company_id,title,job_id);
-- statement-breakpoint
CREATE INDEX catalog_vacancy_filters ON catalog_vacancy_current(batch,lifecycle,kind);
-- statement-breakpoint
CREATE TABLE catalog_chunks (
 run_id TEXT NOT NULL REFERENCES catalog_runs(id), chunk_index INTEGER NOT NULL CHECK(chunk_index>=0),
 chunk_digest TEXT NOT NULL CHECK(length(chunk_digest)=64 AND chunk_digest NOT GLOB '*[^0-9a-f]*'), row_count INTEGER NOT NULL CHECK(row_count>=0),
 PRIMARY KEY(run_id,chunk_index)
);
-- statement-breakpoint
CREATE TABLE catalog_stage_companies (
 run_id TEXT NOT NULL REFERENCES catalog_runs(id), company_id TEXT NOT NULL, display_name TEXT NOT NULL CHECK(length(display_name)<=1000),
 career_url TEXT, origin_id TEXT NOT NULL,
 PRIMARY KEY(run_id,company_id), FOREIGN KEY(origin_id,run_id) REFERENCES catalog_origins(id,run_id)
);
-- statement-breakpoint
CREATE TABLE catalog_stage_sources (
 run_id TEXT NOT NULL REFERENCES catalog_runs(id), source_id TEXT NOT NULL, company_id TEXT NOT NULL, source_key TEXT NOT NULL,
 ats_family TEXT NOT NULL, inventory_url TEXT, coverage TEXT CHECK(coverage IN ('VERIFIED','PARTIAL','FAILED','NOT_CHECKED')),
 generated_at TEXT, origin_id TEXT NOT NULL,
 PRIMARY KEY(run_id,source_id), FOREIGN KEY(origin_id,run_id) REFERENCES catalog_origins(id,run_id)
);
-- statement-breakpoint
CREATE TABLE catalog_stage_vacancies (
 run_id TEXT NOT NULL REFERENCES catalog_runs(id), job_id TEXT NOT NULL, company_id TEXT NOT NULL, origin_job_key TEXT NOT NULL,
 operation TEXT NOT NULL CHECK(operation IN ('IDENTIFY_ONLY','UPSERT','REMOVE')),
 source_id TEXT, kind TEXT CHECK(kind IN ('OPPORTUNITY','AI_QUEUE')),
 lifecycle TEXT CHECK(lifecycle IN ('NEW','STILL_OPEN','UPDATED')),
 title TEXT CHECK(length(title)<=1000), location TEXT CHECK(length(location)<=1000), canonical_url TEXT, apply_url TEXT, fingerprint TEXT,
 batch TEXT CHECK(batch IN ('jw1','jw2','jw3','jw4')), first_seen_at TEXT, last_seen_at TEXT,
 worker_eligible INTEGER CHECK(worker_eligible IN (0,1)), technical_status TEXT, origin_id TEXT NOT NULL,
 PRIMARY KEY(run_id,job_id), UNIQUE(run_id,origin_job_key),
 FOREIGN KEY(origin_id,run_id) REFERENCES catalog_origins(id,run_id),
 CHECK(operation!='UPSERT' OR (kind IS NOT NULL AND lifecycle IS NOT NULL)),
 CHECK(operation='UPSERT' OR (source_id IS NULL AND kind IS NULL AND lifecycle IS NULL AND title IS NULL AND location IS NULL AND
 canonical_url IS NULL AND apply_url IS NULL AND fingerprint IS NULL AND batch IS NULL AND first_seen_at IS NULL AND last_seen_at IS NULL AND worker_eligible IS NULL AND technical_status IS NULL))
);
-- statement-breakpoint
CREATE TABLE catalog_stage_aliases (
 run_id TEXT NOT NULL, alias_key TEXT NOT NULL, job_id TEXT NOT NULL,
 resolution TEXT NOT NULL CHECK(resolution IN ('EXACT_KEY','PYTHON_RESOLVED','MANUAL_CONFIRMED')),
 PRIMARY KEY(run_id,alias_key), FOREIGN KEY(run_id,job_id) REFERENCES catalog_stage_vacancies(run_id,job_id)
);
-- statement-breakpoint
CREATE TABLE catalog_head (
 scope TEXT PRIMARY KEY NOT NULL CHECK(scope='catalog'), sync_revision INTEGER NOT NULL CHECK(sync_revision>0),
 run_id TEXT NOT NULL UNIQUE REFERENCES catalog_runs(id),
 content_revision INTEGER NOT NULL REFERENCES catalog_content_revisions(revision),
 ledger_revision INTEGER NOT NULL REFERENCES catalog_ledger_checkpoints(revision)
);
-- statement-breakpoint
CREATE TABLE catalog_audit (
 id TEXT PRIMARY KEY NOT NULL, run_id TEXT NOT NULL REFERENCES catalog_runs(id),
 event_code TEXT NOT NULL CHECK(event_code='CATALOG_PUBLISHED'), sync_revision INTEGER NOT NULL UNIQUE
);
-- statement-breakpoint
CREATE VIEW catalog_visible_vacancies AS SELECT v.* FROM catalog_vacancy_current v WHERE EXISTS(SELECT 1 FROM catalog_head WHERE scope='catalog');
-- statement-breakpoint
CREATE VIEW catalog_visible_companies AS SELECT v.* FROM catalog_company_current v WHERE EXISTS(SELECT 1 FROM catalog_head WHERE scope='catalog');
-- statement-breakpoint
CREATE VIEW catalog_visible_sources AS SELECT v.* FROM catalog_source_current v WHERE EXISTS(SELECT 1 FROM catalog_head WHERE scope='catalog');
-- statement-breakpoint
CREATE TRIGGER catalog_runs_start BEFORE INSERT ON catalog_runs WHEN NEW.state!='STAGING'
BEGIN SELECT RAISE(ABORT,'run_must_start_staging'); END;
-- statement-breakpoint
CREATE TRIGGER catalog_runs_transition BEFORE UPDATE OF state ON catalog_runs
WHEN NOT ((OLD.state='STAGING' AND NEW.state IN ('READY','ABORTED')) OR
 (OLD.state='READY' AND NEW.state='ABORTED') OR (OLD.state='READY' AND NEW.state='PUBLISHED' AND EXISTS(SELECT 1 FROM catalog_head WHERE run_id=NEW.id)))
BEGIN SELECT RAISE(ABORT,'invalid_run_transition'); END;
-- statement-breakpoint
CREATE TRIGGER catalog_runs_ready BEFORE UPDATE OF state ON catalog_runs WHEN NEW.state='READY' AND
 ((SELECT count(*) FROM catalog_chunks WHERE run_id=NEW.id)!=NEW.expected_chunks OR
 (SELECT min(chunk_index) FROM catalog_chunks WHERE run_id=NEW.id)!=0 OR
 (SELECT max(chunk_index) FROM catalog_chunks WHERE run_id=NEW.id)!=NEW.expected_chunks-1)
BEGIN SELECT RAISE(ABORT,'incomplete_chunks'); END;
-- statement-breakpoint
CREATE TRIGGER catalog_runs_immutable BEFORE UPDATE ON catalog_runs WHEN NEW.id IS NOT OLD.id OR NEW.observed_commit IS NOT OLD.observed_commit OR NEW.projection_digest IS NOT OLD.projection_digest OR NEW.expected_revision IS NOT OLD.expected_revision OR NEW.content_revision IS NOT OLD.content_revision OR NEW.ledger_revision IS NOT OLD.ledger_revision OR NEW.expected_chunks IS NOT OLD.expected_chunks OR NEW.expected_companies IS NOT OLD.expected_companies OR NEW.expected_sources IS NOT OLD.expected_sources OR NEW.expected_vacancies IS NOT OLD.expected_vacancies
BEGIN SELECT RAISE(ABORT,'immutable_identity_or_event'); END;
-- statement-breakpoint
CREATE TRIGGER catalog_runs_retain BEFORE DELETE ON catalog_runs
BEGIN SELECT RAISE(ABORT,'permanent_identity_or_event'); END;
-- statement-breakpoint
CREATE TRIGGER catalog_company_identity_immutable BEFORE UPDATE ON catalog_company_identity
BEGIN SELECT RAISE(ABORT,'immutable_identity_or_event'); END;
-- statement-breakpoint
CREATE TRIGGER catalog_company_identity_retain BEFORE DELETE ON catalog_company_identity
BEGIN SELECT RAISE(ABORT,'permanent_identity_or_event'); END;
-- statement-breakpoint
CREATE TRIGGER catalog_source_identity_immutable BEFORE UPDATE ON catalog_source_identity
BEGIN SELECT RAISE(ABORT,'immutable_identity_or_event'); END;
-- statement-breakpoint
CREATE TRIGGER catalog_source_identity_retain BEFORE DELETE ON catalog_source_identity
BEGIN SELECT RAISE(ABORT,'permanent_identity_or_event'); END;
-- statement-breakpoint
CREATE TRIGGER catalog_vacancy_identity_immutable BEFORE UPDATE ON catalog_vacancy_identity
BEGIN SELECT RAISE(ABORT,'immutable_identity_or_event'); END;
-- statement-breakpoint
CREATE TRIGGER catalog_vacancy_identity_retain BEFORE DELETE ON catalog_vacancy_identity
BEGIN SELECT RAISE(ABORT,'permanent_identity_or_event'); END;
-- statement-breakpoint
CREATE TRIGGER catalog_aliases_immutable BEFORE UPDATE ON catalog_aliases
BEGIN SELECT RAISE(ABORT,'immutable_identity_or_event'); END;
-- statement-breakpoint
CREATE TRIGGER catalog_aliases_retain BEFORE DELETE ON catalog_aliases
BEGIN SELECT RAISE(ABORT,'permanent_identity_or_event'); END;
-- statement-breakpoint
CREATE TRIGGER catalog_origins_immutable BEFORE UPDATE ON catalog_origins
BEGIN SELECT RAISE(ABORT,'immutable_identity_or_event'); END;
-- statement-breakpoint
CREATE TRIGGER catalog_origins_retain BEFORE DELETE ON catalog_origins
BEGIN SELECT RAISE(ABORT,'permanent_identity_or_event'); END;
-- statement-breakpoint
CREATE TRIGGER catalog_content_revisions_immutable BEFORE UPDATE ON catalog_content_revisions
BEGIN SELECT RAISE(ABORT,'immutable_identity_or_event'); END;
-- statement-breakpoint
CREATE TRIGGER catalog_content_revisions_retain BEFORE DELETE ON catalog_content_revisions
BEGIN SELECT RAISE(ABORT,'permanent_identity_or_event'); END;
-- statement-breakpoint
CREATE TRIGGER catalog_ledger_checkpoints_immutable BEFORE UPDATE ON catalog_ledger_checkpoints
BEGIN SELECT RAISE(ABORT,'immutable_identity_or_event'); END;
-- statement-breakpoint
CREATE TRIGGER catalog_ledger_checkpoints_retain BEFORE DELETE ON catalog_ledger_checkpoints
BEGIN SELECT RAISE(ABORT,'permanent_identity_or_event'); END;
-- statement-breakpoint
CREATE TRIGGER catalog_audit_immutable BEFORE UPDATE ON catalog_audit
BEGIN SELECT RAISE(ABORT,'immutable_identity_or_event'); END;
-- statement-breakpoint
CREATE TRIGGER catalog_audit_retain BEFORE DELETE ON catalog_audit
BEGIN SELECT RAISE(ABORT,'permanent_identity_or_event'); END;
-- statement-breakpoint
CREATE TRIGGER catalog_stage_companies_insert_staging BEFORE INSERT ON catalog_stage_companies
WHEN (SELECT state FROM catalog_runs WHERE id=NEW.run_id)!='STAGING'
BEGIN SELECT RAISE(ABORT,'stage_is_sealed'); END;
-- statement-breakpoint
CREATE TRIGGER catalog_stage_companies_update_staging BEFORE UPDATE ON catalog_stage_companies
WHEN (SELECT state FROM catalog_runs WHERE id=NEW.run_id)!='STAGING'
BEGIN SELECT RAISE(ABORT,'stage_is_sealed'); END;
-- statement-breakpoint
CREATE TRIGGER catalog_stage_companies_delete_staging BEFORE DELETE ON catalog_stage_companies
WHEN (SELECT state FROM catalog_runs WHERE id=OLD.run_id) NOT IN ('PUBLISHED','ABORTED')
BEGIN SELECT RAISE(ABORT,'stage_is_sealed'); END;
-- statement-breakpoint
CREATE TRIGGER catalog_stage_companies_immutable BEFORE UPDATE ON catalog_stage_companies
BEGIN SELECT RAISE(ABORT,'immutable_identity_or_event'); END;
-- statement-breakpoint
CREATE TRIGGER catalog_stage_sources_insert_staging BEFORE INSERT ON catalog_stage_sources
WHEN (SELECT state FROM catalog_runs WHERE id=NEW.run_id)!='STAGING'
BEGIN SELECT RAISE(ABORT,'stage_is_sealed'); END;
-- statement-breakpoint
CREATE TRIGGER catalog_stage_sources_update_staging BEFORE UPDATE ON catalog_stage_sources
WHEN (SELECT state FROM catalog_runs WHERE id=NEW.run_id)!='STAGING'
BEGIN SELECT RAISE(ABORT,'stage_is_sealed'); END;
-- statement-breakpoint
CREATE TRIGGER catalog_stage_sources_delete_staging BEFORE DELETE ON catalog_stage_sources
WHEN (SELECT state FROM catalog_runs WHERE id=OLD.run_id) NOT IN ('PUBLISHED','ABORTED')
BEGIN SELECT RAISE(ABORT,'stage_is_sealed'); END;
-- statement-breakpoint
CREATE TRIGGER catalog_stage_sources_immutable BEFORE UPDATE ON catalog_stage_sources
BEGIN SELECT RAISE(ABORT,'immutable_identity_or_event'); END;
-- statement-breakpoint
CREATE TRIGGER catalog_stage_vacancies_insert_staging BEFORE INSERT ON catalog_stage_vacancies
WHEN (SELECT state FROM catalog_runs WHERE id=NEW.run_id)!='STAGING'
BEGIN SELECT RAISE(ABORT,'stage_is_sealed'); END;
-- statement-breakpoint
CREATE TRIGGER catalog_stage_vacancies_update_staging BEFORE UPDATE ON catalog_stage_vacancies
WHEN (SELECT state FROM catalog_runs WHERE id=NEW.run_id)!='STAGING'
BEGIN SELECT RAISE(ABORT,'stage_is_sealed'); END;
-- statement-breakpoint
CREATE TRIGGER catalog_stage_vacancies_delete_staging BEFORE DELETE ON catalog_stage_vacancies
WHEN (SELECT state FROM catalog_runs WHERE id=OLD.run_id) NOT IN ('PUBLISHED','ABORTED')
BEGIN SELECT RAISE(ABORT,'stage_is_sealed'); END;
-- statement-breakpoint
CREATE TRIGGER catalog_stage_vacancies_immutable BEFORE UPDATE ON catalog_stage_vacancies
BEGIN SELECT RAISE(ABORT,'immutable_identity_or_event'); END;
-- statement-breakpoint
CREATE TRIGGER catalog_stage_aliases_insert_staging BEFORE INSERT ON catalog_stage_aliases
WHEN (SELECT state FROM catalog_runs WHERE id=NEW.run_id)!='STAGING'
BEGIN SELECT RAISE(ABORT,'stage_is_sealed'); END;
-- statement-breakpoint
CREATE TRIGGER catalog_stage_aliases_update_staging BEFORE UPDATE ON catalog_stage_aliases
WHEN (SELECT state FROM catalog_runs WHERE id=NEW.run_id)!='STAGING'
BEGIN SELECT RAISE(ABORT,'stage_is_sealed'); END;
-- statement-breakpoint
CREATE TRIGGER catalog_stage_aliases_delete_staging BEFORE DELETE ON catalog_stage_aliases
WHEN (SELECT state FROM catalog_runs WHERE id=OLD.run_id) NOT IN ('PUBLISHED','ABORTED')
BEGIN SELECT RAISE(ABORT,'stage_is_sealed'); END;
-- statement-breakpoint
CREATE TRIGGER catalog_stage_aliases_immutable BEFORE UPDATE ON catalog_stage_aliases
BEGIN SELECT RAISE(ABORT,'immutable_identity_or_event'); END;
-- statement-breakpoint
CREATE TRIGGER catalog_chunks_insert_staging BEFORE INSERT ON catalog_chunks
WHEN (SELECT state FROM catalog_runs WHERE id=NEW.run_id)!='STAGING'
BEGIN SELECT RAISE(ABORT,'stage_is_sealed'); END;
-- statement-breakpoint
CREATE TRIGGER catalog_chunks_update_staging BEFORE UPDATE ON catalog_chunks
WHEN (SELECT state FROM catalog_runs WHERE id=NEW.run_id)!='STAGING'
BEGIN SELECT RAISE(ABORT,'stage_is_sealed'); END;
-- statement-breakpoint
CREATE TRIGGER catalog_chunks_delete_staging BEFORE DELETE ON catalog_chunks
WHEN (SELECT state FROM catalog_runs WHERE id=OLD.run_id) NOT IN ('PUBLISHED','ABORTED')
BEGIN SELECT RAISE(ABORT,'stage_is_sealed'); END;
-- statement-breakpoint
CREATE TRIGGER catalog_chunks_immutable BEFORE UPDATE ON catalog_chunks
BEGIN SELECT RAISE(ABORT,'immutable_identity_or_event'); END;
-- statement-breakpoint
CREATE TRIGGER catalog_head_insert BEFORE INSERT ON catalog_head
WHEN NOT (NEW.sync_revision=1 AND NEW.content_revision=1 AND NEW.ledger_revision=1 AND (SELECT expected_revision FROM catalog_runs WHERE id=NEW.run_id)=0) OR NOT EXISTS(SELECT 1 FROM catalog_runs r WHERE r.id=NEW.run_id AND r.state='READY' AND r.content_revision=NEW.content_revision AND r.ledger_revision=NEW.ledger_revision)
 OR (SELECT count(*) FROM catalog_company_current)!=(SELECT expected_companies FROM catalog_runs WHERE id=NEW.run_id)
 OR (SELECT count(*) FROM catalog_source_current)!=(SELECT expected_sources FROM catalog_runs WHERE id=NEW.run_id)
 OR (SELECT count(*) FROM catalog_vacancy_current)!=(SELECT expected_vacancies FROM catalog_runs WHERE id=NEW.run_id)
 OR (SELECT count(*) FROM catalog_vacancy_identity)!=(SELECT identity_count FROM catalog_ledger_checkpoints WHERE revision=NEW.ledger_revision)
 OR (SELECT count(*) FROM catalog_aliases)!=(SELECT mapping_count FROM catalog_ledger_checkpoints WHERE revision=NEW.ledger_revision)
BEGIN SELECT RAISE(ABORT,'catalog_publication_conflict'); END;
-- statement-breakpoint
CREATE TRIGGER catalog_head_insert_publish AFTER INSERT ON catalog_head
BEGIN
 UPDATE catalog_runs SET state='PUBLISHED' WHERE id=NEW.run_id;
 INSERT INTO catalog_audit(id,run_id,event_code,sync_revision) VALUES ('publication:'||NEW.sync_revision,NEW.run_id,'CATALOG_PUBLISHED',NEW.sync_revision);
END;
-- statement-breakpoint
CREATE TRIGGER catalog_head_update BEFORE UPDATE ON catalog_head
WHEN NOT (NEW.scope=OLD.scope AND NEW.sync_revision=OLD.sync_revision+1 AND (SELECT expected_revision FROM catalog_runs WHERE id=NEW.run_id)=OLD.sync_revision AND (NEW.content_revision=OLD.content_revision OR (NEW.content_revision=OLD.content_revision+1 AND (SELECT content_digest FROM catalog_content_revisions WHERE revision=NEW.content_revision)!=(SELECT content_digest FROM catalog_content_revisions WHERE revision=OLD.content_revision))) AND (NEW.ledger_revision=OLD.ledger_revision OR (NEW.ledger_revision=OLD.ledger_revision+1 AND (SELECT ledger_digest FROM catalog_ledger_checkpoints WHERE revision=NEW.ledger_revision)!=(SELECT ledger_digest FROM catalog_ledger_checkpoints WHERE revision=OLD.ledger_revision)))) OR NOT EXISTS(SELECT 1 FROM catalog_runs r WHERE r.id=NEW.run_id AND r.state='READY' AND r.content_revision=NEW.content_revision AND r.ledger_revision=NEW.ledger_revision)
 OR (SELECT count(*) FROM catalog_company_current)!=(SELECT expected_companies FROM catalog_runs WHERE id=NEW.run_id)
 OR (SELECT count(*) FROM catalog_source_current)!=(SELECT expected_sources FROM catalog_runs WHERE id=NEW.run_id)
 OR (SELECT count(*) FROM catalog_vacancy_current)!=(SELECT expected_vacancies FROM catalog_runs WHERE id=NEW.run_id)
 OR (SELECT count(*) FROM catalog_vacancy_identity)!=(SELECT identity_count FROM catalog_ledger_checkpoints WHERE revision=NEW.ledger_revision)
 OR (SELECT count(*) FROM catalog_aliases)!=(SELECT mapping_count FROM catalog_ledger_checkpoints WHERE revision=NEW.ledger_revision)
BEGIN SELECT RAISE(ABORT,'catalog_publication_conflict'); END;
-- statement-breakpoint
CREATE TRIGGER catalog_head_update_publish AFTER UPDATE ON catalog_head
BEGIN
 UPDATE catalog_runs SET state='PUBLISHED' WHERE id=NEW.run_id;
 INSERT INTO catalog_audit(id,run_id,event_code,sync_revision) VALUES ('publication:'||NEW.sync_revision,NEW.run_id,'CATALOG_PUBLISHED',NEW.sync_revision);
END;
-- statement-breakpoint
CREATE TRIGGER catalog_head_retain BEFORE DELETE ON catalog_head BEGIN SELECT RAISE(ABORT,'checkpoint_required'); END;
-- statement-breakpoint
CREATE TABLE catalog_cas_guard (expected_revision INTEGER NOT NULL CHECK(expected_revision>=0));
-- statement-breakpoint
CREATE TRIGGER catalog_cas_check BEFORE INSERT ON catalog_cas_guard WHEN NEW.expected_revision!=coalesce((SELECT sync_revision FROM catalog_head WHERE scope='catalog'),0) BEGIN SELECT RAISE(ABORT,'catalog_cas_conflict'); END;
-- statement-breakpoint
CREATE TRIGGER catalog_cas_clear AFTER INSERT ON catalog_cas_guard BEGIN DELETE FROM catalog_cas_guard; END;
