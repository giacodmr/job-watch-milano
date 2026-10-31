// M47: full Git/Python -> v2 HTTP -> D1 -> importer -> PERSONAL -> journal
// -> retention on the SAME pair of ephemeral databases for thirty revisions.
import {afterAll,beforeAll,expect,it} from 'vitest';
import {Miniflare,convertV4MiniflareOptions} from 'miniflare';
import {mkdtemp,readFile,writeFile,rm} from 'node:fs/promises';
import {execFileSync} from 'node:child_process';
import {resolve} from 'node:path';
import {tmpdir} from 'node:os';
import {generateKeyPair,SignJWT,createLocalJWKSet,exportJWK} from 'jose';
import {canonical,sha256} from '../shared/canonical';
import {applySchema} from '../tools/model-c-schema';
import {verifyGitProjection} from '../tools/model-c-git';
import {verifyProjectionProof} from '../shared/projection-proof';
import {selectModelC} from '../shared/model-c-selection';
import {prepareCatalogV2Packets} from '../shared/model-c-ingestion-v2';
import {importModelC} from '../tools/model-c-importer';
import type {ImportOptions} from '../tools/model-c-importer';
import {prepareSafeRemoteBootstrapPlan} from '../tools/model-c-remote-plan';
import {createOfflineV2IngestionHarness} from '../worker/model-c-ingest-v2-lab';
import {observeIngestJournal} from '../tools/model-c-publication-journal';
import {compactTerminalV2Runs} from '../tools/model-c-v2-ingest-retention';
import {inspectPublishedModelCRecovery} from '../tools/model-c-import-recovery';
import {getModelCCatalogSnapshot} from '../worker/data/model-c-catalog';
import {executePersonalCommand} from '../worker/data/model-c-personal-write';
import {getModelCPersonalJob} from '../worker/data/model-c-personal';

const python=process.env.JOB_WATCH_PYTHON||'python3';
const issuer='https://m47-test.cloudflareaccess.com',audience='a'.repeat(64);
const clientId='c'.repeat(32)+'.access',hostname='sync.synthetic.invalid';
const base='https://'+hostname+'/api/model-c/sync/v2/runs';
let runtime:Miniflare,repo:string,c:D1Database,p:D1Database;
let sourceJobs:Record<string,unknown>[],initialJobId='',initialPacket:
 Awaited<ReturnType<typeof prepareCatalogV2Packets>>|null=null;
