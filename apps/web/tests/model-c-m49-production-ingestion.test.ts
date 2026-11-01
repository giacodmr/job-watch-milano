// M49: deployable service-only Cloudflare ingress, tested on real local D1.
// All data and principals below are synthetic. No Cloudflare account is contacted.
import {beforeAll,afterAll,describe,it,expect} from 'vitest';
import worker from '../worker/index';
import {build} from 'esbuild';
import {Miniflare,convertV4MiniflareOptions} from 'miniflare';
import {SignJWT,generateKeyPair,exportJWK,createLocalJWKSet} from 'jose';
import type {JWTVerifyGetKey} from 'jose';
import {applySchema} from '../tools/model-c-schema';
import {canonical,sha256} from '../shared/canonical';
import {handlePrivateServiceIngestion,privateServiceGateEnabled,privateServiceQuota}
  from '../worker/model-c-ingest-v2-production';
import type {PrivateIngestionEnv} from '../worker/model-c-ingest-v2-production';
import {authenticatePrivateRequest} from '../worker/private-access';
import {reservePersonalWriteBudget} from '../worker/data/model-c-quota-admission';
import {stageCheckedV2Packets} from '../tools/model-c-m49-service-client';

const host='jobs.example.com',issuer='https://job-watch-tests.cloudflareaccess.com';
const userAudience='a'.repeat(64),serviceAudience='s'.repeat(64);
const clientId='serviceclient1234.access',userSub='access-user-12345678';
const url='https://'+host;
let mf:Miniflare,catalog:D1Database,personal:D1Database,keys:JWTVerifyGetKey;
let privateKey:CryptoKey;
const gate:PrivateIngestionEnv={
 APP_ENV:'private',PRIVATE_HOSTNAME:host,PRIVATE_ACCESS_ISSUER:issuer,
 PRIVATE_ACCESS_AUD:userAudience,PRIVATE_ALLOWED_SUB:userSub,PRIVATE_OWNER_ID:'private-owner-xyz',
 PRIVATE_INGESTION_GATE:'gate-b-approved',PRIVATE_QUOTA_ATTESTED:'verified-under-budget',
 PRIVATE_SERVICE_ACCESS_AUD:serviceAudience,PRIVATE_SERVICE_ALLOWED_CLIENT_ID:clientId,
 PRIVATE_INGESTION_QUOTA_REMAINING:'30000',
};
function env():PrivateIngestionEnv{return {...gate,CATALOG:catalog,PERSONAL:personal,
 PRIVATE_INGESTION_QUOTA_VALID_UNTIL:new Date(Date.now()+120000).toISOString()};}
async function token(service=true){
 return new SignJWT(service?
   {sub:'',type:'app',common_name:clientId}:
   {sub:userSub,email:'user@example.test',type:'app'})
 .setProtectedHeader({alg:'RS256',kid:'test-key'}).setIssuer(issuer)
 .setAudience(service?serviceAudience:userAudience).setIssuedAt()
 .setExpirationTime('10m').sign(privateKey);
}
function request(path:string,secret?:string,method='GET',payload?:unknown,extra?:HeadersInit){
 const headers=new Headers(extra);
 if(secret)headers.set('cf-access-jwt-assertion',secret);
 if(payload!==undefined)headers.set('content-type','application/json');
 return new Request(url+path,{method,headers,
  ...(payload===undefined?{}:{body:JSON.stringify(payload)})});
}
beforeAll(async()=>{
 const bundle=await build({entryPoints:['worker/index.ts'],bundle:true,write:false,
   format:'esm',platform:'browser',target:'es2023'});
 mf=new Miniflare(convertV4MiniflareOptions({modules:true,
   script:bundle.outputFiles[0]!.text,compatibilityDate:'2026-10-29',cf:false,
   bindings:{APP_ENV:'local'},d1Databases:{CATALOG:'m49-catalog',PERSONAL:'m49-personal'}}));
 catalog=await mf.getD1Database('CATALOG');
 personal=await mf.getD1Database('PERSONAL');
 await applySchema(catalog,'catalog');
 await applySchema(personal,'personal');
 const pair=await generateKeyPair('RS256',{extractable:true});
 privateKey=pair.privateKey;
 const jwk=await exportJWK(pair.publicKey);
 keys=createLocalJWKSet({keys:[{...jwk,kid:'test-key',alg:'RS256',use:'sig'}]});
});
afterAll(async()=>{await mf?.dispose();});

