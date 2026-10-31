import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { execFileSync } from 'node:child_process';
import { mkdtemp, readFile, writeFile, rm } from 'node:fs/promises';
import { resolve } from 'node:path';
import { tmpdir } from 'node:os';
import { Miniflare, convertV4MiniflareOptions } from 'miniflare';
import { applySchema, captureSynthetic } from '../tools/model-c-schema';
import { importModelC, ModelCImportError, inspectCatalogPlan } from '../tools/model-c-importer';
import {executePersonalCommand} from '../worker/data/model-c-personal-write';
import {getModelCPersonalJob} from '../worker/data/model-c-personal';
import type { ImportOptions } from '../tools/model-c-importer';
import { verifyGitProjection } from '../tools/model-c-git';
import { importSnapshot } from '../worker/data/importer';
import { selectModelC } from '../shared/model-c-selection';
import { assessFreeBootstrapRemoteQuota } from '../tools/model-c-free-bootstrap';
import { canonical, sha256 } from '../shared/canonical';
import {prepareSafeRemoteBootstrapPlan} from '../tools/model-c-remote-plan';
import {prepareOfflineIngestPackets} from '../tools/model-c-ingest-offline-client';
import {projectTrustedInventoryV1} from '../tools/model-c-trusted-stage';

let runtime:Miniflare, seq=0, commitSequence=0;
const dirs:string[]=[], measurements:Record<string,unknown>={}, preflights:Record<string,unknown>={};
const bootstrap={identities:{mode:'first-v1-bootstrap' as const},personalReferences:[]};
const python=process.env.JOB_WATCH_PYTHON||'python3';
const git=(repo:string,...args:string[])=>execFileSync('git',['-C',repo,...args],{encoding:'utf8',stdio:['ignore','pipe','pipe']}).trim();
function cohere(repo:string) {execFileSync(python,['tests/helpers/model-c-import-fixture.py',repo,'cohere'],{stdio:'pipe',env:{...process.env,PYTHONDONTWRITEBYTECODE:'1'}});}
function commit(repo:string) {
  git(repo,'add','.');git(repo,'-c','user.name=Synthetic','-c','user.email=synthetic@example.test','commit','--allow-empty','-qm','Synthetic importer fixture '+(++commitSequence));
  const sha=git(repo,'rev-parse','HEAD');git(repo,'update-ref','refs/remotes/origin/main',sha);return sha;
}
async function fixture(count=2, profile?:'baseline') {
  const repo=await mkdtemp(resolve(tmpdir(),'model-c-test-'));dirs.push(repo);
  execFileSync(python,['tests/helpers/model-c-import-fixture.py',repo,'seed',String(count),...(profile?[profile]:[])],{stdio:'pipe',env:{...process.env,PYTHONDONTWRITEBYTECODE:'1'}});
  git(repo,'init','-q','-b','main');git(repo,'remote','add','origin','https://github.com/giacodmr/job-watch-milano.git');
  const sha=commit(repo), c=await runtime.getD1Database('DB'+seq++), p=await runtime.getD1Database('DB'+seq++);
  const schemaCosts={catalog:await applySchema(c,'catalog'),personal:await applySchema(p,'personal')};
  const options:ImportOptions={source:{repo,commit:sha},bootstrap:'empty-target',owner:'synthetic-owner',executionTarget:'local-ephemeral',budget:{day:new Date().toISOString().slice(0,10),availableRows:30000}};
  return {repo,c,p,options,schemaCosts};
}
async function inventory(repo:string,mutate:(jobs:Record<string,unknown>[])=>void) {
  const path=resolve(repo,'current_jobs_jw2.json'), data=JSON.parse(await readFile(path,'utf8'));
  mutate(data.companies[0].jobs);await writeFile(path,JSON.stringify(data));cohere(repo);return commit(repo);
}
// Inject real transaction failures, not alternate importer logic.
function intercept(db:D1Database, handler:(sql:string[],actual:()=>Promise<D1Result[]>)=>Promise<D1Result[]>) {
  const statements=new WeakMap<object,{sql:string;real:D1PreparedStatement}>();
  const wrap=(real:D1PreparedStatement,sql:string):D1PreparedStatement=>{
    const result={bind:(...args:unknown[])=>wrap(real.bind(...args),sql),all:real.all.bind(real),first:real.first.bind(real),run:real.run.bind(real),raw:real.raw.bind(real)} as D1PreparedStatement;
    statements.set(result,{sql,real});return result;
  };
  return {prepare:(sql:string)=>wrap(db.prepare(sql),sql),batch:async(stmts:D1PreparedStatement[])=>handler(stmts.map(s=>statements.get(s)!.sql),()=>db.batch(stmts.map(s=>statements.get(s)!.real)))} as D1Database;
}
const count=async(db:D1Database,t:string)=>Number(await db.prepare('SELECT count(*) AS n FROM '+t).first('n'));
beforeAll(async()=>{runtime=new Miniflare(convertV4MiniflareOptions({modules:true,script:'export default {fetch(){return new Response("synthetic")}}',cf:false,compatibilityDate:'2026-10-29',d1Databases:Object.fromEntries(Array.from({length:90},(_,i)=>['DB'+i,'importer-'+i]))}));});
afterAll(async()=>{await runtime?.dispose();for(const d of dirs)await rm(d,{recursive:true,force:true});
  if(process.env.MODEL_C_METRICS_FILE)await writeFile(process.env.MODEL_C_METRICS_FILE,JSON.stringify({syntheticOnly:true,measurement:'actual D1 meta.rows_written; schema setup and fixture seed excluded',scenarios:measurements,preflights},null,2)+'\n');});

