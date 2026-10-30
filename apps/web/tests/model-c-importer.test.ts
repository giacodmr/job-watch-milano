import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { execFileSync } from 'node:child_process';
import { mkdtemp, readFile, writeFile, rm } from 'node:fs/promises';
import { resolve } from 'node:path';
import { tmpdir } from 'node:os';
import { Miniflare, convertV4MiniflareOptions } from 'miniflare';
import { applySchema, captureSynthetic } from '../tools/model-c-schema';
import { importModelC } from '../tools/model-c-importer';
import type { ImportOptions } from '../tools/model-c-importer';
import { verifyGitProjection } from '../tools/model-c-git';
import { importSnapshot } from '../worker/data/importer';
import { canonical } from '../shared/canonical';

let runtime:Miniflare, seq=0, commitSequence=0;
const dirs:string[]=[], measurements:Record<string,unknown>={};
const bootstrap={identities:{mode:'first-v1-bootstrap' as const},personalReferences:[]};
const python=process.env.JOB_WATCH_PYTHON||'python3';
const git=(repo:string,...args:string[])=>execFileSync('git',['-C',repo,...args],{encoding:'utf8',stdio:['ignore','pipe','pipe']}).trim();
function cohere(repo:string) {execFileSync(python,['tests/helpers/model-c-import-fixture.py',repo,'cohere'],{stdio:'pipe',env:{...process.env,PYTHONDONTWRITEBYTECODE:'1'}});}
function commit(repo:string) {
  git(repo,'add','.');git(repo,'-c','user.name=Synthetic','-c','user.email=synthetic@example.test','commit','--allow-empty','-qm','Synthetic importer fixture '+(++commitSequence));
  const sha=git(repo,'rev-parse','HEAD');git(repo,'update-ref','refs/remotes/origin/main',sha);return sha;
}
async function fixture(count=2) {
  const repo=await mkdtemp(resolve(tmpdir(),'model-c-test-'));dirs.push(repo);
  execFileSync(python,['tests/helpers/model-c-import-fixture.py',repo,'seed',String(count)],{stdio:'pipe',env:{...process.env,PYTHONDONTWRITEBYTECODE:'1'}});
  git(repo,'init','-q','-b','main');git(repo,'remote','add','origin','https://github.com/giacodmr/job-watch-milano.git');
  const sha=commit(repo), c=await runtime.getD1Database('DB'+seq++), p=await runtime.getD1Database('DB'+seq++);
  await applySchema(c,'catalog');await applySchema(p,'personal');
  const options:ImportOptions={source:{repo,commit:sha},bootstrap:'empty-target',owner:'synthetic-owner',budget:{day:new Date().toISOString().slice(0,10),availableRows:30000}};
  return {repo,c,p,options};
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
  if(process.env.MODEL_C_METRICS_FILE)await writeFile(process.env.MODEL_C_METRICS_FILE,JSON.stringify({syntheticOnly:true,measurement:'actual D1 meta.rows_written; schema setup and fixture seed excluded',scenarios:measurements},null,2)+'\n');});

describe('verified incremental importer on ephemeral D1',()=>{
  it('bootstraps, replays with zero writes, and observes a new identical commit without a content revision',async()=>{
    const f=await fixture();const a=await importModelC(f.c,f.p,f.options);measurements.bootstrap=a.metrics;
    expect(a.status).toBe('PUBLISHED');expect(await count(f.c,'catalog_vacancy_identity')).toBe(2);expect(await count(f.c,'catalog_vacancy_current')).toBe(2);
    const replay=await importModelC(f.c,f.p,f.options);measurements.replay=replay.metrics;expect(replay.metrics.total).toBe(0);expect(replay.status).toBe('REPLAY');
    const current=(await f.c.prepare('SELECT * FROM catalog_vacancy_current').all()).results;
    f.options.source.commit=commit(f.repo);const b=await importModelC(f.c,f.p,f.options);measurements.unchangedObservation=b.metrics;
    expect(b.syncRevision).toBe(2);expect(b.observation.catalogRevision).toBe(1);expect(b.observation.contentOrigin).toEqual(a.observation.contentOrigin);
    expect((await f.c.prepare('SELECT * FROM catalog_vacancy_current').all()).results).toEqual(current);
    expect(await count(f.c,'catalog_content_revisions')).toBe(1);expect(await count(f.c,'catalog_audit')).toBe(2);
    expect(await count(f.c,'catalog_stage_vacancies')).toBe(0);expect(a.metrics.total).toBeLessThanOrEqual(a.metrics.reservedBound);
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
  it('rejects an oversized atomic publication before staging rather than splitting the current delta',async()=>{
    const f=await fixture(1600);
    await expect(importModelC(f.c,f.p,{...f.options,budget:{...f.options.budget,availableRows:60000,extendedAuthorized:true}})).rejects.toThrow('ATOMIC_PUBLICATION_LIMIT');
    expect(await count(f.c,'catalog_head')).toBe(0);expect(await count(f.c,'catalog_runs')).toBe(0);expect(await count(f.c,'catalog_write_reservations')).toBe(0);
  });
  it('invalidates projection input on a code-only commit without manufacturing content changes',async()=>{
    const f=await fixture(1);const first=await importModelC(f.c,f.p,f.options);
    const path=resolve(f.repo,'sync_analysis_state.py');await writeFile(path,(await readFile(path,'utf8'))+'\n# synthetic implementation-only change\n');f.options.source.commit=commit(f.repo);
    const next=await importModelC(f.c,f.p,f.options);
    expect(next.observation.catalogRevision).toBe(first.observation.catalogRevision);expect(next.observation.projectionInputDigest).not.toBe(first.observation.projectionInputDigest);
  });
});
