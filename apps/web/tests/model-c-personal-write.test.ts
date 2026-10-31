import {beforeAll,afterAll,describe,it,expect} from 'vitest';
import {Miniflare,convertV4MiniflareOptions} from 'miniflare';
import worker from '../worker/index';
import {applySchema,captureSynthetic} from '../tools/model-c-schema';
import {stageCatalog,publicationFixture,seedPersonal,owner,hash,commit,jobId} from './helpers/model-c-fixtures';
import {executePersonalCommand} from '../worker/data/model-c-personal-write';
import {getModelCPersonalJob,getModelCPersonalSummary,listModelCPersonalJobs,getModelCPersonalOverlays} from '../worker/data/model-c-personal';

let runtime:Miniflare,sequence=0,operationSequence=0;
const op=()=>('00000000-0000-4000-8000-'+String(++operationSequence).padStart(12,'0'));
const local='http://localhost';
const url=local+'/api/model-c/personal/commands/';
type Env=Parameters<typeof worker.fetch>[1];
const command=(job:string,revision:number,kind:'DECISION'|'SAVED',changes:Record<string,unknown>)=>({
  jobId:job,expectedRevision:revision,catalogRevision:1,operationId:op(),kind,...changes,
});
async function fresh(){
  const catalog=await runtime.getD1Database('DB'+sequence++);
  const personal=await runtime.getD1Database('DB'+sequence++);
  await applySchema(catalog,'catalog');await applySchema(personal,'personal');
  await stageCatalog(catalog);await catalog.batch(publicationFixture(catalog,'run-one'));
  await seedPersonal(personal);
  const env:Env={APP_ENV:'local',MODEL_C_LOCAL_API:'synthetic-only',
    MODEL_C_LOCAL_WRITE:'synthetic-only',CATALOG:catalog,PERSONAL:personal,MODEL_C_TEST_OWNER:owner};
  const post=async(cmd:Record<string,unknown>,opts?:{origin?:string;type?:string;ownerHeader?:string})=>{
    const headers:Record<string,string>={'content-type':opts?.type??'application/json'};
    if(opts?.origin!==undefined)headers.origin=opts.origin;
    else headers.origin=local;
    if(opts?.ownerHeader)headers['x-owner-id']=opts.ownerHeader;
    const kind=cmd.kind==='SAVED'?'saved':'decision';
    const response=await worker.fetch(new Request(url+kind,{method:'POST',headers,body:JSON.stringify(cmd)}),env);
    return {status:response.status,body:await response.json() as Record<string,unknown>};
  };
  return {catalog,personal,env,post};
}
beforeAll(()=>{runtime=new Miniflare(convertV4MiniflareOptions({
  modules:true,script:'export default {fetch(){return new Response("synthetic")}}',cf:false,compatibilityDate:'2026-10-29',
  d1Databases:Object.fromEntries(Array.from({length:32},(_,i)=>['DB'+i,'model-c-write-'+i])),
}));});
afterAll(async()=>{await runtime?.dispose();});