describe('verified incremental importer on ephemeral D1',()=>{
  it('never interprets a remote execution target as permission to mutate D1',async()=>{
    const f=await fixture(1);
    for(const extra of [{executionTarget:'remote' as const},
      {executionTarget:'remote' as const,oneTimeFreeBootstrap:true,
        budget:{...f.options.budget,availableRows:95000}}]) {
      const result=importModelC(f.c,f.p,{...f.options,...extra});
      await expect(result).rejects.toThrow('REMOTE_IMPORT_NOT_AUTHORIZED');
    }
    expect(await count(f.c,'catalog_head')).toBe(0);
    expect(await count(f.c,'catalog_write_reservations')).toBe(0);
    expect(await count(f.p,'personal_catalog_receipts')).toBe(0);
  });
  it('bootstraps, replays with zero writes, and observes a new identical commit without a content revision',async()=>{
    const f=await fixture();const a=await importModelC(f.c,f.p,f.options);measurements.bootstrap=a.metrics;
    expect(a.status).toBe('PUBLISHED');expect(a.metrics.staging+a.metrics.promotion+a.metrics.checkpoint).toBe(a.metrics.publication);expect(await count(f.c,'catalog_vacancy_identity')).toBe(2);expect(await count(f.c,'catalog_vacancy_current')).toBe(2);
    const replay=await importModelC(f.c,f.p,f.options);measurements.replay=replay.metrics;expect(replay.metrics.total).toBe(0);expect(replay.status).toBe('REPLAY');
    const current=(await f.c.prepare('SELECT * FROM catalog_vacancy_current').all()).results;
    f.options.source.commit=commit(f.repo);const b=await importModelC(f.c,f.p,f.options);measurements.unchangedObservation=b.metrics;
    expect(b.syncRevision).toBe(2);expect(b.observation.catalogRevision).toBe(1);expect(b.observation.contentOrigin).toEqual(a.observation.contentOrigin);
    expect((await f.c.prepare('SELECT * FROM catalog_vacancy_current').all()).results).toEqual(current);
    expect(await count(f.c,'catalog_content_revisions')).toBe(1);expect(await count(f.c,'catalog_audit')).toBe(2);
    expect(await count(f.c,'catalog_stage_vacancies')).toBe(0);expect(a.metrics.total).toBeLessThanOrEqual(a.metrics.reservedBound);
  });
  it('retains APP decisions after a subsequent real GitHub synthetic import and replay',async()=>{
    const f=await fixture(1);
    const initial=await importModelC(f.c,f.p,f.options);
    expect(initial.status).toBe('PUBLISHED');
    const id=await f.c.prepare('SELECT id FROM catalog_vacancy_identity').first<string>('id');
    expect(id).toMatch(/^job:[a-f0-9]{64}$/);
    const importedHead=await f.p.prepare('SELECT revision,context_digest FROM personal_heads WHERE owner_id=?')
      .bind(f.options.owner).first();
    const importedEvents=(await f.p.prepare('SELECT * FROM personal_decision_events').all()).results;
    const local=await executePersonalCommand(f.c,f.p,{ownerId:f.options.owner},{
      kind:'DECISION',jobId:id!,catalogRevision:initial.syncRevision,expectedRevision:0,
      operationId:'00000000-0000-4000-8000-000000004141',decision:'INTERESTED',reasonSummary:null,
    });
    expect(local).toMatchObject({status:'saved',decision:'INTERESTED',jobRevision:1});
    expect(await f.p.prepare('SELECT revision,context_digest FROM personal_heads WHERE owner_id=?')
      .bind(f.options.owner).first()).toEqual(importedHead);
    f.options.source.commit=commit(f.repo);
    const subsequent=await importModelC(f.c,f.p,f.options);
    expect(subsequent.syncRevision).toBe(initial.syncRevision+1);
    expect((await getModelCPersonalJob(f.c,f.p,{ownerId:f.options.owner},id!)).job)
      .toMatchObject({decision:'INTERESTED',decisionSource:'APP',jobRevision:1});
    expect(await count(f.p,'personal_app_events')).toBe(1);
    expect(await count(f.p,'personal_app_operations')).toBe(1);
    expect((await f.p.prepare('SELECT * FROM personal_decision_events').all()).results).toEqual(importedEvents);
    const replay=await importModelC(f.c,f.p,f.options);
    expect(replay.status).toBe('REPLAY');
    expect((await getModelCPersonalJob(f.c,f.p,{ownerId:f.options.owner},id!)).job.decision).toBe('INTERESTED');
    expect(await count(f.p,'personal_app_events')).toBe(1);
  });
  it('upserts only the changed payload and preserves distinct ATS/coverage origins and company metadata',async()=>{
    const f=await fixture();await importModelC(f.c,f.p,f.options);
    const before=(await f.c.prepare('SELECT job_id,title,origin_id FROM catalog_vacancy_current ORDER BY job_id').all()).results;
    f.options.source.commit=await inventory(f.repo,jobs=>{jobs[0]!.title='Strategy Associate';});
    const result=await importModelC(f.c,f.p,f.options);measurements.minimalDelta=result.metrics;
    const after=(await f.c.prepare('SELECT job_id,title,origin_id FROM catalog_vacancy_current ORDER BY job_id').all()).results;
    expect(after.filter((r,i)=>canonical(r)!==canonical(before[i]))).toHaveLength(1);expect(result.observation.catalogRevision).toBe(2);
    const source=await f.c.prepare('SELECT a.source_path AS config,b.source_path AS coverage FROM catalog_source_current s JOIN catalog_origins a ON a.id=s.origin_id JOIN catalog_origins b ON b.id=s.coverage_origin_id').first();
    expect(source).toEqual({config:'ats_mapping_jw2.json',coverage:'current_jobs_jw2.json'});
    expect(await f.c.prepare('SELECT config_id,membership FROM catalog_company_current').first()).toMatchObject({config_id:'1',membership:'ACTIVE'});
  });
  it('measures a broad delta without splitting publication',async()=>{
    const f=await fixture(120);const initial=await importModelC(f.c,f.p,f.options);measurements.bootstrap120=initial.metrics;
    f.options.source.commit=await inventory(f.repo,jobs=>{for(const j of jobs)j.title='Strategy Associate';});
    const result=await importModelC(f.c,f.p,f.options);measurements.broadDelta120=result.metrics;
    expect(await count(f.c,'catalog_vacancy_current')).toBe(120);expect(result.metrics.total).toBeLessThanOrEqual(result.metrics.reservedBound);
    expect(await count(f.c,'catalog_audit')).toBe(2);
  });
  it('extends Python aliases without changing identity and removes only authorized current payloads',async()=>{
    const f=await fixture(1);await importModelC(f.c,f.p,f.options);
    const job=JSON.parse(await readFile(resolve(f.repo,'current_jobs_jw2.json'),'utf8')).companies[0].jobs[0];
    await writeFile(resolve(f.repo,'job_memory_jw2.json'),JSON.stringify({batch:'JW2',records:{'Amazon::old-uuid':{identity:{...job,source_id:'old-uuid'}}}}));
    f.options.source.commit=commit(f.repo);const alias=await importModelC(f.c,f.p,f.options);measurements.newAlias=alias.metrics;
    expect(await count(f.c,'catalog_vacancy_identity')).toBe(1);expect(await count(f.c,'catalog_aliases')).toBe(2);
    await writeFile(resolve(f.repo,'job_memory_jw2.json'),JSON.stringify({batch:'JW2',records:{}}));
    f.options.source.commit=await inventory(f.repo,jobs=>{jobs.length=0;});
    const removed=await importModelC(f.c,f.p,f.options);measurements.removal=removed.metrics;
    expect(await count(f.c,'catalog_vacancy_current')).toBe(0);expect(await count(f.c,'catalog_vacancy_identity')).toBe(1);expect(await count(f.c,'catalog_aliases')).toBe(2);
  });
  it('preserves OPPORTUNITY plus AI_QUEUE membership, uses active PERSONAL DISMISSED and retains closed captures/events',async()=>{
    const f=await fixture(1);await importModelC(f.c,f.p,f.options);
    const id=await f.c.prepare('SELECT id FROM catalog_vacancy_identity').first<string>('id');
    // SAVED is a PERSONAL fact; Python still reports needsAnalysis on this fixture.
    await f.p.batch([f.p.prepare("INSERT INTO personal_job_refs VALUES (?,?,NULL,NULL,'CLOSED',?,'job_memory_jw2.json',?,1)").bind(f.options.owner,id,f.options.source.commit,'a'.repeat(64)),
      f.p.prepare("INSERT INTO personal_reference_state VALUES (?,?,'SAVED',1,1)").bind(f.options.owner,id),f.p.prepare('UPDATE personal_heads SET revision=revision+1')]);
    const result=await importModelC(f.c,f.p,f.options);measurements.personalReference=result.metrics;
    expect(await f.c.prepare('SELECT kind,needs_analysis FROM catalog_vacancy_current').first()).toEqual({kind:'OPPORTUNITY',needs_analysis:1});
    expect(await f.p.prepare('SELECT state FROM personal_reconciliation').first('state')).toBe('VERIFIED');
    const captures=await f.p.prepare('SELECT * FROM personal_job_refs').all();
    await f.p.batch([f.p.prepare("INSERT INTO personal_reference_state VALUES (?,?,'DISMISSED',1,1)").bind(f.options.owner,id),f.p.prepare('UPDATE personal_heads SET revision=revision+1')]);
    await importModelC(f.c,f.p,f.options);expect(await count(f.c,'catalog_vacancy_current')).toBe(0);
    expect((await f.p.prepare('SELECT * FROM personal_job_refs').all()).results).toEqual(captures.results);
    expect(await count(f.c,'catalog_vacancy_identity')).toBe(1);
  });
  it('appends original personal facts once and never rewrites current pointers or events',async()=>{
    const f=await fixture(1), job=JSON.parse(await readFile(resolve(f.repo,'current_jobs_jw2.json'),'utf8')).companies[0].jobs[0];
    await writeFile(resolve(f.repo,'job_memory_jw2.json'),JSON.stringify({batch:'JW2',records:{'Amazon::123456':{identity:job,user:{decision:'NOT_INTERESTED',decided_at:'2026-10-29T10:00:00Z'}}}}));
    f.options.source.commit=commit(f.repo);await importModelC(f.c,f.p,f.options);
    const before=(await f.p.prepare('SELECT * FROM personal_decision_events').all()).results;expect(before).toHaveLength(1);
    expect(await count(f.c,'catalog_vacancy_current')).toBe(0);expect(await count(f.p,'personal_decision_current')).toBe(0);
    await importModelC(f.c,f.p,f.options);expect((await f.p.prepare('SELECT * FROM personal_decision_events').all()).results).toEqual(before);
  });
  it('rejects wrong hashes/proof, dirty projections and unauthorized ancestry before any write',async()=>{
    const f=await fixture(1), verified=await verifyGitProjection(f.options.source,bootstrap), before=(await captureSynthetic(f.c,'catalog')).sha256;
    const bad=structuredClone(verified.bundle);bad.manifest.files[0]!.bytes++;
    await expect(importModelC(f.c,f.p,{...f.options,source:{...f.options.source,bundle:bad}})).rejects.toThrow('PROJECTION_REPLAY_MISMATCH');
    await expect(importModelC(f.c,f.p,{...f.options,source:{...f.options.source,proof:{...verified.proof,projectionInputDigest:'f'.repeat(64)}}})).rejects.toThrow('PROJECTION_PROOF_MISMATCH');
    const dirty=structuredClone(verified.bundle);dirty.chunks[0]![0]!.sourceSha256='f'.repeat(64);
    await expect(importModelC(f.c,f.p,{...f.options,source:{...f.options.source,bundle:dirty}})).rejects.toThrow();
    expect((await captureSynthetic(f.c,'catalog')).sha256).toBe(before);
    await importModelC(f.c,f.p,f.options);const ancestor=f.options.source.commit;
    f.options.source.commit=commit(f.repo);await importModelC(f.c,f.p,f.options);
    await expect(importModelC(f.c,f.p,{...f.options,source:{...f.options.source,commit:ancestor}})).rejects.toThrow('GIT_VERIFICATION_FAILED');
    await expect(importModelC(f.c,f.p,{...f.options,source:{...f.options.source,commit:'main'}})).rejects.toThrow('EXPLICIT_COMMIT_SHA_REQUIRED');
  });
  it('rejects incomplete trusted ledger, unknown personal refs, and nonempty bootstrap',async()=>{
    const f=await fixture(1);await importModelC(f.c,f.p,f.options);
    // Fault injection of storage corruption, outside the importer.
    await f.c.prepare('DROP TRIGGER catalog_aliases_retain').run();await f.c.prepare('DELETE FROM catalog_aliases').run();
    await expect(importModelC(f.c,f.p,f.options)).rejects.toThrow('UNTRUSTED_LEDGER');
    const g=await fixture(1);
    await g.p.batch([g.p.prepare('INSERT INTO personal_owners VALUES (?)').bind(g.options.owner),g.p.prepare('INSERT INTO personal_heads VALUES (?,1,?,NULL)').bind(g.options.owner,'a'.repeat(64)),g.p.prepare("INSERT INTO personal_job_refs VALUES (?,?,NULL,NULL,NULL,?,'job_memory_jw2.json',?,1)").bind(g.options.owner,'job:'+'f'.repeat(64),g.options.source.commit,'a'.repeat(64))]);
    await expect(importModelC(g.c,g.p,g.options)).rejects.toThrow('UNRESOLVED_PERSONAL_REFERENCE');
    const h=await fixture(1);await h.c.prepare("INSERT INTO catalog_company_identity VALUES ('orphan')").run();
    await expect(importModelC(h.c,h.p,h.options)).rejects.toThrow('NONEMPTY_BOOTSTRAP_REFUSED');
  });
  it('fails insufficient and unauthorized extended budgets before any target mutation',async()=>{
    const f=await fixture(1), beforeC=(await captureSynthetic(f.c,'catalog')).sha256, beforeP=(await captureSynthetic(f.p,'personal')).sha256;
    await expect(importModelC(f.c,f.p,{...f.options,budget:{...f.options.budget,availableRows:1}})).rejects.toThrow('WRITE_BUDGET_INSUFFICIENT');
    await expect(importModelC(f.c,f.p,{...f.options,budget:{...f.options.budget,availableRows:60000}})).rejects.toThrow('INVALID_WRITE_BUDGET');
    expect((await captureSynthetic(f.c,'catalog')).sha256).toBe(beforeC);expect((await captureSynthetic(f.p,'personal')).sha256).toBe(beforeP);
  });
  it('rolls back incomplete staging and recovers on retry without orphan revisions',async()=>{
    const f=await fixture(1);
    // A missing marker is a real incomplete-staging failure inside the atomic batch.
    const faulty=intercept(f.c,async(sql,actual)=>{if(sql.some(s=>s.includes("state='READY'"))){
      await f.c.prepare("CREATE TRIGGER synthetic_missing_chunks BEFORE INSERT ON catalog_chunks BEGIN SELECT RAISE(IGNORE); END").run();
      try{return await actual();}finally{await f.c.prepare('DROP TRIGGER synthetic_missing_chunks').run();}
    }return actual();});
    await expect(importModelC(faulty,f.p,f.options)).rejects.toThrow('INCOMPLETE_STAGING');
    expect(await count(f.c,'catalog_head')).toBe(0);expect(await count(f.c,'catalog_runs')).toBe(0);expect(await count(f.c,'catalog_content_revisions')).toBe(0);
    await importModelC(f.c,f.p,f.options);expect(await count(f.c,'catalog_audit')).toBe(1);
  });
  it('rolls back a late SQL error after current writes, retaining confirmed state for retry',async()=>{
    const f=await fixture(1);await importModelC(f.c,f.p,f.options);const before=(await f.c.prepare('SELECT * FROM catalog_vacancy_current').all()).results;
    f.options.source.commit=await inventory(f.repo,jobs=>{jobs[0]!.title='Strategy Associate';});
    await f.c.prepare("CREATE TRIGGER synthetic_failure BEFORE UPDATE ON catalog_head BEGIN SELECT RAISE(ABORT,'synthetic_late_failure'); END").run();
    await expect(importModelC(f.c,f.p,f.options)).rejects.toThrow('MODEL_C_IMPORT_FAILED');
    expect((await f.c.prepare('SELECT * FROM catalog_vacancy_current').all()).results).toEqual(before);expect(await count(f.c,'catalog_audit')).toBe(1);
    await f.c.prepare('DROP TRIGGER synthetic_failure').run();await importModelC(f.c,f.p,f.options);expect(await count(f.c,'catalog_audit')).toBe(2);
  });
  it('allows one concurrent CAS winner and safely recovers the loser',async()=>{
    const f=await fixture(1);await importModelC(f.c,f.p,f.options);f.options.source.commit=commit(f.repo);let arrived=0;let release:()=>void=()=>{};const gate=new Promise<void>(r=>{release=r;});
    const gated=intercept(f.c,async(sql,actual)=>{if(sql.some(s=>s.includes('INSERT INTO catalog_cas_guard'))){if(++arrived===2)release();await gate;}return actual();});
    const results=await Promise.allSettled([importModelC(gated,f.p,f.options),importModelC(gated,f.p,f.options)]);
    expect(results.filter(r=>r.status==='fulfilled')).toHaveLength(1);expect(await count(f.c,'catalog_audit')).toBe(2);
    expect((await importModelC(f.c,f.p,f.options)).status).toBe('REPLAY');
  });
  it('recovers after publication before receipt and after cleanup failure without republishing',async()=>{
    const f=await fixture(1);
    const failReceipt=intercept(f.p,async(sql,actual)=>{if(sql.some(s=>s.startsWith('INSERT INTO personal_catalog_receipts')))throw Error('SYNTHETIC_RECEIPT_INTERRUPTION');return actual();});
    await expect(importModelC(f.c,failReceipt,f.options)).rejects.toThrow('SYNTHETIC_RECEIPT_INTERRUPTION');expect(await count(f.c,'catalog_audit')).toBe(1);
    const failCleanup=intercept(f.c,async(sql,actual)=>{if(sql.some(s=>s.startsWith('DELETE FROM catalog_stage_')))throw Error('SYNTHETIC_CLEANUP_INTERRUPTION');return actual();});
    await expect(importModelC(failCleanup,f.p,f.options)).rejects.toThrow('SYNTHETIC_CLEANUP_INTERRUPTION');
    const result=await importModelC(f.c,f.p,f.options);measurements.cleanupRecovery=result.metrics;
    expect(result.status).toBe('RECOVERED');expect(result.metrics.publication).toBe(0);expect(result.metrics.cleanup).toBeGreaterThan(0);expect(await count(f.c,'catalog_audit')).toBe(1);
  });
  it('migrates the complete confirmed v1 ledger and historical personal facts without changing v1',async()=>{
    const f=await fixture(1), job=JSON.parse(await readFile(resolve(f.repo,'current_jobs_jw2.json'),'utf8')).companies[0].jobs[0];
    await writeFile(resolve(f.repo,'job_memory_jw2.json'),JSON.stringify({batch:'JW2',records:{'Amazon::123456':{identity:job,user:{decision:'NOT_INTERESTED',decided_at:'2026-10-29T10:00:00Z'}}}}));
    f.options.source.commit=commit(f.repo);
    const v1=await runtime.getD1Database('DB'+seq++);await applySchema(v1,'v1');
    const original=await verifyGitProjection(f.options.source,bootstrap);
    await importSnapshot(v1,original.bundle,{expectedRevision:0,verifyAdvance:async()=>true});
    const before=(await captureSynthetic(v1,'v1')).sha256;
    await writeFile(resolve(f.repo,'job_memory_jw2.json'),JSON.stringify({batch:'JW2',records:{}}));
    f.options.source.commit=await inventory(f.repo,jobs=>{jobs.length=0;});
    const result=await importModelC(f.c,f.p,{...f.options,v1});measurements.v1Migration=result.metrics;
    expect(await f.c.prepare('SELECT id FROM catalog_vacancy_identity').first('id')).toBe(await v1.prepare('SELECT id FROM jobs').first('id'));
    expect(await count(f.c,'catalog_vacancy_current')).toBe(0);expect(await count(f.p,'personal_decision_events')).toBe(1);
    expect(await f.p.prepare('SELECT decision FROM personal_decision_events').first('decision')).toBe('NOT_INTERESTED');
    expect((await captureSynthetic(v1,'v1')).sha256).toBe(before);
    expect((await importModelC(f.c,f.p,{...f.options,v1})).status).toBe('REPLAY');
  });
  it('keeps historical V1 decisions UNRESOLVED_PERSONAL on first import, persisted state and replay',async()=>{
    const f=await fixture(1), path=resolve(f.repo,'job_memory_jw2.json');
    const job=JSON.parse(await readFile(resolve(f.repo,'current_jobs_jw2.json'),'utf8')).companies[0].jobs[0];
    await writeFile(path,JSON.stringify({batch:'JW2',records:{'Amazon::123456':{identity:job,user:{decision:'NOT_INTERESTED',decided_at:'2026-10-29T10:00:00Z'}}}}));
    f.options.source.commit=commit(f.repo);
    const v1=await runtime.getD1Database('DB'+seq++);await applySchema(v1,'v1');
    await importSnapshot(v1,(await verifyGitProjection(f.options.source,bootstrap)).bundle,{expectedRevision:0,verifyAdvance:async()=>true});
    const v1Before=(await captureSynthetic(v1,'v1')).sha256;
    const semantic={fingerprint:job.fingerprint,analysis_status:'ANALYZED',analysis_method:'chatgpt_semantic_full_jd',fit_score:90,
      experience_required:null,mandatory_years_experience:null,preferred_years_experience:null,mandatory_vs_preferred_requirements:null,
      people_management_required:false,individual_contributor_possible:true,decision_scope_and_ownership:null,role_level_assessment:'ENTRY_JUNIOR',
      seniority_evidence:'Synthetic junior role',final_experience_status:'TARGET_0_5',salary:null,salary_source:null,reportable:true,
      rationale:'Synthetic bounded assessment',analyzed_at:'2026-10-29T11:00:00Z'};
    await writeFile(path,JSON.stringify({batch:'JW2',records:{'Amazon::123456':{identity:job,semantic}}}));
    f.options.source.commit=commit(f.repo);
    const next=await verifyGitProjection(f.options.source,bootstrap), projected=next.bundle.chunks.flat().find(r=>r.kind==='job')!;
    expect(projected).toMatchObject({lifecycle:'STILL_OPEN',reportable:true,effectiveDecision:null});
    expect(next.bundle.chunks.flat().some(r=>r.kind==='user')).toBe(false);
    const id=String(await v1.prepare('SELECT id FROM jobs').first('id'));
    const selected=await selectModelC(next.bundle,{...bootstrap,personalDecisionJobIds:[id]});
    expect(selected.subjects).toMatchObject([{personal:true,exclusion:'UNRESOLVED_PERSONAL',catalog:false,aiQueue:false}]);
    const result=await importModelC(f.c,f.p,{...f.options,v1,oneTimeFreeBootstrap:true,executionTarget:'local-ephemeral',budget:{...f.options.budget,availableRows:95000}});
    expect(result.status).toBe('PUBLISHED');expect(await count(f.c,'catalog_vacancy_current')).toBe(0);
    expect(await f.p.prepare('SELECT decision FROM personal_decision_events').first('decision')).toBe('NOT_INTERESTED');
    expect(await count(f.p,'personal_reference_state')).toBe(0);expect(await count(f.p,'personal_decision_current')).toBe(0);
    expect(await count(f.p,'personal_job_refs')).toBe(1);
    const state=(await captureSynthetic(f.p,'personal')).sha256;
    const replay=await importModelC(f.c,f.p,{...f.options,v1});
    expect(replay.status).toBe('REPLAY');expect(replay.metrics.total).toBe(0);expect(replay.observation).toEqual(result.observation);
    expect((await captureSynthetic(f.p,'personal')).sha256).toBe(state);expect((await captureSynthetic(v1,'v1')).sha256).toBe(v1Before);
    expect((await selectModelC(next.bundle,{...bootstrap,personalDecisionJobIds:[id]})).subjects[0]!.exclusion).toBe('UNRESOLVED_PERSONAL');
  });
  it('rejects two PERSONAL owners with divergent active choices before projection or writes',async()=>{
    const f=await fixture(1);await importModelC(f.c,f.p,f.options);
    const id=await f.c.prepare('SELECT id FROM catalog_vacancy_identity').first<string>('id');
    for(const [owner,kind] of [[f.options.owner,'SAVED'],['other-synthetic-owner','DISMISSED']] as const) {
      if(owner!==f.options.owner)await f.p.prepare('INSERT INTO personal_owners VALUES (?)').bind(owner).run();
      await f.p.prepare("INSERT INTO personal_job_refs VALUES (?,?,NULL,NULL,'STILL_OPEN',?,'job_memory_jw2.json',?,1)").bind(owner,id,f.options.source.commit,'a'.repeat(64)).run();
      await f.p.prepare('INSERT INTO personal_reference_state VALUES (?,?,?,1,1)').bind(owner,id,kind).run();
      if(owner!==f.options.owner)await f.p.prepare('INSERT INTO personal_heads VALUES (?,1,?,NULL)').bind(owner,'a'.repeat(64)).run();
    }
    const beforeC=(await captureSynthetic(f.c,'catalog')).sha256, beforeP=(await captureSynthetic(f.p,'personal')).sha256;
    for(const owner of [f.options.owner,'other-synthetic-owner'])await expect(importModelC(f.c,f.p,{...f.options,owner})).rejects.toThrow('MULTI_OWNER_PERSONAL_UNSUPPORTED');
    expect((await captureSynthetic(f.c,'catalog')).sha256).toBe(beforeC);expect((await captureSynthetic(f.p,'personal')).sha256).toBe(beforeP);
    expect(await count(f.c,'catalog_vacancy_current')).toBe(1);
  });
  it('attempts the complete baseline bootstrap and refuses its verified write bound without partial publication',async()=>{
    const f=await fixture(5454,'baseline'), verified=await verifyGitProjection(f.options.source,bootstrap);
    const selected=await selectModelC(verified.bundle,bootstrap);
    expect(selected.ledger.identities).toHaveLength(5454);expect(selected.ledger.mappings).toHaveLength(5474);expect(selected.catalog).toHaveLength(151);
    let failure:ModelCImportError|undefined;
    try {await importModelC(f.c,f.p,{...f.options,source:{...f.options.source,bundle:verified.bundle},budget:{...f.options.budget,availableRows:60000,extendedAuthorized:true}});}
    catch(error) {if(!(error instanceof ModelCImportError))throw error;failure=error;}
    expect(failure?.message).toBe('WRITE_BUDGET_INSUFFICIENT');
    expect(failure!.metrics.publicationStatements).toBeLessThan(8000);expect(failure!.metrics.publicationBytes).toBeLessThan(8*1024*1024);
    expect(failure!.metrics.maxStatementParameters).toBeLessThanOrEqual(80);expect(failure!.metrics.maxStatementSqlBytes).toBeLessThanOrEqual(64*1024);
    expect(failure!.metrics.requiredBound).toBeGreaterThan(60000);
    expect(failure!.metrics.total).toBe(0);expect(failure!.metrics.reservedBound).toBe(0);
    expect(failure!.metrics.writeUnits.catalog_vacancy_identity!.rows).toBe(5454);
    expect(failure!.metrics.writeUnits.catalog_aliases!.rows).toBe(5474);
    expect(failure!.metrics.writeUnits.catalog_stage_vacancies!.rows).toBe(5454*2); // stage plus cleanup
    expect(failure!.metrics.writeUnits.catalog_stage_aliases!.rows).toBe(5474*2);
    expect(Object.values(failure!.metrics.writeBounds).reduce((n,r)=>n+r,0)).toBe(failure!.metrics.requiredBound);
    for(const t of ['catalog_head','catalog_runs','catalog_write_reservations','catalog_vacancy_identity','catalog_aliases','catalog_stage_vacancies','catalog_ledger_checkpoints','catalog_audit'])expect(await count(f.c,t)).toBe(0);
    expect(await count(f.p,'personal_owners')).toBe(0);
    preflights.baseline={syntheticOnly:true,identities:5454,mappings:5474,currentVacancies:151,before:{statements:22025,serializedPlanBytes:6986391},
      metrics:failure!.metrics,limits:{statements:8000,serializedPlanBytes:8*1024*1024,parametersPerStatement:80,sqlBytesPerStatement:64*1024,ordinaryWrites:30000,extendedWrites:60000},
      reason:failure!.message,requiredWriteBound:failure!.metrics.requiredBound,budgetReserved:0,d1Writes:0,
      scope:'Complete verified baseline plan; one synthetic company/source. No real bootstrap cost claim: write admission refused before mutation'};
  },60000);
  it('publishes the full baseline only with oneTimeFreeBootstrap, preserves the ledger and replays without the exception',async()=>{
    const f=await fixture(5454,'baseline'), options:ImportOptions={...f.options,oneTimeFreeBootstrap:true,executionTarget:'local-ephemeral',budget:{...f.options.budget,availableRows:95000}};
    const verified=await verifyGitProjection(f.options.source,bootstrap), selected=await selectModelC(verified.bundle,bootstrap);
    expect(selected.ledger.identities).toHaveLength(5454);expect(selected.ledger.mappings).toHaveLength(5474);expect(selected.catalog).toHaveLength(151);
    const plan=await importModelC(f.c,f.p,{...options,preflightOnly:true,executionTarget:'remote'});
    expect(plan.status).toBe('PREFLIGHT');expect(plan.metrics.requiredBound).toBe(94173);expect(plan.metrics.total).toBe(0);
    expect(assessFreeBootstrapRemoteQuota({preflight:plan}).status).toBe('QUOTA_VERIFICATION_REQUIRED');
    expect(await count(f.c,'catalog_initial_bootstrap_reservations')).toBe(0);expect(await count(f.p,'personal_owners')).toBe(0);
    await expect(importModelC(f.c,f.p,{...options,budget:{...options.budget,availableRows:plan.metrics.requiredBound-1}})).rejects.toThrow('WRITE_BUDGET_INSUFFICIENT');
    const result=await importModelC(f.c,f.p,options);measurements.freeBootstrapFull=result.metrics;
    expect(result.status).toBe('PUBLISHED');expect(result.metrics.requiredBound).toBeLessThanOrEqual(95000);
    expect(result.metrics.total).toBeLessThanOrEqual(result.metrics.reservedBound);expect(result.metrics.reservedBound).toBe(94173);
    const ids=(await f.c.prepare('SELECT id AS jobId,company_id AS companyId,origin_job_key AS originJobKey FROM catalog_vacancy_identity ORDER BY id').all()).results;
    const mappings=(await f.c.prepare('SELECT alias_key AS key,job_id AS jobId FROM catalog_aliases ORDER BY alias_key').all()).results;
    expect(ids).toHaveLength(5454);expect(mappings).toHaveLength(5474);expect(await sha256(canonical({identities:ids,mappings}))).toBe(selected.ledgerDigest);
    expect((await f.c.prepare('SELECT job_id AS jobId,kind FROM catalog_vacancy_current ORDER BY job_id').all()).results).toEqual(selected.catalog);
    expect(await f.c.prepare('SELECT state FROM catalog_runs').first('state')).toBe('PUBLISHED');
    expect(await f.c.prepare('SELECT sync_revision,content_revision,ledger_revision FROM catalog_head').first()).toEqual({sync_revision:1,content_revision:1,ledger_revision:1});
    expect(await f.c.prepare('SELECT ledger_digest,identity_count,mapping_count FROM catalog_ledger_checkpoints').first()).toEqual({ledger_digest:selected.ledgerDigest,identity_count:5454,mapping_count:5474});
    expect(await count(f.c,'catalog_audit')).toBe(1);expect(await count(f.c,'catalog_stage_vacancies')).toBe(0);expect(await count(f.c,'catalog_stage_aliases')).toBe(0);
    expect(await f.c.prepare('SELECT charged FROM catalog_write_totals').first('charged')).toBe(94173);
    expect(await count(f.c,'catalog_write_reservations')).toBe(0);expect(await count(f.c,'catalog_initial_bootstrap_reservations')).toBe(1);
    expect(await f.c.prepare('SELECT observed_commit,manifest_digest,projection_digest FROM catalog_initial_bootstrap_reservations').first()).toEqual({observed_commit:plan.provenance?.observedCommit,manifest_digest:plan.provenance?.manifestDigest,projection_digest:plan.provenance?.projectionDigest});
    expect((await f.c.prepare('PRAGMA foreign_key_check').all()).results).toHaveLength(0);
    const replay=await importModelC(f.c,f.p,{...f.options});measurements.freeBootstrapReplay=replay.metrics;
    expect(replay.status).toBe('REPLAY');expect(replay.metrics.total).toBe(0);
    expect(replay.observation.catalogContentDigest).toBe(result.observation.catalogContentDigest);expect(replay.observation.contentOrigin).toEqual(result.observation.contentOrigin);
    expect(replay.observation.catalogRevision).toBe(1);expect(await count(f.c,'catalog_runs')).toBe(1);
    await expect(importModelC(f.c,f.p,options)).rejects.toThrow('ONE_TIME_BOOTSTRAP_NOT_INITIAL');
    f.options.source.commit=commit(f.repo);
    await expect(importModelC(f.c,f.p,{...options,source:f.options.source})).rejects.toThrow('ONE_TIME_BOOTSTRAP_NOT_INITIAL');
    await expect(importModelC(f.c,f.p,f.options)).rejects.toThrow('WRITE_BUDGET_INSUFFICIENT');
    expect(await count(f.c,'catalog_audit')).toBe(1);
    preflights.freeBootstrap={status:'PUBLISHED',identities:5454,mappings:5474,currentVacancies:151,requiredBound:result.metrics.requiredBound,
      actualRowsWritten:result.metrics.total,budgetReserved:result.metrics.reservedBound,schemaCosts:f.schemaCosts,remoteQuotaStatus:'QUOTA_VERIFICATION_REQUIRED',
      scope:'Actual complete synthetic bootstrap; schema setup is measured separately and is not part of importer rows or account-wide evidence'};
  },90000);
  it('requires explicit bootstrap authorization and local target; preflight remains read-only',async()=>{
    const f=await fixture(1);
    const options:ImportOptions={...f.options,oneTimeFreeBootstrap:true,executionTarget:'local-ephemeral',budget:{...f.options.budget,availableRows:95000}};
    await expect(importModelC(f.c,f.p,{...options,oneTimeFreeBootstrap:false})).rejects.toThrow('INVALID_WRITE_BUDGET');
    await expect(importModelC(f.c,f.p,{...options,executionTarget:'remote'})).rejects.toThrow('REMOTE_IMPORT_NOT_AUTHORIZED');
    const {executionTarget:omitted,...noTarget}=options;expect(omitted).toBe('local-ephemeral');
    await expect(importModelC(f.c,f.p,noTarget)).rejects.toThrow('REMOTE_IMPORT_NOT_AUTHORIZED');
    await expect(importModelC(f.c,f.p,{...options,budget:{...options.budget,availableRows:95001}})).rejects.toThrow('INVALID_WRITE_BUDGET');
    await expect(importModelC(f.c,f.p,{...options,source:{...options.source,commit:'main'}})).rejects.toThrow('EXPLICIT_COMMIT_SHA_REQUIRED');
    expect(await count(f.c,'catalog_initial_bootstrap_reservations')).toBe(0);expect(await count(f.c,'catalog_head')).toBe(0);expect(await count(f.p,'personal_owners')).toBe(0);
  });
  it('keeps failed initial reservations charged, rolls back publication and does not give retries a fresh ceiling',async()=>{
    const f=await fixture(2), options:ImportOptions={...f.options,oneTimeFreeBootstrap:true,executionTarget:'local-ephemeral',budget:{...f.options.budget,availableRows:200}};
    const plan=await importModelC(f.c,f.p,{...options,preflightOnly:true});expect(plan.metrics.requiredBound).toBeLessThanOrEqual(200);
    await f.c.prepare("CREATE TRIGGER synthetic_initial_failure BEFORE INSERT ON catalog_head BEGIN SELECT RAISE(ABORT,'synthetic_initial_failure'); END").run();
    await expect(importModelC(f.c,f.p,options)).rejects.toThrow('MODEL_C_IMPORT_FAILED');
    for(const t of ['catalog_head','catalog_runs','catalog_vacancy_identity','catalog_aliases','catalog_audit','catalog_stage_vacancies','catalog_content_revisions'])expect(await count(f.c,t)).toBe(0);
    expect(await count(f.c,'catalog_initial_bootstrap_reservations')).toBe(1);
    expect(await f.c.prepare('SELECT charged FROM catalog_write_totals').first('charged')).toBe(plan.metrics.requiredBound);
    await f.c.prepare('DROP TRIGGER synthetic_initial_failure').run();
    await expect(importModelC(f.c,f.p,options)).rejects.toThrow('WRITE_BUDGET_INSUFFICIENT');
    expect(await count(f.c,'catalog_initial_bootstrap_reservations')).toBe(1);
    const recovered=await importModelC(f.c,f.p,{...options,budget:{...options.budget,availableRows:95000}});
    expect(recovered.status).toBe('PUBLISHED');expect(await count(f.c,'catalog_audit')).toBe(1);
    expect(await f.c.prepare('SELECT charged FROM catalog_write_totals').first('charged')).toBe(plan.metrics.requiredBound+recovered.metrics.reservedBound);
    await expect(f.c.prepare('DELETE FROM catalog_initial_bootstrap_reservations').run()).rejects.toThrow('permanent_write_reservation');
    await expect(f.c.prepare('UPDATE catalog_initial_bootstrap_reservations SET rows_bound=1').run()).rejects.toThrow('immutable_write_reservation');
    await expect(f.c.prepare('INSERT INTO catalog_initial_bootstrap_reservations SELECT ?,day,1,95000,observed_commit,manifest_digest,projection_digest FROM catalog_initial_bootstrap_reservations LIMIT 1').bind('after-head').run()).rejects.toThrow('initial_bootstrap_already_published');
  });
  it('publishes a 3000-identity bootstrap within the authorized budget and verifies replay, delta and full rollback',async()=>{
    const f=await fixture(3000,'baseline');
    const options={...f.options,budget:{...f.options.budget,availableRows:60000,extendedAuthorized:true}};
    const verified=await verifyGitProjection(f.options.source,bootstrap), selected=await selectModelC(verified.bundle,bootstrap);
    const first=await importModelC(f.c,f.p,options);measurements.bootstrap3000=first.metrics;
    expect(first.status).toBe('PUBLISHED');expect(first.metrics.reservedBound).toBeLessThanOrEqual(60000);
    expect(first.metrics.total).toBeLessThanOrEqual(first.metrics.reservedBound);
    expect(first.metrics.staging+first.metrics.promotion+first.metrics.checkpoint).toBe(first.metrics.publication);
    const ids=(await f.c.prepare('SELECT id AS jobId,company_id AS companyId,origin_job_key AS originJobKey FROM catalog_vacancy_identity ORDER BY id').all()).results;
    const mappings=(await f.c.prepare('SELECT alias_key AS key,job_id AS jobId FROM catalog_aliases ORDER BY alias_key').all()).results;
    expect(await sha256(canonical({identities:ids,mappings}))).toBe(selected.ledgerDigest);
    expect(ids).toHaveLength(3000);expect(mappings).toHaveLength(3020);
    expect((await f.c.prepare('SELECT job_id AS jobId,kind FROM catalog_vacancy_current ORDER BY job_id').all()).results).toEqual(selected.catalog);
    expect(await count(f.c,'catalog_vacancy_current')).toBe(151);
    expect(await f.c.prepare('SELECT state FROM catalog_runs').first('state')).toBe('PUBLISHED');
    expect(await f.c.prepare('SELECT sync_revision,content_revision,ledger_revision FROM catalog_head').first()).toEqual({sync_revision:1,content_revision:1,ledger_revision:1});
    expect(await f.c.prepare('SELECT ledger_digest,identity_count,mapping_count FROM catalog_ledger_checkpoints').first()).toEqual({ledger_digest:selected.ledgerDigest,identity_count:3000,mapping_count:3020});
    expect(await count(f.c,'catalog_audit')).toBe(1);expect(await count(f.c,'catalog_stage_vacancies')).toBe(0);expect(await count(f.c,'catalog_stage_aliases')).toBe(0);
    expect((await f.c.prepare('PRAGMA foreign_key_check').all()).results).toHaveLength(0);
    const replay=await importModelC(f.c,f.p,options);measurements.replay3000=replay.metrics;
    expect(replay.status).toBe('REPLAY');expect(replay.metrics.total).toBe(0);
    f.options.source.commit=await inventory(f.repo,jobs=>{jobs[0]!.title='Strategy Associate';});options.source=f.options.source;
    const tables=['catalog_head','catalog_runs','catalog_origins','catalog_run_proofs','catalog_content_revisions','catalog_ledger_checkpoints','catalog_vacancy_identity','catalog_aliases','catalog_vacancy_current','catalog_audit'];
    const state=async()=>sha256(canonical((await f.c.batch(tables.map(t=>f.c.prepare('SELECT * FROM '+t)))).map(r=>r.results)));
    const before=await state();
    await f.c.prepare("CREATE TRIGGER synthetic_bulk_failure BEFORE UPDATE ON catalog_head BEGIN SELECT RAISE(ABORT,'synthetic_bulk_failure'); END").run();
    await expect(importModelC(f.c,f.p,options)).rejects.toThrow('MODEL_C_IMPORT_FAILED');
    expect(await state()).toBe(before);expect(await count(f.c,'catalog_audit')).toBe(1);expect(await count(f.c,'catalog_stage_vacancies')).toBe(0);
    await f.c.prepare('DROP TRIGGER synthetic_bulk_failure').run();
    const delta=await importModelC(f.c,f.p,options);measurements.delta3000=delta.metrics;
    expect(delta.syncRevision).toBe(2);expect(await count(f.c,'catalog_vacancy_identity')).toBe(3000);expect(await count(f.c,'catalog_aliases')).toBe(3020);
    expect(await f.c.prepare('SELECT charged FROM catalog_write_days').first('charged')).toBeLessThanOrEqual(60000);
  },60000);
  it('refuses unconfirmed identities from a v1 staging import',async()=>{
    const f=await fixture(1), v1=await runtime.getD1Database('DB'+seq++);await applySchema(v1,'v1');
    const original=await verifyGitProjection(f.options.source,bootstrap);
    await importSnapshot(v1,original.bundle,{expectedRevision:0,verifyAdvance:async()=>true});
    await v1.prepare("INSERT INTO jobs(id,company_id,origin_job_key) SELECT 'job:'||?,company_id,'Amazon::unconfirmed' FROM jobs LIMIT 1").bind('f'.repeat(64)).run();
    await expect(importModelC(f.c,f.p,{...f.options,v1})).rejects.toThrow('V1_UNCONFIRMED_LEDGER');
    expect(await count(f.c,'catalog_write_reservations')).toBe(0);
  });
  it('enforces the shared daily budget across attempts and admits the explicitly authorized extended ceiling',async()=>{
    const f=await fixture(1);await importModelC(f.c,f.p,f.options);
    const charged=Number(await f.c.prepare('SELECT charged FROM catalog_write_days').first('charged'));
    f.options.source.commit=commit(f.repo);
    await expect(importModelC(f.c,f.p,{...f.options,budget:{...f.options.budget,availableRows:charged+1}})).rejects.toThrow('WRITE_BUDGET_INSUFFICIENT');
    expect(await count(f.c,'catalog_audit')).toBe(1);
    await importModelC(f.c,f.p,{...f.options,budget:{...f.options.budget,availableRows:60000,extendedAuthorized:true}});
    expect(Number(await f.c.prepare('SELECT charged FROM catalog_write_days').first('charged'))).toBeGreaterThan(charged);
  });
  it('rejects PERSONAL races atomically and keeps the catalog unpublished',async()=>{
    const f=await fixture(1);let injected=false;
    const racing=intercept(f.p,async(sql,actual)=>{
      if(!injected&&sql.some(s=>s.startsWith('INSERT INTO personal_import_assert'))){injected=true;await f.p.prepare("INSERT INTO personal_owners VALUES ('concurrent-owner')").run();}
      return actual();
    });
    await expect(importModelC(f.c,racing,f.options)).rejects.toThrow('IMPORT_ASSERTION_FAILED');
    expect(await count(f.c,'catalog_head')).toBe(0);expect(await count(f.p,'personal_heads')).toBe(0);
  });
  it('does not adopt a PERSONAL writer that races just after the append transaction',async()=>{
    const f=await fixture(1);let injected=false;
    const racing=intercept(f.p,async(sql,actual)=>{
      const result=await actual();
      if(!injected&&sql.some(s=>s.startsWith('INSERT INTO personal_owners'))){injected=true;await f.p.prepare('UPDATE personal_heads SET revision=revision+1').run();}
      return result;
    });
    await expect(importModelC(f.c,racing,f.options)).rejects.toThrow('PERSONAL_CONTEXT_CHANGED');
    expect(await count(f.c,'catalog_head')).toBe(0);expect(await count(f.p,'personal_heads')).toBe(1);
    await importModelC(f.c,f.p,f.options);expect(await count(f.c,'catalog_audit')).toBe(1);
  });
  it('rejects divergent history, mismatched commits, symlinks and changed runtime proof without leaking payloads',async()=>{
    const f=await fixture(1), a=f.options.source.commit;await importModelC(f.c,f.p,f.options);
    f.options.source.commit=commit(f.repo);await importModelC(f.c,f.p,f.options);
    git(f.repo,'checkout','-q','-b','synthetic-fork',a);f.options.source.commit=commit(f.repo);
    await expect(importModelC(f.c,f.p,f.options)).rejects.toThrow('GIT_VERIFICATION_FAILED');
    const g=await fixture(1), verified=await verifyGitProjection(g.options.source,bootstrap);
    const proof=structuredClone(verified.proof);proof.inputs.runtime.python='untrusted-runtime';
    await expect(importModelC(g.c,g.p,{...g.options,source:{...g.options.source,proof}})).rejects.toThrow('PROJECTION_PROOF_MISMATCH');
    await writeFile(resolve(g.repo,'private-marker.json'),JSON.stringify({marker:'SYNTHETIC_PRIVATE_VALUE'}));g.options.source.commit=commit(g.repo);
    await expect(importModelC(g.c,g.p,{...g.options,source:{...g.options.source,bundle:verified.bundle}})).rejects.toThrow('COMMIT_MISMATCH');
    execFileSync('ln',['-s','job_watch_rules.json',resolve(g.repo,'symlink.json')]);g.options.source.commit=commit(g.repo);
    await expect(importModelC(g.c,g.p,g.options)).rejects.toThrow('UNSUPPORTED_SOURCE_MODE');
    expect(await count(g.c,'catalog_write_reservations')).toBe(0);
  });
  it('retains approved statement, parameter and 8 MiB admission limits after compaction',()=>{
    const small={sql:'SELECT ?',values:['x'.repeat(18000)],writes:{}};
    expect(()=>inspectCatalogPlan(Array.from({length:512},()=>small))).toThrow('ATOMIC_PUBLICATION_LIMIT');
    expect(()=>inspectCatalogPlan(Array.from({length:8001},()=>({sql:'SELECT 1',values:[],writes:{}})))).toThrow('ATOMIC_PUBLICATION_LIMIT');
    expect(()=>inspectCatalogPlan([{sql:'SELECT 1 /*'+'x'.repeat(65536)+'*/',values:[],writes:{}}])).toThrow('STATEMENT_LIMIT');
    expect(()=>inspectCatalogPlan([{sql:'SELECT '+Array(81).fill('?').join('+'),values:Array(81).fill(1),writes:{}}])).toThrow('STATEMENT_LIMIT');
  });
  it('rolls back missing rows from a multi-row stage insert, not just missing chunk markers',async()=>{
    const f=await fixture(5);
    await f.c.prepare("CREATE TRIGGER synthetic_missing_alias BEFORE INSERT ON catalog_stage_aliases WHEN NEW.alias_key='Amazon::123457' BEGIN SELECT RAISE(IGNORE); END").run();
    await expect(importModelC(f.c,f.p,f.options)).rejects.toThrow('IMPORT_ASSERTION_FAILED');
    for(const t of ['catalog_head','catalog_runs','catalog_vacancy_identity','catalog_aliases','catalog_audit','catalog_stage_aliases'])expect(await count(f.c,t)).toBe(0);
    await f.c.prepare('DROP TRIGGER synthetic_missing_alias').run();
    await importModelC(f.c,f.p,f.options);expect(await count(f.c,'catalog_vacancy_identity')).toBe(5);expect(await count(f.c,'catalog_aliases')).toBe(5);
  });
  it('invalidates projection input on a code-only commit without manufacturing content changes',async()=>{
    const f=await fixture(1);const first=await importModelC(f.c,f.p,f.options);
    const path=resolve(f.repo,'sync_analysis_state.py');await writeFile(path,(await readFile(path,'utf8'))+'\n# synthetic implementation-only change\n');f.options.source.commit=commit(f.repo);
    const next=await importModelC(f.c,f.p,f.options);
    expect(next.observation.catalogRevision).toBe(first.observation.catalogRevision);expect(next.observation.projectionInputDigest).not.toBe(first.observation.projectionInputDigest);
  });
});

