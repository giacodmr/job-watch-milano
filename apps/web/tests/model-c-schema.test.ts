import { beforeAll,afterAll,describe,it,expect } from 'vitest';
import { Miniflare,convertV4MiniflareOptions } from 'miniflare';
import {canonical,sha256} from '../shared/canonical';
import { applySchema,captureSynthetic,restoreSynthetic,migrationSources } from '../tools/model-c-schema';
import { stageCatalog,publicationFixture,seedPersonal,seedV1,jobId,hash,commit } from './helpers/model-c-fixtures';
let runtime:Miniflare, sequence=0;
beforeAll(async()=>{
  runtime=new Miniflare(convertV4MiniflareOptions({modules:true,script:'export default {fetch(){return new Response("synthetic")}}',cf:false,compatibilityDate:'2026-10-29',
    d1Databases:Object.fromEntries(Array.from({length:40},(_,i)=>['DB'+i,'model-c-schema-'+i]))}));
});
afterAll(async()=>{await runtime?.dispose();});
async function fresh(scope:'catalog'|'personal'|'v1') {
  const db=await runtime.getD1Database('DB'+sequence++);const metrics=await applySchema(db,scope);return {db,metrics};
}
async function published(){const {db}=await fresh('catalog');await stageCatalog(db);await db.batch(publicationFixture(db,'run-one'));return db;}

describe('physically separate, inactive Model C schemas',()=>{
  it('separates scopes and makes additive migration replay a zero-write no-op',async()=>{
    const c=await fresh('catalog'), p=await fresh('personal');
    expect(await c.db.prepare('SELECT scope FROM model_c_schema').first('scope')).toBe('CATALOG');
    expect(await p.db.prepare('SELECT scope FROM model_c_schema').first('scope')).toBe('PERSONAL');
    expect(await applySchema(c.db,'catalog')).toMatchObject({applied:0,rowsWritten:0});
    expect(await applySchema(p.db,'personal')).toMatchObject({applied:0,rowsWritten:0});
    await expect(applySchema(c.db,'personal')).rejects.toThrow('WRONG_DATABASE_SCOPE');
    expect((await c.db.prepare("SELECT name FROM sqlite_master WHERE name GLOB 'personal_*'").all()).results).toHaveLength(0);
    const tables=(await c.db.prepare("SELECT name FROM sqlite_master WHERE type='table' AND name NOT GLOB '_*'").all<{name:string}>()).results;
    for(const t of tables){const cols=(await c.db.prepare('PRAGMA table_info('+t.name+')').all<{name:string}>()).results.map(v=>v.name);for(const forbidden of ['owner_id','decision','fit_score','reportable','summary','reason','jd','description','payload_json'])expect(cols).not.toContain(forbidden);}
  });
  it('upgrades an existing populated PERSONAL v2 via additive migration without altering imported facts',async()=>{
    const db=await runtime.getD1Database('DB'+sequence++);
    for(const migration of (await migrationSources('personal')).slice(0,2)) {
      await db.batch([
        db.prepare('CREATE TABLE IF NOT EXISTS model_c_migrations (name TEXT PRIMARY KEY NOT NULL,sha256 TEXT NOT NULL CHECK(length(sha256)=64))'),
        ...migration.statements.map(sql=>db.prepare(sql)),
        db.prepare('INSERT INTO model_c_migrations(name,sha256) VALUES (?,?)').bind(migration.name,migration.sha256),
      ]);
    }
    expect(await db.prepare('SELECT version FROM model_c_schema').first('version')).toBe(2);
    await seedPersonal(db);
    const initial=await db.prepare('SELECT * FROM personal_decision_events').all();
    const head=await db.prepare('SELECT * FROM personal_heads').all();
    const receipts=await db.prepare('SELECT * FROM personal_catalog_receipts').all();
    const migrated=await applySchema(db,'personal');
    expect(migrated.applied).toBe(1);
    expect(await db.prepare('SELECT version FROM model_c_schema').first('version')).toBe(3);
    expect((await db.prepare('SELECT * FROM personal_decision_events').all()).results).toEqual(initial.results);
    expect((await db.prepare('SELECT * FROM personal_heads').all()).results).toEqual(head.results);
    expect((await db.prepare('SELECT * FROM personal_catalog_receipts').all()).results).toEqual(receipts.results);
    expect(await db.prepare('PRAGMA foreign_key_check').all()).toMatchObject({results:[]});
    expect(await applySchema(db,'personal')).toMatchObject({applied:0,rowsWritten:0});
  });
  it('refuses an altered migration hash and refuses to overlay v1',async()=>{
    const {db}=await fresh('catalog');await db.prepare("UPDATE model_c_migrations SET sha256=?").bind('f'.repeat(64)).run();
    await expect(applySchema(db,'catalog')).rejects.toThrow('MIGRATION_HASH_MISMATCH');
    const v1=await fresh('v1');await seedV1(v1.db);const before=await captureSynthetic(v1.db,'v1');
    await expect(applySchema(v1.db,'catalog')).rejects.toThrow('V1_DATABASE_REFUSED');
    expect((await captureSynthetic(v1.db,'v1')).sha256).toBe(before.sha256);
    expect(await v1.db.prepare('SELECT version FROM schema_metadata').first('version')).toBe(5);
  });
});

