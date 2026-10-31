// M47 actual Miniflare process/runtime disposal and re-instantiation over
// one filesystem-backed D1 root. Independent of in-memory local adapters.
import {afterAll,beforeAll,expect,it} from 'vitest';
import {Miniflare,convertV4MiniflareOptions} from 'miniflare';
import {mkdtemp,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {resolve} from 'node:path';
import {generateKeyPair,SignJWT,createLocalJWKSet,exportJWK} from 'jose';
import {canonical,sha256} from '../shared/canonical';
import {applySchema} from '../tools/model-c-schema';
import {CATALOG_V2_CONTRACT,validateCatalogV2Run,validateCatalogV2Chunk}
 from '../shared/model-c-ingestion-v2';
import {createOfflineV2IngestionHarness} from '../worker/model-c-ingest-v2-lab';
import {auditReceivedV2Stage} from '../tools/model-c-v2-stage-attestation';
import {advanceCompleteV2IngestJournal,observeIngestJournal}
 from '../tools/model-c-publication-journal';
import {stageCatalog,publicationFixture,seedPersonal,owner}
 from './helpers/model-c-fixtures';
import {inspectPublishedModelCRecovery} from '../tools/model-c-import-recovery';
const host='sync.synthetic.invalid',issuer='https://m47-restart.cloudflareaccess.com',
 aud='a'.repeat(64),client='c'.repeat(32)+'.access';
const base='https://'+host+'/api/model-c/sync/v2/runs';
let root:string,runtime:Miniflare;
function boot(){
 return new Miniflare(convertV4MiniflareOptions({
  modules:true,cf:false,
  script:'export default {fetch(){return new Response("synthetic")}}',
  compatibilityDate:'2026-10-29',
  resourcePersistencePath:root,
  d1Databases:{CATALOG:'m47-cold-catalog',PERSONAL:'m47-cold-personal'},
 }));
}
async function databases(){
 return {c:await runtime.getD1Database('CATALOG'),
  p:await runtime.getD1Database('PERSONAL')};
}
beforeAll(async()=>{root=await mkdtemp(resolve(tmpdir(),'m47-persist-'));runtime=boot();});
afterAll(async()=>{await runtime?.dispose();if(root)await rm(root,{recursive:true,force:true});});
it('recovers partial v2 staging after two genuine Miniflare disposals',async()=>{
 let {c,p}=await databases();
 expect((await applySchema(c,'catalog')).applied).toBe(7);
 expect((await applySchema(p,'personal')).applied).toBe(3);
 const pair=await generateKeyPair('RS256');
 const jwk=await exportJWK(pair.publicKey);
 const keys=createLocalJWKSet({keys:[{...jwk,alg:'RS256',kid:'restart',use:'sig'}]});
 const jwt=await new SignJWT({type:'app',sub:'',common_name:client})
  .setProtectedHeader({alg:'RS256',kid:'restart'}).setIssuer(issuer)
  .setAudience(aud).setIssuedAt().setExpirationTime('10m').sign(pair.privateKey);
 const records=[0,1].map(i=>({
  kind:'company' as const,id:'company:cold:'+i,
  name:'Cold restart '+i,configId:null,tier:null,priority:null,
  careerUrl:null,membership:'ACTIVE' as const,
  sourcePath:'synthetic/restart.py',sourceSha256:'a'.repeat(64)}));
 const meta={contract:CATALOG_V2_CONTRACT,scope:'CATALOG' as const,
  commitSha:'d'.repeat(40),manifestDigest:'b'.repeat(64),
  projectionDigest:'c'.repeat(64),ledgerDigest:'d'.repeat(64),
  catalogContentDigest:'e'.repeat(64),planDigest:'f'.repeat(64),
  expectedRevision:0,schemaVersion:7 as const,totalChunks:2,recordCount:2,
  inventoryDigest:await sha256(canonical(records))};
 const runId='ingest-v2:'+await sha256(canonical(meta));
 const run=await validateCatalogV2Run({...meta,runId});
 const chunks=await Promise.all(records.map(async(record,index)=>{
  const digest=await sha256(canonical([record]));
  return validateCatalogV2Chunk({contract:CATALOG_V2_CONTRACT,
   scope:'CATALOG',runId,index,totalChunks:2,count:1,digest,
   idempotencyKey:await sha256(canonical({runId,index,digest})),records:[record]});
 }));
 const send=(database:D1Database,url:string,method:string,payload?:unknown)=>{
  const h=createOfflineV2IngestionHarness({catalog:database,keys,auth:{
   hostname:host,issuer,audience:aud,allowedClientId:client},
   quota:{syntheticVerified:true,writeUnitsRemaining:10000}});
  return h(new Request(url,{method,
   headers:{'cf-access-jwt-assertion':jwt,
    ...(payload===undefined?{}:{'content-type':'application/json'})},
   ...(payload===undefined?{}:{body:canonical(payload)})}));
 };
 expect((await send(c,base,'POST',run)).status).toBe(201);
 expect((await send(c,base+'/'+runId+'/chunks','POST',chunks[1])).status).toBe(201);
 await expect(auditReceivedV2Stage(c,runId)).rejects.toMatchObject({
  code:'V2_INCOMPLETE_CHUNKS'});
 expect((await observeIngestJournal(c,runId)).phase).toBe('RECEIVING');
 // Simulated power loss: dispose the *whole* runtime and recreate it with
 // the same resourcePersistencePath; no snapshot restore or fixture reseed.
 await runtime.dispose();runtime=boot();({c,p}=await databases());
 expect((await applySchema(c,'catalog')).applied).toBe(0);
 expect((await applySchema(p,'personal')).applied).toBe(0);
 expect((await observeIngestJournal(c,runId)).phase).toBe('RECEIVING');
 expect((await send(c,base+'/'+runId+'/chunks','POST',chunks[1])).status).toBe(200);
 expect((await send(c,base+'/'+runId+'/chunks','POST',chunks[0])).status).toBe(201);
 const verified=await auditReceivedV2Stage(c,runId);
 expect(verified.recordCount).toBe(2);
 await advanceCompleteV2IngestJournal(c,runId);
 await runtime.dispose();runtime=boot();({c,p}=await databases());
 expect((await observeIngestJournal(c,runId)).phase).toBe('COMPLETE');
 expect((await auditReceivedV2Stage(c,runId)).recordCount).toBe(2);
 expect(Number(await c.prepare('SELECT count(*) AS n FROM catalog_head').first('n'))).toBe(0);
 expect(Number(await p.prepare('SELECT count(*) AS n FROM personal_catalog_receipts').first('n'))).toBe(0);
 expect((await c.prepare('PRAGMA foreign_key_check').all()).results).toHaveLength(0);
});
it('keeps the published CATALOG head but reports PERSONAL pending after another real restart',async()=>{
 let {c,p}=await databases();
 await stageCatalog(c,'cold-published');
 await c.batch(publicationFixture(c,'cold-published'));
 await seedPersonal(p);
 const pending=await inspectPublishedModelCRecovery(c,p,{ownerId:owner});
 expect(pending.status).toBe('CATALOG_PUBLISHED_PERSONAL_PENDING');
 const before=(await c.prepare('SELECT * FROM catalog_head').all()).results;
 const personalBefore=(await p.prepare('SELECT * FROM personal_assessment_events').all()).results;
 await runtime.dispose();runtime=boot();({c,p}=await databases());
 expect((await c.prepare('SELECT * FROM catalog_head').all()).results).toEqual(before);
 expect((await p.prepare('SELECT * FROM personal_assessment_events').all()).results).toEqual(personalBefore);
 expect((await inspectPublishedModelCRecovery(c,p,{ownerId:owner})).status)
  .toBe('CATALOG_PUBLISHED_PERSONAL_PENDING');
 expect((await c.prepare('PRAGMA foreign_key_check').all()).results).toHaveLength(0);
 expect((await p.prepare('PRAGMA foreign_key_check').all()).results).toHaveLength(0);
});
