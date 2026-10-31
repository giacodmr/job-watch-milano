import {beforeAll,describe,it,expect} from 'vitest';
import {build} from 'esbuild';
import {Miniflare,convertV4MiniflareOptions} from 'miniflare';
import {applySchema,captureSynthetic} from '../tools/model-c-schema';
import {stageCatalog,publicationFixture,seedPersonal,jobId,owner,hash,commit} from './helpers/model-c-fixtures';
import {getModelCPersonalJob,getModelCPersonalOverlays,listModelCPersonalJobs,getModelCPersonalSummary} from '../worker/data/model-c-personal';
import {writeModelCPersonal} from '../worker/data/model-c-personal-write';

let script:string;
beforeAll(async()=>{
  const result=await build({entryPoints:['worker/index.ts'],bundle:true,write:false,
    format:'esm',platform:'browser',target:'es2023'});
  script=result.outputFiles[0]!.text;
});
async function fixture(write=true){
  const runtime=new Miniflare(convertV4MiniflareOptions({
    modules:true,script,cf:false,compatibilityDate:'2026-10-29',
    bindings:{APP_ENV:'local',MODEL_C_LOCAL_API:'synthetic-only',MODEL_C_TEST_OWNER:owner,
      ...(write?{MODEL_C_LOCAL_WRITE:'synthetic-only'}:{})},
    d1Databases:{CATALOG:'pr41-catalog',PERSONAL:'pr41-personal'},
  }));
  const c=await runtime.getD1Database('CATALOG'),p=await runtime.getD1Database('PERSONAL');
  await applySchema(c,'catalog');await applySchema(p,'personal');
  await stageCatalog(c);await c.batch(publicationFixture(c,'run-one'));await seedPersonal(p);
  const api=(path:string,body?:object,options?:{origin?:string;type?:string})=>
    runtime.dispatchFetch('http://localhost'+path,body===undefined?undefined:{
      method:'POST',headers:{origin:options?.origin??'http://localhost',
        'content-type':options?.type??'application/json'},
      body:JSON.stringify(body),
    });
  return {runtime,c,p,api};
}
const path='/api/model-c/personal/commands/decision';
const savedPath='/api/model-c/personal/commands/saved';
let seq=0;
const command=(decision:'INTERESTED'|'APPLIED'|'TO_REVIEW'|'NOT_INTERESTED'|null,rev:number,id?:string)=>({
  jobId,decision,expectedRevision:rev,idempotencyKey:id??'00000000-0000-4000-8000-'+String(++seq).padStart(12,'0'),
});
const saved=(action:'activate'|'deactivate',rev:number,id?:string)=>({
  jobId,action,expectedRevision:rev,idempotencyKey:id??'00000000-0000-4000-8000-'+String(++seq).padStart(12,'0'),
});
async function json(r:Response){return r.json() as Promise<Record<string,any>>;}