describe('M47 populated v5 to v6 additive upgrade',()=>{
  it('backfills RECEIVING into durable immutable journal and preserves all M46 chunks',async()=>{
    const db=await runtime.getD1Database('DB'+sequence++);
    for(const m of (await migrationSources('catalog')).slice(0,5)){
      await db.batch([
        db.prepare('CREATE TABLE IF NOT EXISTS model_c_migrations (name TEXT PRIMARY KEY NOT NULL,sha256 TEXT NOT NULL CHECK(length(sha256)=64))'),
        ...m.statements.map(sql=>db.prepare(sql)),
        db.prepare('INSERT INTO model_c_migrations VALUES (?,?)').bind(m.name,m.sha256),
      ]);
    }
    expect(await db.prepare('SELECT version FROM model_c_schema').first('version')).toBe(5);
    const {prepareOfflineIngestPackets}=await import('../tools/model-c-ingest-offline-client');
    const packet=await prepareOfflineIngestPackets({
      commitSha:'a'.repeat(40),manifestDigest:'b'.repeat(64),
      projectionDigest:'c'.repeat(64),planDigest:'d'.repeat(64),
      expectedRevision:0,
    },[{kind:'company',id:'company:synthetic',name:'Synthetic',
      careerUrl:null}],1);
    const digest=await sha256(canonical(packet.run));
    await db.prepare(`INSERT INTO catalog_ingest_runs
      (id,commit_sha,manifest_digest,projection_digest,plan_digest,
       expected_revision,total_chunks,principal_digest,run_digest)
       VALUES(?,?,?,?,?,?,?,?,?)`).bind(
        packet.run.runId,packet.run.commitSha,packet.run.manifestDigest,
        packet.run.projectionDigest,packet.run.planDigest,0,1,'e'.repeat(64),digest).run();
    const part=packet.chunks[0]!;
    await db.prepare(`INSERT INTO catalog_ingest_chunks
      (run_id,chunk_index,chunk_digest,idempotency_key,record_count,records_json)
      VALUES(?,?,?,?,?,?)`).bind(packet.run.runId,0,part.chunkDigest,
        part.idempotencyKey,1,canonical(part.records)).run();
    const old=(await db.prepare('SELECT * FROM catalog_ingest_chunks').all()).results;
    expect((await applySchema(db,'catalog')).applied).toBe(1);
    expect(await db.prepare('SELECT version FROM model_c_schema').first('version')).toBe(6);
    expect((await db.prepare('SELECT * FROM catalog_ingest_chunks').all()).results).toEqual(old);
    const journal=(await db.prepare('SELECT * FROM catalog_ingest_journal').all()).results;
    expect(journal).toHaveLength(1);
    expect(journal[0]).toMatchObject({run_id:packet.run.runId,phase:'RECEIVING',
      sequence:0,event_digest:digest});
    await expect(db.prepare('DELETE FROM catalog_ingest_runs WHERE id=?')
      .bind(packet.run.runId).run()).rejects.toThrow('retained_ingest_run');
    await expect(db.prepare('DELETE FROM catalog_ingest_chunks WHERE run_id=?')
      .bind(packet.run.runId).run()).rejects.toThrow('retained_ingest_chunk');
    expect((await applySchema(db,'catalog')).applied).toBe(0);
    expect((await db.prepare('PRAGMA foreign_key_check').all()).results).toHaveLength(0);
  });
});