describe('M47 trusted Git replay vs persisted M46 staging, isolated D1',()=>{
  async function prepared(){
    const f=await fixture(1);
    const preflight=await importModelC(f.c,f.p,{...f.options,
      preflightOnly:true,oneTimeFreeBootstrap:true,executionTarget:'remote'});
    if(preflight.status!=='PREFLIGHT')throw Error('SYNTHETIC_PREFLIGHT_REQUIRED');
    const setup={
      catalog:{migrationFiles:5,localRowsWritten:f.schemaCosts.catalog.rowsWritten,
        remoteUpperBound:f.schemaCosts.catalog.rowsWritten+100},
      personal:{migrationFiles:3,localRowsWritten:f.schemaCosts.personal.rowsWritten,
        remoteUpperBound:f.schemaCosts.personal.rowsWritten+100},
    };
    const trustedPlan=await prepareSafeRemoteBootstrapPlan(preflight,setup);
    const context={identities:{mode:'first-v1-bootstrap' as const},
      personalReferences:[],personalDecisionJobIds:[]};
    const verified=await verifyGitProjection(f.options.source,context);
    const selected=await selectModelC(verified.bundle,context);
    const records=projectTrustedInventoryV1(verified.bundle,selected);
    const packet=await prepareOfflineIngestPackets({
      commitSha:verified.proof.observedGitCommit,
      manifestDigest:verified.proof.sourceManifestDigest,
      projectionDigest:verified.proof.projectionInputDigest,
      planDigest:trustedPlan.digest,expectedRevision:0,
    },records,8);
    await f.c.prepare(`INSERT INTO catalog_ingest_runs
      (id,commit_sha,manifest_digest,projection_digest,plan_digest,expected_revision,
       total_chunks,principal_digest,run_digest) VALUES (?,?,?,?,?,?,?,?,?)`)
      .bind(packet.run.runId,packet.run.commitSha,packet.run.manifestDigest,
        packet.run.projectionDigest,packet.run.planDigest,packet.run.expectedRevision,
        packet.run.totalChunks,'a'.repeat(64),await sha256(canonical(packet.run))).run();
    const append=async(index:number,alter?:{title?:string})=>{
      const original=packet.chunks[index]!;
      let chunk=original;
      if(alter){
        const records=original.records.map(r=>r.kind==='job'?{...r,title:alter.title??r.title}:r);
        const digest=await sha256(canonical(records));
        chunk={...original,records:records as typeof original.records,chunkDigest:digest,
          idempotencyKey:await sha256(canonical({runId:original.runId,chunkIndex:index,chunkDigest:digest}))};
      }
      await f.c.prepare(`INSERT INTO catalog_ingest_chunks
        (run_id,chunk_index,chunk_digest,idempotency_key,record_count,records_json)
        VALUES (?,?,?,?,?,?)`).bind(
          chunk.runId,chunk.chunkIndex,chunk.chunkDigest,chunk.idempotencyKey,
          chunk.records.length,canonical(chunk.records)).run();
    };
    return {f,packet,trustedPlan,append};
  }
  it('binds a complete staging receipt to trusted Git and reuses original CATALOG and PERSONAL importer',async()=>{
    const {f,packet,trustedPlan,append}=await prepared();
    for(let i=0;i<packet.chunks.length;i++)await append(i);
    const result=await importModelC(f.c,f.p,{...f.options,
      stagedPublication:{runId:packet.run.runId,trustedPlan}});
    expect(result.status).toBe('PUBLISHED');
    expect(await count(f.c,'catalog_head')).toBe(1);
    expect(await count(f.c,'catalog_vacancy_current')).toBe(1);
    expect(await count(f.p,'personal_catalog_receipts')).toBe(1);
    expect(await count(f.c,'catalog_ingest_chunks')).toBe(packet.chunks.length);
    const again=await importModelC(f.c,f.p,f.options);
    expect(again.status).toBe('REPLAY');
    expect(again.metrics.total).toBe(0);
  });
  it('refuses an incomplete stage BEFORE any local importer write',async()=>{
    const {f,packet,trustedPlan,append}=await prepared();
    if(packet.chunks.length<2)throw Error('EXPECTED_MULTIPLE_SYNTHETIC_CHUNKS');
    await append(0);
    await expect(importModelC(f.c,f.p,{...f.options,
      stagedPublication:{runId:packet.run.runId,trustedPlan}}))
      .rejects.toThrow('INCOMPLETE_CHUNKS');
    expect(await count(f.c,'catalog_head')).toBe(0);
    expect(await count(f.c,'catalog_write_reservations')).toBe(0);
    expect(await count(f.p,'personal_heads')).toBe(0);
  });
  it('refuses a digest-consistent but Git-inconsistent staged title BEFORE any publication',async()=>{
    const {f,packet,trustedPlan,append}=await prepared();
    for(let i=0;i<packet.chunks.length;i++){
      if(packet.chunks[i]!.records.some(r=>r.kind==='job'))await append(i,{title:'Forged staged title'});
      else await append(i);
    }
    await expect(importModelC(f.c,f.p,{...f.options,
      stagedPublication:{runId:packet.run.runId,trustedPlan}}))
      .rejects.toThrow('STAGED_PROJECTION_MISMATCH');
    expect(await count(f.c,'catalog_head')).toBe(0);
    expect(await count(f.p,'personal_heads')).toBe(0);
  });
});