describe('PR #41: additive PERSONAL app writer, real D1 and Worker HTTP',()=>{
  it('saves INTERESTED, then APPLIED, reads both through PERSONAL and composite overlays without touching imported facts',async()=>{
    const {catalog,personal,post}=await fresh();
    const importedBefore=await personal.prepare('SELECT decision FROM personal_decision_events').first('decision');
    const catBefore=(await captureSynthetic(catalog,'catalog')).sha256;
    const first=await post(command(jobId,0,'DECISION',{decision:'INTERESTED'}));
    expect(first).toMatchObject({status:200,body:{status:'saved',jobRevision:1,decision:'INTERESTED',replayed:false}});
    const read=await getModelCPersonalJob(catalog,personal,{ownerId:owner},jobId);
    expect(read.job).toMatchObject({decision:'INTERESTED',decisionSource:'APP',jobRevision:1,
      reconciliation:'PENDING'});
    expect(read.decisionEvents).toEqual(expect.arrayContaining([
      expect.objectContaining({decision:'INTERESTED',origin:'APP',sourceCommit:null}),
      expect.objectContaining({decision:'NOT_INTERESTED',origin:'GITHUB',sourceCommit:commit}),
    ]));
    const second=await post(command(jobId,1,'DECISION',{decision:'APPLIED',reasonSummary:'Test submission'}));
    expect(second).toMatchObject({status:200,body:{jobRevision:2,decision:'APPLIED'}});
    const list=await listModelCPersonalJobs(catalog,personal,{ownerId:owner},{view:'applied'});
    expect(list).toMatchObject({total:1,items:[{decision:'APPLIED',jobRevision:2}]});
    expect((await listModelCPersonalJobs(catalog,personal,{ownerId:owner},{view:'to_apply'})).total).toBe(0);
    const overlay=await getModelCPersonalOverlays(catalog,personal,{ownerId:owner},[jobId]);
    expect(overlay.items[jobId]?.decision).toBe('APPLIED');
    expect((await getModelCPersonalSummary(catalog,personal,{ownerId:owner})).counts.decisionsCount).toBe(1);
    expect(await personal.prepare('SELECT count(*) AS n FROM personal_app_events').first('n')).toBe(2);
    expect(await personal.prepare('SELECT decision FROM personal_decision_events').first('decision')).toBe(importedBefore);
    expect((await captureSynthetic(catalog,'catalog')).sha256).toBe(catBefore);
    expect(await personal.prepare('SELECT revision FROM personal_heads WHERE owner_id=?').bind(owner).first('revision')).toBe(1);
  });
  it('persists SAVED, removes it independently of imported decision, preserves history',async()=>{
    const {catalog,personal,post}=await fresh();
    expect((await post(command(jobId,0,'SAVED',{active:true}))).body).toMatchObject({saved:true,jobRevision:1});
    expect((await getModelCPersonalJob(catalog,personal,{ownerId:owner},jobId)).job)
      .toMatchObject({decision:'NOT_INTERESTED',activeReferences:['DISMISSED','SAVED']});
    expect((await post(command(jobId,1,'SAVED',{active:false}))).body).toMatchObject({saved:false,jobRevision:2});
    const row=(await getModelCPersonalJob(catalog,personal,{ownerId:owner},jobId)).job;
    expect(row.activeReferences).toEqual(['DISMISSED']);
    expect(row.decision).toBe('NOT_INTERESTED');
    expect(await personal.prepare("SELECT count(*) AS n FROM personal_app_events WHERE kind='SAVED'").first('n')).toBe(2);
    expect(await personal.prepare('SELECT count(*) AS n FROM personal_reference_state').first('n')).toBe(1);
  });
  it('supports an APP-only reference for an owner with no imported job rows',async()=>{
    const {catalog,personal,env}=await fresh();
    const second='synthetic-fresh';
    await personal.prepare('INSERT INTO personal_owners VALUES (?)').bind(second).run();
    await personal.prepare('INSERT INTO personal_heads VALUES (?,1,?,?)').bind(second,hash,commit).run();
    const result=await executePersonalCommand(catalog,personal,{ownerId:second},
      command(jobId,0,'DECISION',{decision:'TO_REVIEW'}));
    expect(result).toMatchObject({jobRevision:1,decision:'TO_REVIEW'});
    const page=await listModelCPersonalJobs(catalog,personal,{ownerId:second},{view:'to_apply'});
    expect(page).toMatchObject({total:1,items:[{jobId,decision:'TO_REVIEW',decisionSource:'APP'}]});
    expect((await getModelCPersonalJob(catalog,personal,{ownerId:second},jobId)).decisionEvents[0])
      .toMatchObject({origin:'APP'});
    expect((await getModelCPersonalOverlays(catalog,personal,{ownerId:second},[jobId])).items[jobId])
      .toMatchObject({decision:'TO_REVIEW'});
    expect((await personal.prepare('SELECT count(*) AS n FROM personal_job_refs WHERE owner_id=?')
      .bind(second).first('n'))).toBe(0);
    expect(env.MODEL_C_TEST_OWNER).toBe(owner);
  });
  it('revokes a decision with an immutable tombstone without deleting the imported record',async()=>{
    const {catalog,personal,post}=await fresh();
    const response=await post(command(jobId,0,'DECISION',{decision:null}));
    expect(response).toMatchObject({status:200,body:{decision:null,jobRevision:1}});
    const row=await getModelCPersonalJob(catalog,personal,{ownerId:owner},jobId);
    expect(row.job.decision).toBeNull();
    expect(row.job.decisionSource).toBe('APP');
    expect(row.decisionEvents).toEqual(expect.arrayContaining([expect.objectContaining({
      origin:'APP',decision:null,
    })]));
    expect((await getModelCPersonalSummary(catalog,personal,{ownerId:owner})).counts.decisionsCount).toBe(0);
    expect(await personal.prepare('SELECT count(*) AS n FROM personal_decision_events').first('n')).toBe(1);
  });
  it('returns durable idempotent replay and rejects a reused key with altered payload',async()=>{
    const {personal,post}=await fresh();
    const cmd=command(jobId,0,'DECISION',{decision:'INTERESTED'});
    const first=await post(cmd),retry=await post(cmd);
    expect(first.status).toBe(200);expect(retry).toMatchObject({status:200,body:{replayed:true,jobRevision:1}});
    expect(await personal.prepare('SELECT count(*) AS n FROM personal_app_events').first('n')).toBe(1);
    const wrong=await post({...cmd,decision:'APPLIED'});
    expect(wrong).toMatchObject({status:409,body:{error:'IDEMPOTENCY_KEY_REUSED'}});
    expect(await personal.prepare('SELECT count(*) AS n FROM personal_app_events').first('n')).toBe(1);
  });
  it('enforces per-job CAS for competing operations, and invalidates stale PERSONAL paging cursors',async()=>{
    const {catalog,personal,post}=await fresh();
    // A second historical row ensures pagination has a real continuation cursor.
    const missing='job:'+'2'.repeat(64);
    await personal.prepare("INSERT INTO personal_job_refs VALUES (?,?,'Old archived',NULL,'UNKNOWN',?,'old.json',?,1)")
      .bind(owner,missing,commit,hash).run();
    const first=await listModelCPersonalJobs(catalog,personal,{ownerId:owner},{limit:1});
    expect(first.nextCursor).not.toBeNull();
    const a=command(jobId,0,'DECISION',{decision:'INTERESTED'});
    const b=command(jobId,0,'DECISION',{decision:'NOT_INTERESTED'});
    const results=await Promise.all([post(a),post(b)]);
    expect(results.map(r=>r.status).sort()).toEqual([200,409]);
    await expect(listModelCPersonalJobs(catalog,personal,{ownerId:owner},{limit:1,cursor:first.nextCursor!}))
      .rejects.toMatchObject({code:'CONTEXT_CHANGED'});
    expect(await personal.prepare('SELECT count(*) AS n FROM personal_app_events').first('n')).toBe(1);
  });
  it('atomically rolls back the entire transaction when idempotency persistence fails',async()=>{
    const {personal,post}=await fresh();
    await personal.prepare(`CREATE TRIGGER synthetic_fail BEFORE INSERT ON personal_app_operations
      BEGIN SELECT RAISE(ABORT,'synthetic_operation_failure'); END`).run();
    expect((await post(command(jobId,0,'DECISION',{decision:'INTERESTED'}))).status).toBe(503);
    for(const table of ['personal_app_jobs','personal_app_events','personal_app_current',
      'personal_app_heads','personal_app_operations']){
      expect(await personal.prepare('SELECT count(*) AS n FROM '+table).first('n'),table).toBe(0);
    }
    await personal.prepare('DROP TRIGGER synthetic_fail').run();
  });
  it('preserves owner isolation and rejects origin, remote runtime and override headers',async()=>{
    const {personal,env,post}=await fresh();
    const cmd=command(jobId,0,'DECISION',{decision:'INTERESTED'});
    expect((await post(cmd,{ownerHeader:'synthetic-other'})).status).toBe(403);
    expect((await post(cmd,{origin:'https://evil.example'})).status).toBe(403);
    const remote=await worker.fetch(new Request('https://evil.example/api/model-c/personal/commands/decision',{
      method:'POST',headers:{origin:'https://evil.example','content-type':'application/json'},body:JSON.stringify(cmd),
    }),env);
    expect(remote.status).toBe(403);
    const noGate=await worker.fetch(new Request(url+'decision',{
      method:'POST',headers:{origin:local,'content-type':'application/json'},body:JSON.stringify(cmd),
    }),{...env,MODEL_C_LOCAL_WRITE:'disabled'});
    expect(noGate.status).toBe(404);
    const other='synthetic-other';
    await personal.prepare('INSERT INTO personal_owners VALUES (?)').bind(other).run();
    await personal.prepare('INSERT INTO personal_heads VALUES (?,1,?,?)').bind(other,hash,commit).run();
    const good=await post(cmd);expect(good.status).toBe(200);
    expect(await personal.prepare('SELECT count(*) AS n FROM personal_app_events WHERE owner_id=?')
      .bind(other).first('n')).toBe(0);
  });
  it('validates strict JSON, size, revision, IDs, command kind and method',async()=>{
    const {env,post}=await fresh();
    const cmd=command(jobId,0,'DECISION',{decision:'INTERESTED'});
    expect((await post({...cmd,unexpected:true})).status).toBe(400);
    expect((await post({...cmd,jobId:'bad'})).status).toBe(400);
    expect((await post({...cmd,decision:'CUSTOM'})).status).toBe(400);
    expect((await post({...cmd,kind:'SAVED',active:true,decision:'INTERESTED'})).status).toBe(400);
    expect((await post(cmd,{type:'text/plain'})).status).toBe(415);
    const withoutOrigin=await worker.fetch(new Request(url+'decision',{
      method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(cmd),
    }),env);
    expect(withoutOrigin.status).toBe(403);
    const forbiddenMethod=await worker.fetch(new Request(url+'decision',{method:'GET'}),env);
    expect(forbiddenMethod.status).toBe(405);
    const oversized=await worker.fetch(new Request(url+'decision',{
      method:'POST',headers:{origin:local,'content-type':'application/json'},
      body:JSON.stringify({...cmd,reasonSummary:'x'.repeat(3000)}),
    }),env);
    expect(oversized.status).toBe(413);
    const wrongRevision=await post({...cmd,catalogRevision:2});
    expect(wrongRevision).toMatchObject({status:409,body:{error:'CATALOG_CHANGED'}});
  });
  it('keeps SAVED and decision APP events immutable and imported receipt/provenance untouched',async()=>{
    const {personal,catalog,post}=await fresh();
    const before=await personal.prepare('SELECT revision,context_digest FROM personal_heads WHERE owner_id=?')
      .bind(owner).first();
    expect((await post(command(jobId,0,'SAVED',{active:true}))).status).toBe(200);
    await expect(personal.prepare("UPDATE personal_app_events SET kind='DECISION'").run()).rejects.toThrow();
    await expect(personal.prepare('DELETE FROM personal_app_events').run()).rejects.toThrow();
    await expect(personal.prepare('DELETE FROM personal_app_operations').run()).rejects.toThrow();
    expect(await personal.prepare('SELECT revision,context_digest FROM personal_heads WHERE owner_id=?')
      .bind(owner).first()).toEqual(before);
    const overlay=await getModelCPersonalOverlays(catalog,personal,{ownerId:owner},[jobId]);
    expect(overlay.items[jobId]?.activeReferences).toContain('SAVED');
    expect(overlay.items[jobId]?.reconciliation).toBe('PENDING');
  });
});
