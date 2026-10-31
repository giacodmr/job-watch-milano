import {afterAll,beforeAll,describe,expect,it} from 'vitest';
import {Miniflare,convertV4MiniflareOptions} from 'miniflare';
import {generateKeyPair,SignJWT,createLocalJWKSet,exportJWK} from 'jose';
import type {JWTVerifyGetKey} from 'jose';
import {canonical,sha256} from '../shared/canonical';
import {CATALOG_V2_CONTRACT,validateCatalogV2Run,validateCatalogV2Chunk} from '../shared/model-c-ingestion-v2';
import {createOfflineV2IngestionHarness} from '../worker/model-c-ingest-v2-lab';
import {auditReceivedV2Stage} from '../tools/model-c-v2-stage-attestation';
import {advanceCompleteV2IngestJournal,observeIngestJournal} from '../tools/model-c-publication-journal';
import {applySchema} from '../tools/model-c-schema';
const host='sync.synthetic.invalid',issuer='https://job-watch-tests.cloudflareaccess.com';
const aud='a'.repeat(64),client='c'.repeat(32)+'.access';
const opts={hostname:host,issuer,audience:aud,allowedClientId:client};
const base='https://'+host+'/api/model-c/sync/v2/runs';
let runtime:Miniflare,catalog:D1Database,personal:D1Database,key:CryptoKey,keys:JWTVerifyGetKey;
let serial=0;
type Packet={run:Awaited<ReturnType<typeof validateCatalogV2Run>>;
 chunks:Awaited<ReturnType<typeof validateCatalogV2Chunk>>[]};
async function jwt(extra:Record<string,unknown>={}){
 return new SignJWT({sub:'',type:'app',common_name:client,...extra})
 .setProtectedHeader({alg:'RS256',kid:'service-key'}).setIssuer(issuer)
 .setAudience(aud).setIssuedAt().setExpirationTime('10m').sign(key);
}
async function packet(size=2):Promise<Packet>{
 const n=++serial,records=Array.from({length:size},(_,i)=>({
  kind:'company' as const,id:'company:'+n+':'+i,
  name:'Synthetic '+n+' '+i,configId:null,tier:null,priority:null,
  careerUrl:null,membership:'ACTIVE' as const,
  sourcePath:'synthetic/companies.py',sourceSha256:'a'.repeat(64),
 }));
 const chunks=[];
 for(const [index,record] of records.entries()){
  const subset=[record],digest=await sha256(canonical(subset));
  chunks.push({contract:CATALOG_V2_CONTRACT,scope:'CATALOG' as const,
   index,count:1,totalChunks:size,digest,records:subset});
 }
 const meta={contract:CATALOG_V2_CONTRACT,scope:'CATALOG' as const,
  commitSha:n.toString(16).padStart(40,'0'),manifestDigest:'b'.repeat(64),
  projectionDigest:'c'.repeat(64),ledgerDigest:'d'.repeat(64),
  catalogContentDigest:'e'.repeat(64),planDigest:'f'.repeat(64),
  expectedRevision:0,schemaVersion:7 as const,totalChunks:size,
  recordCount:size,inventoryDigest:await sha256(canonical(records))};
 const runId='ingest-v2:'+await sha256(canonical(meta));
 const run=await validateCatalogV2Run({...meta,runId});
 const valid=[];
 for(const c of chunks)valid.push(await validateCatalogV2Chunk({...c,runId,
  idempotencyKey:await sha256(canonical({runId,index:c.index,digest:c.digest}))}));
 return {run,chunks:valid};
}
const req=(url:string,token:string,method='GET',body?:unknown,extra:Record<string,string>={})=>
 new Request(url,{method,headers:{'cf-access-jwt-assertion':token,...(body===undefined?{}:{
 'content-type':'application/json'}),...extra},...(body===undefined?{}:{body:canonical(body)})});
const count=async(db:D1Database,table:string)=>
 Number(await db.prepare('SELECT count(*) AS n FROM '+table).first('n'));