describe('PR #41: real local Worker + D1 PERSONAL write engine',()=>{
  it('POST→D1→GET: preserves import, overrides decisions, revokes, saves, replays safely',async()=>{
    const {runtime,c,p,api}=await fixture();
    try {
      const catalogBefore=(await captureSynthetic(c,'catalog')).sha256;
      const importerDigest=await p.prepare('SELECT context_digest FROM personal_heads').first('context_digest');
      const a=command('INTERESTED',0);
      const created=await api(path,a);expect(created.status).toBe(201);
      const first=await json(created);expect(first).toMatchObject({
        status:'saved',replayed:false,appRevision:1,decision:'INTERESTED',decisionSource:'APP',saved:false,
      });
      const detail=await json(await api('/api/model-c/personal/jobs/'+jobId));
      expect(detail.job).toMatchObject({decision:'INTERESTED',decisionSource:'APP',appRevision:1,
        assessment:{fitScore:75},savedSource:null});
      expect(detail.decisionEvents).toMatchObject([{decision:'NOT_INTERESTED'}]);
      expect(detail.appEvents).toHaveLength(1);
      expect((await json(await api('/api/model-c/opportunities/jobs?limit=10'))).items[0].personal.decision).toBe('INTERESTED');
      expect((await json(await api('/api/model-c/personal/jobs?decision=INTERESTED'))).total).toBe(1);
      expect((await json(await api('/api/model-c/personal/jobs?view=dismissed&decision=NOT_INTERESTED'))).total).toBe(0);
      const duplicate=await api(path,a);
      expect(duplicate.status).toBe(200);expect(await json(duplicate)).toMatchObject({replayed:true,eventId:first.eventId,appRevision:1});
      const changed=await api(path,{...a,decision:'APPLIED'});
      expect(changed.status).toBe(409);expect(await json(changed)).toEqual({error:'IDEMPOTENCY_KEY_CONFLICT'});
      const stale=await api(path,command('APPLIED',0));expect(stale.status).toBe(409);
      const b=await api(path,command('APPLIED',1));
      expect(b.status).toBe(201);expect(await json(b)).toMatchObject({decision:'APPLIED',appRevision:2});
      expect((await json(await api('/api/model-c/personal/jobs?view=applied'))).total).toBe(1);
      const s=await api(savedPath,saved('activate',2));expect(s.status).toBe(201);
      expect((await json(await api('/api/model-c/personal/jobs/'+jobId))).job).toMatchObject({
        decision:'APPLIED',saved:true,savedSource:'APP',appRevision:3,
      });
      const off=await api(savedPath,saved('deactivate',3));expect(off.status).toBe(201);
      const clear=await api(path,command(null,4));expect(clear.status).toBe(201);
      const final=await json(await api('/api/model-c/personal/jobs/'+jobId));
      expect(final.job).toMatchObject({decision:null,decisionSource:'APP',saved:false,appRevision:5,
        assessment:{fitScore:75},activeReferences:['DISMISSED']});
      expect(final.appEvents.map((e:{resultRevision:number})=>e.resultRevision)).toEqual([5,4,3,2,1]);
      expect(await p.prepare('SELECT count(*) AS n FROM personal_app_operations').first('n')).toBe(5);
      expect(await p.prepare('SELECT count(*) AS n FROM personal_app_events').first('n')).toBe(5);
      expect(await p.prepare('SELECT decision FROM personal_decision_events').first('decision')).toBe('NOT_INTERESTED');
      expect(await p.prepare('SELECT context_digest FROM personal_heads').first('context_digest')).toBe(importerDigest);
      expect((await captureSynthetic(c,'catalog')).sha256).toBe(catalogBefore);
      expect((await json(await api('/api/model-c/personal/summary'))).counts).toMatchObject({
        referencesCount:1,decisionsCount:0,assessmentsCount:1,
      });
    }finally{await runtime.dispose();}
  });

  it('competing different keys have exactly one winner, stale CAS and persistent receipt',async()=>{
    const {runtime,p,api}=await fixture();
    try{
      const [a,b]=await Promise.all([api(path,command('INTERESTED',0)),api(path,command('APPLIED',0))]);
      expect([a.status,b.status].sort()).toEqual([201,409]);
      expect(await p.prepare('SELECT count(*) AS n FROM personal_app_events').first('n')).toBe(1);
      expect(await p.prepare('SELECT revision FROM personal_app_job_state').first('revision')).toBe(1);
      expect(await p.prepare('SELECT epoch FROM personal_app_owner_epochs').first('epoch')).toBe(1);
    }finally{await runtime.dispose();}
  });

  it('same-key concurrent retries return one event and replay receipt',async()=>{
    const {runtime,p,api}=await fixture();
    try{
      const cmd=command('INTERESTED',0);
      const [a,b]=await Promise.all([api(path,cmd),api(path,cmd)]);
      expect([a.status,b.status].sort()).toEqual([200,201]);
      expect((await json(a)).eventId).toBe((await json(b)).eventId);
      expect(await p.prepare('SELECT count(*) AS n FROM personal_app_events').first('n')).toBe(1);
      expect(await p.prepare('SELECT epoch FROM personal_app_owner_epochs').first('epoch')).toBe(1);
    }finally{await runtime.dispose();}
  });

  it('a mid-transaction SQL fault rolls back projection, event, receipt and epoch',async()=>{
    const {runtime,p,api}=await fixture();
    try{
      await p.prepare("CREATE TRIGGER pr41_test_abort BEFORE INSERT ON personal_app_events BEGIN SELECT RAISE(ABORT,'fault_injection'); END").run();
      const response=await api(path,command('INTERESTED',0));
      expect(response.status).toBe(503);
      for(const table of ['personal_app_events','personal_app_operations','personal_app_job_state','personal_app_owner_epochs'])
        expect(await p.prepare('SELECT count(*) AS n FROM '+table).first('n'),table).toBe(0);
      await p.prepare('DROP TRIGGER pr41_test_abort').run();
      expect((await api(path,command('INTERESTED',0))).status).toBe(201);
    }finally{await runtime.dispose();}
  });

  it('per-job cursor epoch changes, no imported assessment corruption, owner isolation and APP-only job',async()=>{
    const {runtime,c,p,api}=await fixture();
    try{
      const second='synthetic-second';
      await p.prepare('INSERT INTO personal_owners VALUES (?)').bind(second).run();
      await p.prepare('INSERT INTO personal_heads VALUES (?,1,?,?)').bind(second,hash,commit).run();
      const otherBefore=await listModelCPersonalJobs(c,p,{ownerId:second});
      expect(otherBefore.total).toBe(0);
      const first=await listModelCPersonalJobs(c,p,{ownerId:owner},{limit:1});
      const a=await api(path,command('INTERESTED',0));expect(a.status).toBe(201);
      if(first.nextCursor)await expect(listModelCPersonalJobs(c,p,{ownerId:owner},{cursor:first.nextCursor}))
        .rejects.toMatchObject({code:'CONTEXT_CHANGED'});
      const other=await writeModelCPersonal(c,p,{ownerId:second},
        {kind:'DECISION',payload:command('APPLIED',0)});
      expect(other.appRevision).toBe(1);
      const otherNow=await listModelCPersonalJobs(c,p,{ownerId:second});
      expect(otherNow).toMatchObject({total:1,items:[{jobId,appRevision:1,
        decision:'APPLIED',capturedCommit:null,capturedPath:null,decisionSource:'APP'}]});
      expect((await getModelCPersonalSummary(c,p,{ownerId:second})).counts).toMatchObject({decisionsCount:1,assessmentsCount:0});
      expect((await getModelCPersonalOverlays(c,p,{ownerId:second},[jobId])).items[jobId]?.decision).toBe('APPLIED');
      expect((await getModelCPersonalJob(c,p,{ownerId:owner},jobId)).job.decision).toBe('INTERESTED');
      expect(await p.prepare('SELECT count(*) AS n FROM personal_assessment_events').first('n')).toBe(1);
    }finally{await runtime.dispose();}
  });

  it('gate OFF, wrong origin, invalid body and remote runtime prevent writes',async()=>{
    const {runtime,p,api}=await fixture(false);
    try{
      expect((await json(await api('/api/model-c/personal/capabilities'))).writeEnabled).toBe(false);
      const r=await api(path,command('INTERESTED',0));expect(r.status).toBe(403);
      expect(await p.prepare('SELECT count(*) AS n FROM personal_app_events').first('n')).toBe(0);
      // Direct Worker adapter check with explicitly gated env.
      const {handleModelCLocalApi}=await import('../worker/model-c-local-api');
      const env={APP_ENV:'local',MODEL_C_LOCAL_API:'synthetic-only',MODEL_C_LOCAL_WRITE:'synthetic-only',
        MODEL_C_TEST_OWNER:owner,PERSONAL:p};
      const request=new Request('http://localhost'+path,{method:'POST',headers:{
        Origin:'https://attacker.example','Content-Type':'application/json'},body:JSON.stringify(command('INTERESTED',0))});
      expect((await handleModelCLocalApi(request,new URL(request.url),env)).status).toBe(403);
      expect((await handleModelCLocalApi(new Request('https://external.example'+path),
        new URL('https://external.example'+path),env)).status).toBe(403);
      expect((await api('/api/model-c/personal/capabilities')).status).toBe(200);
    }finally{await runtime.dispose();}
  });

  it('schema v3 is additive and leaves imported projection unchanged before first command',async()=>{
    const {runtime,c,p}=await fixture();
    try{
      expect(await p.prepare("SELECT version FROM model_c_schema WHERE scope='PERSONAL'").first('version')).toBe(3);
      expect(await c.prepare("SELECT version FROM model_c_schema WHERE scope='CATALOG'").first('version')).toBe(4);
      expect(await p.prepare('SELECT count(*) AS n FROM personal_app_events').first('n')).toBe(0);
      expect(await p.prepare('PRAGMA foreign_key_check').all()).toMatchObject({results:[]});
      expect(await p.prepare('SELECT decision FROM personal_decision_events').first('decision')).toBe('NOT_INTERESTED');
      expect(await applySchema(p,'personal')).toMatchObject({applied:0,rowsWritten:0});
    }finally{await runtime.dispose();}
  });
});