describe('catalog structure, staging and transaction contract',()=>{
  it('hides stage and bootstrap until the explicit publication batch',async()=>{
    const {db}=await fresh('catalog');await stageCatalog(db);
    expect((await db.prepare('SELECT * FROM catalog_visible_vacancies').all()).results).toHaveLength(0);
    expect(await db.prepare('SELECT count(*) AS n FROM catalog_stage_vacancies').first('n')).toBe(1);
    await db.batch(publicationFixture(db,'run-one'));
    expect((await db.prepare('SELECT job_id FROM catalog_visible_vacancies').all()).results).toEqual([{job_id:jobId}]);
    expect(await db.prepare("SELECT state FROM catalog_runs WHERE id='run-one'").first('state')).toBe('PUBLISHED');
    expect(await db.prepare('SELECT count(*) AS n FROM catalog_audit').first('n')).toBe(1);
    expect(await db.prepare('SELECT count(*) AS n FROM catalog_cas_guard').first('n')).toBe(0);
  });
  it('rejects incomplete/sparse chunks, unready heads and stage mutations after READY',async()=>{
    const {db}=await fresh('catalog');await stageCatalog(db,'incomplete',0,1,hash,false);
    await expect(db.prepare("UPDATE catalog_runs SET state='READY' WHERE id='incomplete'").run()).rejects.toThrow('incomplete_chunks');
    await db.prepare("INSERT INTO catalog_chunks VALUES ('incomplete',7,?,0)").bind(hash).run();
    await expect(db.prepare("UPDATE catalog_runs SET state='READY' WHERE id='incomplete'").run()).rejects.toThrow('incomplete_chunks');
    await expect(db.prepare("INSERT INTO catalog_head VALUES ('catalog',1,'incomplete',1,1)").run()).rejects.toThrow('catalog_publication_conflict');
    const second=await fresh('catalog');await stageCatalog(second.db);
    await expect(second.db.prepare("INSERT INTO catalog_stage_aliases VALUES ('run-one','new-alias',?,'PYTHON_RESOLVED')").bind(jobId).run()).rejects.toThrow('stage_is_sealed');
    await expect(second.db.prepare("UPDATE catalog_stage_vacancies SET title='changed'").run()).rejects.toThrow();
  });
  it('rolls back all current writes when a CAS assertion fails',async()=>{
    const db=await published();await stageCatalog(db,'second',1,2,'c'.repeat(64));
    const before=(await captureSynthetic(db,'catalog')).sha256;
    await expect(db.batch([
      db.prepare("UPDATE catalog_vacancy_current SET title='Uncommitted synthetic title'"),
      db.prepare('INSERT INTO catalog_cas_guard VALUES (0)'),
    ])).rejects.toThrow('catalog_cas_conflict');
    expect((await captureSynthetic(db,'catalog')).sha256).toBe(before);
    expect(await db.prepare('SELECT title FROM catalog_visible_vacancies').first('title')).toBe('Synthetic Analyst');
  });
  it('lets only one competing publication win and preserves IDs and aliases',async()=>{
    const {db}=await fresh('catalog');await stageCatalog(db,'left');await stageCatalog(db,'right');
    const results=await Promise.allSettled([db.batch(publicationFixture(db,'left')),db.batch(publicationFixture(db,'right'))]);
    expect(results.filter(r=>r.status==='fulfilled')).toHaveLength(1);
    expect(await db.prepare('SELECT sync_revision FROM catalog_head').first('sync_revision')).toBe(1);
    expect(await db.prepare('SELECT id FROM catalog_vacancy_identity').first('id')).toBe(jobId);
    expect(await db.prepare('SELECT count(*) AS n FROM catalog_aliases').first('n')).toBe(2);
  });
  it('enforces ownership/FKs and retains permanent identities, aliases and audit',async()=>{
    const db=await published();
    await expect(db.prepare("UPDATE catalog_vacancy_current SET company_id='missing'").run()).rejects.toThrow();
    await expect(db.prepare("INSERT INTO catalog_aliases VALUES ('bad','missing','EXACT_KEY')").run()).rejects.toThrow();
    await expect(db.prepare('DELETE FROM catalog_vacancy_identity').run()).rejects.toThrow();
    await expect(db.prepare("UPDATE catalog_aliases SET job_id='other'").run()).rejects.toThrow();
    await expect(db.prepare('DELETE FROM catalog_audit').run()).rejects.toThrow();
    await expect(db.prepare("UPDATE catalog_vacancy_current SET lifecycle='UNKNOWN'").run()).rejects.toThrow();
    await expect(db.prepare("UPDATE catalog_source_current SET coverage='CLOSED'").run()).rejects.toThrow();
    await expect(db.prepare('INSERT INTO catalog_company_identity VALUES (NULL)').run()).rejects.toThrow();
    expect((await db.prepare('PRAGMA foreign_key_check').all()).results).toHaveLength(0);
  });
  it('rejects a ledger count mismatch atomically and permits only post-publication stage cleanup',async()=>{
    const {db}=await fresh('catalog');
    await db.prepare('INSERT INTO catalog_ledger_checkpoints VALUES (1,?,99,99)').bind(hash).run();
    await stageCatalog(db);
    await expect(db.batch(publicationFixture(db,'run-one'))).rejects.toThrow('catalog_publication_conflict');
    expect(await db.prepare('SELECT count(*) AS n FROM catalog_vacancy_identity').first('n')).toBe(0);
    const good=await published();
    await good.batch(['catalog_stage_aliases','catalog_stage_vacancies','catalog_stage_sources','catalog_stage_companies','catalog_chunks'].map(t=>good.prepare('DELETE FROM '+t)));
    expect(await good.prepare('SELECT count(*) AS n FROM catalog_visible_vacancies').first('n')).toBe(1);
    expect(await good.prepare('SELECT count(*) AS n FROM catalog_aliases').first('n')).toBe(2);
  });
  it('retains a content revision for no-change observations and rejects revision jumps',async()=>{
    const db=await published();await stageCatalog(db,'same',1,1);
    await db.batch(publicationFixture(db,'same',1,1));
    expect(await db.prepare('SELECT sync_revision FROM catalog_head').first('sync_revision')).toBe(2);
    expect(await db.prepare('SELECT content_revision FROM catalog_head').first('content_revision')).toBe(1);
    await stageCatalog(db,'jump',2,3,'d'.repeat(64));
    await expect(db.batch(publicationFixture(db,'jump',2,3))).rejects.toThrow('catalog_publication_conflict');
    expect(await db.prepare('SELECT sync_revision FROM catalog_head').first('sync_revision')).toBe(2);
  });
});