describe('M49 default-denied service ingestion boundary',()=>{
 it('worker dispatch denies the service route before any remote bindings exist',async()=>{
  const res=await worker.fetch(request('/api/model-c/sync/v2/runs',undefined,'POST',{}),
    {APP_ENV:'private'} as never);
  expect(res.status).toBe(404);
  expect(await res.json()).toMatchObject({status:'not_found'});
 });
 it('does not activate from a public template, partial flag, or unknown quota',async()=>{
  const secret=await token();
  expect(privateServiceGateEnabled({...env(),PRIVATE_INGESTION_GATE:''})).toBe(false);
  expect(privateServiceQuota({...env(),PRIVATE_INGESTION_QUOTA_REMAINING:''})).toBeUndefined();
  expect(privateServiceQuota({...env(),PRIVATE_INGESTION_QUOTA_REMAINING:'60000'})).toBeUndefined();
  expect(privateServiceQuota({...env(),PRIVATE_INGESTION_QUOTA_VALID_UNTIL:
    new Date(Date.now()+3600000).toISOString()})).toBeUndefined();
  expect(privateServiceQuota(env())).toMatchObject({operatorVerified:true,writeUnitsRemaining:30000});
  const disabled=await handlePrivateServiceIngestion(request('/api/model-c/sync/v2/runs',secret),
   {...env(),PRIVATE_INGESTION_GATE:''},keys);
  expect(disabled.status).toBe(404);
  const unknown=await handlePrivateServiceIngestion(request('/api/model-c/sync/v2/runs',secret,'POST',{}),
   {...env(),PRIVATE_INGESTION_QUOTA_REMAINING:''},keys);
  expect(unknown.status).toBe(503);
  expect((await unknown.json() as {status:string}).status).toBe('quota_unverified');
 });
 it('rejects interactive Access identity, missing JWT, bad host and forged owner',async()=>{
  const service=await token(),interactive=await token(false);
  for(const req of [
   request('/api/model-c/sync/v2/runs',undefined),
   request('/api/model-c/sync/v2/runs',interactive),
   new Request('https://preview.example.com/api/model-c/sync/v2/runs',
     {headers:{'cf-access-jwt-assertion':service}}),
   request('/api/model-c/sync/v2/runs',service,'GET',undefined,{'x-owner-id':'attacker'}),
   request('/api/model-c/sync/v2/runs',service,'GET',undefined,{'origin':url}),
  ]){
   const response=await handlePrivateServiceIngestion(req,env(),keys);
   expect([401,403]).toContain(response.status);
  }
  await expect(authenticatePrivateRequest(request('/',service),env(),keys))
   .rejects.toMatchObject({status:401});
 });
 it('stages a canonical v2 run/chunk, resumes, replays, and refuses conflicting bytes',async()=>{
  const secret=await token();
  const record={kind:'identity',jobId:'job:'+'b'.repeat(64),
    companyId:'synthetic-company',originJobKey:'fixture-key'};
  const records=[record],digest=await sha256(canonical(records));
  const unsigned={
   contract:'job-watch-model-c-ingestion/2',scope:'CATALOG',
   commitSha:'1'.repeat(40),manifestDigest:'2'.repeat(64),
   projectionDigest:'3'.repeat(64),ledgerDigest:'4'.repeat(64),
   catalogContentDigest:'5'.repeat(64),planDigest:'6'.repeat(64),
   expectedRevision:0,schemaVersion:7,totalChunks:1,recordCount:1,
   inventoryDigest:digest,
  };
  const run={...unsigned,runId:'ingest-v2:'+await sha256(canonical(unsigned))};
  const chunk={contract:'job-watch-model-c-ingestion/2',scope:'CATALOG',
    runId:run.runId,index:0,count:1,totalChunks:1,digest,records,
    idempotencyKey:await sha256(canonical({runId:run.runId,index:0,digest}))};
  const base='/api/model-c/sync/v2/runs',path=base+'/'+run.runId;
  const post=(p:string,value:unknown)=>handlePrivateServiceIngestion(
   request(p,secret,'POST',value),env(),keys);
  expect((await post(base,run)).status).toBe(201);
  expect((await post(base,run)).status).toBe(200);
  expect((await post(path+'/chunks',chunk)).status).toBe(201);
  expect((await post(path+'/chunks',chunk)).status).toBe(200);
  const progress=await handlePrivateServiceIngestion(request(path+'/status',secret),env(),keys);
  expect(progress.status).toBe(200);
  expect(await progress.json()).toMatchObject({complete:true,received:1,expected:1});
  const mutated={...chunk,records:[{...record,companyId:'evil'}]};
  expect((await post(path+'/chunks',mutated)).status).toBe(400);
  const staged=await stageCheckedV2Packets({run:run as never,chunks:[chunk] as never},{
    endpoint:url,serviceJwt:secret,gateBApproved:true,
    transport:r=>handlePrivateServiceIngestion(r,env(),keys),
  });
  expect(staged).toMatchObject({status:'STAGED_NOT_PUBLISHED',received:1,
    publicationAuthorized:false});
  const lostAck=await stageCheckedV2Packets({run:run as never,chunks:[chunk] as never},{
    endpoint:url,serviceJwt:secret,gateBApproved:true,
    transport:async r=>{
      const response=await handlePrivateServiceIngestion(r,env(),keys);
      if(r.method==='POST')throw Error('SYNTHETIC_LOST_ACK_AFTER_COMMIT');
      return response;
    },
  });
  expect(lostAck).toMatchObject({status:'STAGED_NOT_PUBLISHED',received:1});
  await expect(stageCheckedV2Packets({run:run as never,chunks:[chunk] as never},{
    endpoint:url,serviceJwt:secret,gateBApproved:false,
    transport:r=>handlePrivateServiceIngestion(r,env(),keys),
  })).rejects.toThrow('M49_GATE_B_CLOSED');
  const count=await catalog.prepare('SELECT COUNT(*) AS n FROM catalog_ingest_v2_chunks').first('n');
  expect(count).toBe(1);
  const charged=Number(await catalog.prepare('SELECT charged FROM catalog_write_totals WHERE day=?')
    .bind(new Date().toISOString().slice(0,10)).first('charged')??0);
  // 64 units reserved with the run, 16 with the chunk, and 0 on replay.
  expect(charged).toBe(80);
  const head=await catalog.prepare("SELECT sync_revision FROM catalog_head WHERE scope='catalog'").first('sync_revision');
  expect(head??0).toBe(0);
  // Service never advances the canonical head, publishes, or changes PERSONAL.
  expect(await personal.prepare('SELECT COUNT(*) AS n FROM personal_app_events').first('n')).toBe(0);
 });
 it('rejects concurrent writes exceeding the common durable account budget',async()=>{
   const budget={operatorVerified:true as const,day:new Date().toISOString().slice(0,10),
     writeUnitsRemaining:200};
   const results=await Promise.allSettled([
     reservePersonalWriteBudget(catalog,budget,64),
     reservePersonalWriteBudget(catalog,budget,64),
   ]);
   expect(results.filter(r=>r.status==='fulfilled')).toHaveLength(1);
   expect(results.filter(r=>r.status==='rejected')).toHaveLength(1);
   expect(Number(await catalog.prepare('SELECT charged FROM catalog_write_totals WHERE day=?')
     .bind(budget.day).first('charged'))).toBe(144);
 });

 it('serializes trusted publisher and APP reservations in one durable CATALOG budget',async()=>{
   const day=new Date().toISOString().slice(0,10);
   const before=Number(await catalog.prepare('SELECT charged FROM catalog_write_totals WHERE day=?')
     .bind(day).first('charged')??0);
   const ceiling=before+72; // both 64+32 cannot succeed
   const trustedPublisher=async()=>catalog.batch([
     catalog.prepare('INSERT INTO catalog_write_days VALUES (?,0) ON CONFLICT DO NOTHING').bind(day),
     // Exact SQL reservation shape used by the trusted M47/M50 importer.
     catalog.prepare('INSERT INTO catalog_write_reservations VALUES (?,?,?,?)')
       .bind(crypto.randomUUID(),day,64,ceiling),
   ]);
   const results=await Promise.allSettled([
     trustedPublisher(),reservePersonalWriteBudget(catalog,
       {operatorVerified:true,day,writeUnitsRemaining:ceiling},32),
   ]);
   expect(results.filter(r=>r.status==='fulfilled')).toHaveLength(1);
   expect(results.filter(r=>r.status==='rejected')).toHaveLength(1);
   const after=Number(await catalog.prepare('SELECT charged FROM catalog_write_totals WHERE day=?')
     .bind(day).first('charged'));
   expect([32,64]).toContain(after-before);
   expect(after).toBeLessThanOrEqual(ceiling);
   // Unknown quota must never reach the reservation SQL or PERSONAL writes.
   expect(privateServiceQuota({...env(),PRIVATE_QUOTA_ATTESTED:''})).toBeUndefined();
 });

});