const metrics:Array<Record<string,unknown>>=[];
function git(...args:string[]){
 return execFileSync('git',['-C',repo,...args],{encoding:'utf8',stdio:['ignore','pipe','pipe']}).trim();
}
function commit(n:number){
 git('add','.');git('-c','user.name=Synthetic','-c','user.email=synthetic@example.test',
  'commit','--allow-empty','-qm','Synthetic continuous M47 '+n);
 const sha=git('rev-parse','HEAD');git('update-ref','refs/remotes/origin/main',sha);
 return sha;
}
async function mutate(n:number){
 const path=resolve(repo,'current_jobs_jw2.json');
 const data=JSON.parse(await readFile(path,'utf8'));
 const jobs=data.companies[0].jobs as Record<string,unknown>[];
 if(n%3===2&&jobs[0])jobs[0].title='Synthetic Strategy '+n;
 if(n===5)jobs.push({...sourceJobs[0],source_id:'999999',
  canonical_url:'https://www.amazon.jobs/en/jobs/999999/additional',
  title:'New Synthetic Vacancy'});
 if(n===10&&jobs.length>1)jobs.splice(1,1);
 if(n===12&&!jobs.some(j=>j.source_id===sourceJobs[1]?.source_id))
  jobs.push({...sourceJobs[1]});
 if(n===16&&jobs[0]){
  // Only Python identity resolution authorizes this alias. The trusted
  // ledger retains the previous id when a native ATS identifier changes.
  const memoryPath=resolve(repo,'job_memory_jw2.json');
  const mem=JSON.parse(await readFile(memoryPath,'utf8'));
  mem.records['Amazon::123456']={identity:{...sourceJobs[0]}};
  await writeFile(memoryPath,JSON.stringify(mem));
  jobs[0].source_id='rotated-2026';
 }
 if(n===18&&jobs[0])jobs[0].title='Updated Advisory';
 if(n===21&&jobs[2])jobs[2].status='CLOSED';
 if(n===22&&jobs[2])jobs[2].status='STILL_OPEN';
 if(n===24)jobs.splice(jobs.findIndex(j=>j.source_id==='999999'),1);
 if(n===27){
  // Historical Git personal decision remains the trusted importer domain,
  // never staged under a service JWT.
  const memoryPath=resolve(repo,'job_memory_jw2.json');
  const mem=JSON.parse(await readFile(memoryPath,'utf8'));
  mem.records['Amazon::123459']={
   identity:{...sourceJobs[3]},
   user:{decision:'NOT_INTERESTED',decided_at:'2026-10-29T10:00:00Z'}};
  await writeFile(memoryPath,JSON.stringify(mem));
 }
 await writeFile(path,JSON.stringify(data));
 execFileSync(python,['tests/helpers/model-c-import-fixture.py',repo,'cohere'],
  {stdio:'pipe',env:{...process.env,PYTHONDONTWRITEBYTECODE:'1'}});
}
function intercept(db:D1Database,stop:(sqls:string[])=>boolean){
 const sqls=new WeakMap<object,{sql:string;real:D1PreparedStatement}>();
 const wrap=(real:D1PreparedStatement,sql:string):D1PreparedStatement=>{
  const v={bind:(...args:unknown[])=>wrap(real.bind(...args),sql),
   all:real.all.bind(real),first:real.first.bind(real),run:real.run.bind(real),
   raw:real.raw.bind(real)} as D1PreparedStatement;
  sqls.set(v,{real,sql});return v;
 };
 return {prepare:(sql:string)=>wrap(db.prepare(sql),sql),
  batch:(steps:D1PreparedStatement[])=>{
   const matched=steps.map(s=>sqls.get(s)!);
   if(stop(matched.map(s=>s.sql)))throw Error('SYNTHETIC_PERSONAL_RECEIPT_LOST');
   return db.batch(matched.map(x=>x.real));
  }} as D1Database;
}
const count=async(table:string)=>Number(await c.prepare('SELECT count(*) AS n FROM '+table).first('n'));
beforeAll(async()=>{
 repo=await mkdtemp(resolve(tmpdir(),'model-c-m47-continuous-'));
 execFileSync(python,['tests/helpers/model-c-import-fixture.py',repo,'seed','22'],
   {stdio:'pipe',env:{...process.env,PYTHONDONTWRITEBYTECODE:'1'}});
 sourceJobs=JSON.parse(await readFile(resolve(repo,'current_jobs_jw2.json'),'utf8')).companies[0].jobs;
 git('init','-q','-b','main');git('remote','add','origin','https://github.com/giacodmr/job-watch-milano.git');
 runtime=new Miniflare(convertV4MiniflareOptions({modules:true,cf:false,
  script:'export default {fetch(){return new Response("synthetic")}}',
  compatibilityDate:'2026-10-29',d1Databases:{
   CATALOG:'m47-continuous-catalog',PERSONAL:'m47-continuous-personal'}}));
 c=await runtime.getD1Database('CATALOG');p=await runtime.getD1Database('PERSONAL');
 expect((await applySchema(c,'catalog')).applied).toBe(7);
 expect((await applySchema(p,'personal')).applied).toBe(3);
});
afterAll(async()=>{await runtime?.dispose();if(repo)await rm(repo,{recursive:true,force:true});});
it('publishes, replays, retains and verifies thirty consecutive v2 revisions with real D1',async()=>{
 const pair=await generateKeyPair('RS256');
 const jwk=await exportJWK(pair.publicKey);
 const keys=createLocalJWKSet({keys:[{...jwk,alg:'RS256',kid:'m47',use:'sig'}]});
 const jwt=await new SignJWT({type:'app',sub:'',common_name:clientId})
  .setProtectedHeader({alg:'RS256',kid:'m47'}).setIssuer(issuer)
  .setAudience(audience).setIssuedAt().setExpirationTime('1h').sign(pair.privateKey);
 const h=createOfflineV2IngestionHarness({catalog:c,keys,
  auth:{hostname,issuer,audience,allowedClientId:clientId},
  quota:{syntheticVerified:true,writeUnitsRemaining:30000}});
 const send=(url:string,method:string,body?:unknown)=>h(new Request(url,{method,
  headers:{'cf-access-jwt-assertion':jwt,...(body===undefined?{}:{
   'content-type':'application/json'})},
  ...(body===undefined?{}:{body:canonical(body)})}));
 let previous:string|undefined;
 for(let i=0;i<30;i++){
  const started=performance.now();
  if(i>0&&i!==1&&i!==9&&i!==20)await mutate(i);
  const sha=commit(i);
  const before=Number(await c.prepare("SELECT sync_revision FROM catalog_head WHERE scope='catalog'")
   .first('sync_revision')??0);
  const identities=(await c.prepare(`SELECT id AS jobId,company_id AS companyId,
   origin_job_key AS originJobKey FROM catalog_vacancy_identity ORDER BY id`).all()).results as
    {jobId:string;companyId:string;originJobKey:string}[];
  const mappings=(await c.prepare(`SELECT alias_key AS key,job_id AS jobId
   FROM catalog_aliases ORDER BY alias_key`).all()).results as {key:string;jobId:string}[];
  const ledger={identities,mappings};
  const personalDecisionJobIds=(await p.prepare(
   'SELECT DISTINCT job_id AS jobId FROM personal_decision_events ORDER BY job_id'
  ).all<{jobId:string}>()).results.map(x=>x.jobId);
  const activeRefs=(await p.prepare(
   'SELECT job_id AS jobId,kind FROM personal_reference_state WHERE active=1 ORDER BY job_id,kind'
  ).all<{jobId:string;kind:'SAVED'|'APPLICATION'|'DISMISSED'}>()).results;
  const context={identities:before?{
   mode:'confirmed-ledger' as const,ledger,expectedDigest:await sha256(canonical(ledger))
  }:{mode:'first-v1-bootstrap' as const},personalReferences:activeRefs,
   personalDecisionJobIds};
  const source={repo,commit:sha};
  const verified=await verifyGitProjection(source,context,previous);
  const proof=await verifyProjectionProof(verified.bundle,verified.proof,context);
  const selected=await selectModelC(verified.bundle,context);
  const opts:ImportOptions={source,bootstrap:'empty-target',owner:'synthetic-owner',
   executionTarget:'local-ephemeral',
   budget:{day:new Date().toISOString().slice(0,10),availableRows:30000}};
  const preflight=await importModelC(c,p,{...opts,preflightOnly:true,
   oneTimeFreeBootstrap:i===0});
  if(preflight.status!=='PREFLIGHT')throw Error('EXPECTED_PREFLIGHT');
  const costs={catalog:{migrationFiles:7,localRowsWritten:0,remoteUpperBound:1000},
    personal:{migrationFiles:3,localRowsWritten:0,remoteUpperBound:1000}};
  const plan=await prepareSafeRemoteBootstrapPlan({
   status:preflight.status,provenance:preflight.provenance,budgetDay:preflight.budgetDay,
   priorLocalReservations:preflight.priorLocalReservations,
   remoteExecutionAuthorized:false,
   syncRevision:preflight.syncRevision,metrics:preflight.metrics},costs);
  const packets=await prepareCatalogV2Packets(verified.bundle,selected,proof,plan.digest,before);
  expect(packets.chunks.length).toBeGreaterThanOrEqual(2);
  expect((await send(base,'POST',packets.run)).status).toBe(201);
  const url=base+'/'+packets.run.runId+'/chunks';
  for(const chunk of [...packets.chunks].reverse()){
   const r=await send(url,'POST',chunk);
   expect(r.status).toBe(201);
  }
  if(i===0)initialPacket=packets;
  if(i===19){
   const results=await Promise.all([send(url,'POST',packets.chunks[0]),
     send(url,'POST',packets.chunks[0])]);
   expect(results.every(r=>r.status===200)).toBe(true);
  }
  const staged=await (await send(base+'/'+packets.run.runId+'/status','GET')).json() as {complete:boolean};
  expect(staged.complete).toBe(true);
  const stagedOptions={...opts,stagedPublication:{runId:packets.run.runId,trustedPlan:plan}};
  let result;
  if(i===14){
   let injected=false;
   const broken=intercept(p,sql=>{
    if(!injected&&sql.some(s=>s.startsWith('INSERT INTO personal_catalog_receipts'))){
     injected=true;return true;
    }return false;
   });
   await expect(importModelC(c,broken,stagedOptions)).rejects.toThrow('SYNTHETIC_PERSONAL_RECEIPT_LOST');
   expect((await observeIngestJournal(c,packets.run.runId)).phase).toBe('CATALOG_PUBLISHED');
   try{result=await importModelC(c,p,stagedOptions);}
   catch(e){
    const observed=await inspectPublishedModelCRecovery(c,p,{ownerId:opts.owner});
    const receipts=Number(await p.prepare('SELECT count(*) AS n FROM personal_catalog_receipts').first('n'));
    throw Error('M47_RECOVERY_DIAGNOSTIC_'+observed.status+
      '_cycle'+i+'_receipts'+receipts+'_appRevision'+
      ('appRevision' in observed?observed.appRevision:'none')+
      '_run'+('catalogRunId' in observed&&observed.catalogRunId===packets.run.runId?'MATCH':'MISMATCH')+
      '_error'+(e instanceof Error?e.message:'unknown'));
   }
   expect(result.status).toBe('RECOVERED');
  }else result=await importModelC(c,p,stagedOptions);
  expect(result.status).toBe(i===14?'RECOVERED':'PUBLISHED');
  expect(result.syncRevision).toBe(before+1);
  expect((await observeIngestJournal(c,packets.run.runId)).phase).toBe('COMPLETED');
  const personal=await inspectPublishedModelCRecovery(c,p,{ownerId:opts.owner});
  expect(['PUBLISHED_RECEIPTS_RECONCILED','APP_CONTEXT_REQUIRES_REVALIDATION'])
   .toContain(personal.status);
  const head=await getModelCCatalogSnapshot(c);
  expect(head.snapshot?.syncRevision).toBe(before+1);
  expect((await importModelC(c,p,stagedOptions)).status).toBe('REPLAY');
  const decisionCycles=[3,8,13,18];
  const decisions=['INTERESTED','TO_REVIEW','APPLIED','NOT_INTERESTED'] as const;
  const slot=decisionCycles.indexOf(i);
  if(slot>=0){
   if(!initialJobId)initialJobId=(await c.prepare(
    "SELECT job_id FROM catalog_aliases WHERE alias_key='Amazon::123456'"
   ).first<string>('job_id'))!;
   const save=await executePersonalCommand(c,p,{ownerId:opts.owner},{
    kind:'DECISION',jobId:initialJobId,catalogRevision:result.syncRevision,
    expectedRevision:slot,operationId:'00000000-0000-4000-8000-00000000414'+slot,
    decision:decisions[slot]!,reasonSummary:null});
   expect('status' in save ? save.status : null).toBe('saved');
  }
  if(i>=4){
   const ix=decisionCycles.filter(x=>x<=i).length-1;
   expect((await getModelCPersonalJob(c,p,{ownerId:opts.owner},initialJobId)).job)
    .toMatchObject({decision:decisions[ix],decisionSource:'APP'});
  }
  const retained=await compactTerminalV2Runs(c);
  expect(await count('catalog_ingest_v2_runs')).toBeLessThanOrEqual(8);
  if(i>0)expect(retained.archived).toBeGreaterThanOrEqual(1);
  if(i===15&&initialPacket){
   expect((await send(base,'POST',initialPacket.run)).status).toBe(200);
   expect((await send(base+'/'+initialPacket.run.runId+'/chunks','POST',initialPacket.chunks[0])).status).toBe(200);
   expect((await observeIngestJournal(c,initialPacket.run.runId)).phase).toBe('COMPLETED');
  }
  metrics.push({cycle:i+1,commit:sha,records:packets.run.recordCount,
   chunks:packets.run.totalChunks,revisionBefore:before,revisionAfter:result.syncRevision,
   journal:'COMPLETED',personal:personal.status,liveRuns:await count('catalog_ingest_v2_runs'),
   archivedRuns:await count('catalog_ingest_v2_archive_runs'),
   importerWriteRows:result.metrics.total,importerBound:result.metrics.requiredBound,
   retentionWriteRows:retained.rowsWritten,replayed:true,
   elapsedMs:Math.round(performance.now()-started)});
  previous=sha;
 }
 expect(metrics).toHaveLength(30);
 expect(await count('catalog_audit')).toBe(30);
 expect(await count('catalog_ingest_v2_archive_runs')).toBe(29);
 expect(await count('catalog_ingest_v2_runs')).toBe(1);
 expect(Number(await p.prepare('SELECT count(*) AS n FROM personal_app_events').first('n'))).toBe(4);
 expect(Number(await p.prepare('SELECT count(*) AS n FROM personal_app_operations').first('n'))).toBe(4);
 expect(Number(await p.prepare('SELECT count(*) AS n FROM personal_decision_events').first('n'))).toBeGreaterThan(0);
 expect(Number(await c.prepare('SELECT count(*) AS n FROM catalog_aliases').first('n'))).toBeGreaterThan(22);
 expect(await c.prepare("SELECT job_id FROM catalog_aliases WHERE alias_key='Amazon::rotated-2026'").first('job_id'))
  .toBe(initialJobId);
 expect((await c.prepare('PRAGMA foreign_key_check').all()).results).toHaveLength(0);
 expect((await p.prepare('PRAGMA foreign_key_check').all()).results).toHaveLength(0);
 console.log('M47_CONTINUOUS_30_CYCLES '+JSON.stringify(metrics));
},360000);