describe('PERSONAL references and cross-database reconciliation',()=>{
  it('keeps decisions, CLOSED/UNKNOWN and aliases independent from catalog refresh',async()=>{
    const c=await published(), p=await fresh('personal');await seedPersonal(p.db);
    const before=await captureSynthetic(p.db,'personal');
    await stageCatalog(c,'remove',1,2,'e'.repeat(64),true,true);
    await c.batch([c.prepare('INSERT INTO catalog_cas_guard VALUES (1)'),c.prepare('DELETE FROM catalog_vacancy_current'),c.prepare("UPDATE catalog_head SET sync_revision=2,run_id='remove',content_revision=2 WHERE scope='catalog'")]);
    expect((await captureSynthetic(p.db,'personal')).sha256).toBe(before.sha256);
    await p.db.prepare("UPDATE personal_job_refs SET last_known_lifecycle='UNKNOWN',revision=2").run();
    expect(await p.db.prepare('SELECT last_known_lifecycle FROM personal_job_refs').first('last_known_lifecycle')).toBe('UNKNOWN');
    expect(await p.db.prepare('SELECT decision FROM personal_decision_events').first('decision')).toBe('NOT_INTERESTED');
    expect(await c.prepare('SELECT count(*) AS n FROM catalog_aliases').first('n')).toBe(2);
  });
  it('enforces local ownership, immutable event history and revision conflicts',async()=>{
    const {db}=await fresh('personal');await seedPersonal(db);
    await expect(db.prepare("INSERT INTO personal_decision_current VALUES ('other',?,'decision:synthetic',1)").bind(jobId).run()).rejects.toThrow();
    await expect(db.prepare('DELETE FROM personal_decision_events').run()).rejects.toThrow();
    await expect(db.prepare("UPDATE personal_decision_events SET decision='INTERESTED'").run()).rejects.toThrow();
    await expect(db.prepare('DELETE FROM personal_job_refs').run()).rejects.toThrow();
    await expect(db.prepare('UPDATE personal_heads SET revision=3').run()).rejects.toThrow('personal_revision_conflict');
    await expect(db.prepare("UPDATE personal_reference_state SET active=0,revision=1").run()).rejects.toThrow('personal_revision_conflict');
  });
  it('requires a local receipt and fresh personal revision, without inventing cross-DB FKs',async()=>{
    const {db}=await fresh('personal');await seedPersonal(db);
    await expect(db.prepare("UPDATE personal_reconciliation SET state='VERIFIED'").run()).rejects.toThrow();
    await db.prepare("INSERT INTO personal_catalog_receipts VALUES ('receipt',1,1,?,?,?)").bind(commit,hash,hash).run();
    await db.prepare("UPDATE personal_reconciliation SET state='VERIFIED',receipt_id='receipt'").run();
    await db.prepare('UPDATE personal_heads SET revision=2').run();
    expect((await db.prepare('SELECT * FROM personal_verified_reconciliation').all()).results).toHaveLength(0);
    await expect(db.prepare("UPDATE personal_reconciliation SET state='VERIFIED',personal_revision=1").run()).rejects.toThrow('stale_personal_context');
    const tables=(await db.prepare("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'personal_%'").all<{name:string}>()).results;
    for(const t of tables)for(const fk of (await db.prepare('PRAGMA foreign_key_list('+t.name+')').all<{table:string}>()).results)expect(fk.table.startsWith('personal_')).toBe(true);
    // A local receipt records an application assertion, NOT proof of another DB.
    expect(await db.prepare('SELECT state FROM personal_reconciliation').first('state')).toBe('VERIFIED');
  });
});