beforeAll(async()=>{
 runtime=new Miniflare(convertV4MiniflareOptions({modules:true,cf:false,
  script:'export default {fetch(){return new Response("synthetic")}}',
  compatibilityDate:'2026-10-29',d1Databases:{
    CATALOG:'m47-v2-local-catalog',PERSONAL:'m47-v2-local-personal'}}));
 catalog=await runtime.getD1Database('CATALOG');personal=await runtime.getD1Database('PERSONAL');
 expect((await applySchema(catalog,'catalog')).applied).toBe(7);
 expect((await applySchema(personal,'personal')).applied).toBe(3);
 const pair=await generateKeyPair('RS256',{extractable:true});key=pair.privateKey;
 const jwk=await exportJWK(pair.publicKey);
 keys=createLocalJWKSet({keys:[{...jwk,alg:'RS256',kid:'service-key',use:'sig'}]});
});
afterAll(async()=>runtime?.dispose());
describe('M47 v2 persisted transport — synthetic-only D1',()=>{
 it('persists out-of-order chunks; resolves duplicates and durable receipts without PERSONAL writes',async()=>{
  const t=await jwt(),p=await packet(),h=createOfflineV2IngestionHarness({catalog,auth:opts,keys,
    quota:{syntheticVerified:true,writeUnitsRemaining:4000}});
  expect((await h(req(base,t,'POST',p.run))).status).toBe(201);
  expect((await h(req(base,t,'POST',p.run))).status).toBe(200);
  const url=base+'/'+p.run.runId+'/chunks';
  expect((await h(req(url,t,'POST',p.chunks[1]))).status).toBe(201);
  const pending=await (await h(req(base+'/'+p.run.runId+'/status',t))).json() as {missing:number[];complete:boolean};
  expect(pending.missing).toEqual([0]);expect(pending.complete).toBe(false);
  expect((await h(req(url,t,'POST',p.chunks[0]))).status).toBe(201);
  expect((await h(req(url,t,'POST',p.chunks[0]))).status).toBe(200);
  const done=await (await h(req(base+'/'+p.run.runId+'/status',t))).json() as typeof pending;
  expect(done.complete).toBe(true);
  const receipt=await auditReceivedV2Stage(catalog,p.run.runId);
  expect(receipt.recordCount).toBe(2);
  expect(receipt.independentlyVerifiedGit).toBe(false);
  expect((await advanceCompleteV2IngestJournal(catalog,p.run.runId)).phase).toBe('COMPLETE');
  expect((await observeIngestJournal(catalog,p.run.runId)).phase).toBe('COMPLETE');
  expect(await count(personal,'personal_decision_events')).toBe(0);
  expect(await count(catalog,'catalog_head')).toBe(0);
 });
 it('survives lost replies and concurrent identical chunk POSTs',async()=>{
  const t=await jwt(),p=await packet(1),h=createOfflineV2IngestionHarness({catalog,
   auth:opts,keys,quota:{syntheticVerified:true,writeUnitsRemaining:1000}});
  expect((await h(req(base,t,'POST',p.run))).status).toBe(201);
  const url=base+'/'+p.run.runId+'/chunks';
  const results=await Promise.all([h(req(url,t,'POST',p.chunks[0])),
    h(req(url,t,'POST',p.chunks[0]))]);
  expect(results.every(r=>[200,201,503].includes(r.status))).toBe(true);
  expect(await catalog.prepare('SELECT count(*) AS n FROM catalog_ingest_v2_chunks WHERE run_id=?')
    .bind(p.run.runId).first('n')).toBe(1);
  expect((await h(req(base+'/'+p.run.runId+'/status',t))).status).toBe(200);
 });
 it('rejects forged provenance, mutated fields, owner injection, invalid principal and PERSONAL route',async()=>{
  const t=await jwt(),p=await packet(1),h=createOfflineV2IngestionHarness({catalog,
   auth:opts,keys,quota:{syntheticVerified:true,writeUnitsRemaining:1000}});
  expect((await h(req(base,t,'POST',{...p.run,manifestDigest:'9'.repeat(64)}))).status).toBe(400);
  expect((await h(req(base,t,'POST',{...p.run,ownerId:'attacker'}))).status).toBe(400);
  expect((await h(req(base,t,'POST',p.run,{'x-owner-id':'attacker'}))).status).toBe(403);
  expect((await h(req(base,t,'POST',p.run))).status).toBe(201);
  const url=base+'/'+p.run.runId+'/chunks';
  expect((await h(req(url,t,'POST',{...p.chunks[0],records:[{kind:'job',ownerId:'x'}]}))).status).toBe(400);
  expect((await h(req(url,t,'POST',p.chunks[0]))).status).toBe(201);
  expect((await h(req(url,await jwt({sub:'browser',common_name:undefined}),'POST',p.chunks[0]))).status).toBeGreaterThanOrEqual(400);
  expect((await h(req('https://'+host+'/api/model-c/personal/commands',t,'POST',{}))).status).toBe(404);
  expect(await count(personal,'personal_owners')).toBe(0);
 });
 it('fails closed without synthetic quota attestation or on a missing chunk',async()=>{
  const t=await jwt(),p=await packet(2),closed=createOfflineV2IngestionHarness({catalog,auth:opts,keys});
  expect((await closed(req(base,t,'POST',p.run))).status).toBe(503);
  const h=createOfflineV2IngestionHarness({catalog,auth:opts,keys,
   quota:{syntheticVerified:true,writeUnitsRemaining:300}});
  expect((await h(req(base,t,'POST',p.run))).status).toBe(201);
  const url=base+'/'+p.run.runId+'/chunks';
  expect((await h(req(url,t,'POST',p.chunks[0]))).status).toBe(201);
  await expect(auditReceivedV2Stage(catalog,p.run.runId))
   .rejects.toMatchObject({code:'V2_INCOMPLETE_CHUNKS'});
  expect(await count(catalog,'catalog_head')).toBe(0);
 });
 it('does not import v2 receiver through deployable entrypoints',async()=>{
  const {readFile}=await import('node:fs/promises');
  for(const file of ['worker/index.ts','worker/private-runtime.ts']){
   const entry=await readFile(file,'utf8');
   expect(entry).not.toContain('model-c-ingest-v2-lab');
   expect(entry).not.toContain('/api/model-c/sync/v2/runs');
  }
 });
});