describe('bounded synthetic backup/restore',()=>{
  it.each(['catalog','personal','v1'] as const)('round-trips %s including data, FK, triggers and migration ledger',async scope=>{
    const {db}=await fresh(scope);
    if(scope==='catalog'){await stageCatalog(db);await db.batch(publicationFixture(db,'run-one'));}
    else if(scope==='personal')await seedPersonal(db);else await seedV1(db);
    const backup=await captureSynthetic(db,scope), restored=await runtime.getD1Database('DB'+sequence++);
    expect(await restoreSynthetic(restored,scope,backup)).toMatchObject({verified:true});
    expect((await captureSynthetic(restored,scope)).sha256).toBe(backup.sha256);
    expect(await applySchema(restored,scope)).toMatchObject({applied:0,rowsWritten:0});
    if(scope==='catalog')await expect(restored.prepare('DELETE FROM catalog_aliases').run()).rejects.toThrow();
    if(scope==='personal')await expect(restored.prepare('DELETE FROM personal_decision_events').run()).rejects.toThrow();
    if(scope==='v1')expect(await restored.prepare('SELECT id FROM jobs').first('id')).toBe(jobId);
  });
  it('rejects corruption, wrong scope and nonempty restore destinations',async()=>{
    const {db}=await fresh('personal');await seedPersonal(db);const backup=await captureSynthetic(db,'personal');
    const empty=await runtime.getD1Database('DB'+sequence++);
    await expect(restoreSynthetic(empty,'personal',{...backup,sha256:'f'.repeat(64)})).rejects.toThrow('BACKUP_INTEGRITY_FAILED');
    await expect(restoreSynthetic(empty,'catalog',backup)).rejects.toThrow('WRONG_BACKUP_SCOPE');
    await expect(restoreSynthetic(db,'personal',backup)).rejects.toThrow('RESTORE_TARGET_NOT_EMPTY');
    const mismatched=structuredClone(backup);
    const ledger=mismatched.data.tables.find(t=>t.name==='model_c_migrations')!;
    ledger.rows[0]![ledger.columns.indexOf('sha256')]='f'.repeat(64);
    mismatched.sha256=await sha256(canonical(mismatched.data));
    await expect(restoreSynthetic(empty,'personal',mismatched)).rejects.toThrow('BACKUP_MIGRATION_MISMATCH');
  });
});
