// M47: 19 independently isolated failure vectors on actual local Miniflare D1.
// This is transport/journal/retention fault coverage, NOT a substitute for the
// separate full 19-window importer crash/recovery certification.
import {afterAll,beforeAll,expect,it} from 'vitest';
import {Miniflare,convertV4MiniflareOptions} from 'miniflare';
import {generateKeyPair,SignJWT,createLocalJWKSet,exportJWK} from 'jose';
import type {JWTVerifyGetKey} from 'jose';
import {canonical,sha256} from '../shared/canonical';
import {applySchema} from '../tools/model-c-schema';
import {CATALOG_V2_CONTRACT,validateCatalogV2Run,validateCatalogV2Chunk}
 from '../shared/model-c-ingestion-v2';
import {createOfflineV2IngestionHarness} from '../worker/model-c-ingest-v2-lab';
import {auditReceivedV2Stage} from '../tools/model-c-v2-stage-attestation';
import {advanceCompleteV2IngestJournal,observeIngestJournal}
 from '../tools/model-c-publication-journal';
import {compactTerminalV2Runs} from '../tools/model-c-v2-ingest-retention';

const host='sync.synthetic.invalid',issuer='https://m47-faults.cloudflareaccess.com';
const aud='a'.repeat(64),client='c'.repeat(32)+'.access';
const base='https://'+host+'/api/model-c/sync/v2/runs';
let runtime:Miniflare,personal:D1Database,key:CryptoKey,keys:JWTVerifyGetKey;
async function jwt(audience=aud){
 return new SignJWT({type:'app',sub:'',common_name:client})
  .setProtectedHeader({alg:'RS256',kid:'fault-key'})
  .setIssuer(issuer).setAudience(audience).setIssuedAt()
  .setExpirationTime('10m').sign(key);
}
async function packet(index:number,expectedRevision=0){
 const records=Array.from({length:2},(_,i)=>({
  kind:'company' as const,id:'m47-fault:'+index+':'+i,
  name:'Synthetic fault '+index+' '+i,configId:null,tier:null,priority:null,
  careerUrl:null,membership:'ACTIVE' as const,
  sourcePath:'synthetic/fault.py',sourceSha256:'a'.repeat(64),
 }));
 const meta={contract:CATALOG_V2_CONTRACT,scope:'CATALOG' as const,
  commitSha:(index+100).toString(16).padStart(40,'0'),
  manifestDigest:'b'.repeat(64),projectionDigest:'c'.repeat(64),
  ledgerDigest:'d'.repeat(64),catalogContentDigest:'e'.repeat(64),
  planDigest:'f'.repeat(64),expectedRevision,schemaVersion:7 as const,
  totalChunks:2,recordCount:2,inventoryDigest:await sha256(canonical(records))};
 const runId='ingest-v2:'+await sha256(canonical(meta));
 const run=await validateCatalogV2Run({...meta,runId});
 const chunks=[];
 for(let i=0;i<2;i++){
  const group=[records[i]!],digest=await sha256(canonical(group));
  chunks.push(await validateCatalogV2Chunk({contract:CATALOG_V2_CONTRACT,
   scope:'CATALOG',runId,index:i,count:1,totalChunks:2,digest,
   idempotencyKey:await sha256(canonical({runId,index:i,digest})),records:group}));
 }
 return {run,chunks};
}
function brokenWrites(db:D1Database,needle:string,afterCommit:boolean){
 let failed=false;
 const wrap=(raw:D1PreparedStatement,sql:string):D1PreparedStatement=>({
  bind:(...args:unknown[])=>wrap(raw.bind(...args),sql),
  all:raw.all.bind(raw),first:raw.first.bind(raw),raw:raw.raw.bind(raw),
  run:async()=>{
   if(!failed&&sql.includes(needle)){
    failed=true;
    if(!afterCommit)throw Error('D1_DRIVER_UNAVAILABLE_BEFORE_COMMIT');
    await raw.run();throw Error('D1_DRIVER_LOST_ACK_AFTER_COMMIT');
   }
   return raw.run();
  },
 }) as D1PreparedStatement;
 return {prepare:(sql:string)=>wrap(db.prepare(sql),sql)} as D1Database;
}
const scenarios=[
 'missing JWT',
 'wrong JWT audience',
 'untrusted hostname',
 'quota evidence absent',
 'forged immutable run digest',
 'owner injection rejected',
 'run write interrupted before commit',
 'run committed but reply lost',
 'duplicate run replay',
 'stale revision denied',
 'missing numbered chunk denied',
 'chunk interrupted before commit',
 'chunk committed but reply lost',
 'out-of-order chunk delivery',
 'conflicting duplicate chunk',
 'chunk URL run mismatch',
 'journal sequence skipped',
 'journal mutation denied',
 'nonterminal archive and deletion denied',
] as const;
beforeAll(async()=>{
 runtime=new Miniflare(convertV4MiniflareOptions({modules:true,cf:false,
  script:'export default {fetch(){return new Response("synthetic")}}',
  compatibilityDate:'2026-10-29',
  d1Databases:Object.fromEntries([...scenarios.map((_,i)=>['C'+i,'fault-catalog-'+i]),
   ['PERSONAL','fault-personal']])}));
 personal=await runtime.getD1Database('PERSONAL');
 expect((await applySchema(personal,'personal')).applied).toBe(3);
 const pair=await generateKeyPair('RS256',{extractable:true});key=pair.privateKey;
 const jwk=await exportJWK(pair.publicKey);
 keys=createLocalJWKSet({keys:[{...jwk,alg:'RS256',kid:'fault-key',use:'sig'}]});
});
afterAll(async()=>runtime?.dispose());
it.each(scenarios.map((name,index)=>({name,index})))(
 'v2 fail-closed vector $index: $name',async({index})=>{
 const db=await runtime.getD1Database('C'+index);
 expect((await applySchema(db,'catalog')).applied).toBe(7);
 const p=await packet(index,index===9?1:0),token=await jwt();
 const harness=(catalog:D1Database=db,quota=true)=>
  createOfflineV2IngestionHarness({catalog,keys,
   auth:{hostname:host,issuer,audience:aud,allowedClientId:client},
   ...(quota?{quota:{syntheticVerified:true as const,writeUnitsRemaining:30000}}:{})});
 const request=(url:string,method:string,body?:unknown,t=token)=>
  new Request(url,{method,headers:{'cf-access-jwt-assertion':t,
   ...(body===undefined?{}:{'content-type':'application/json'})},
   ...(body===undefined?{}:{body:canonical(body)})});
 const send=(method:string,url:string,body?:unknown,catalog:D1Database=db,t=token)=>
  harness(catalog)(request(url,method,body,t));
 const chunks=base+'/'+p.run.runId+'/chunks';
 let result:Response;
 switch(index){
  case 0:
   result=await harness()(new Request(base,{method:'POST',body:canonical(p.run),
    headers:{'content-type':'application/json'}}));
   expect(result.status).toBeGreaterThanOrEqual(400);break;
  case 1:
   result=await send('POST',base,p.run,db,await jwt('wrong-audience'));
   expect(result.status).toBeGreaterThanOrEqual(400);break;
  case 2:
   result=await send('POST','https://wrong.synthetic.invalid/api/model-c/sync/v2/runs',p.run);
   expect(result.status).toBeGreaterThanOrEqual(400);break;
  case 3:
   expect((await harness(db,false)(request(base,'POST',p.run))).status).toBe(503);break;
  case 4:
   expect((await send('POST',base,{...p.run,manifestDigest:'0'.repeat(64)})).status).toBe(400);break;
  case 5:
   expect((await send('POST',base,{...p.run,ownerId:'untrusted-owner'})).status).toBe(400);break;
  case 6:
   expect((await send('POST',base,p.run,brokenWrites(db,'INSERT INTO catalog_ingest_v2_runs',false))).status).toBe(503);
   expect((await send('POST',base,p.run)).status).toBe(201);break;
  case 7:
   expect((await send('POST',base,p.run,brokenWrites(db,'INSERT INTO catalog_ingest_v2_runs',true))).status).toBe(200);
   expect((await send('POST',base,p.run)).status).toBe(200);break;
  case 8:
   expect((await send('POST',base,p.run)).status).toBe(201);
   expect((await send('POST',base,p.run)).status).toBe(200);break;
  case 9:
   expect((await send('POST',base,p.run)).status).toBe(409);break;
  default:
   expect((await send('POST',base,p.run)).status).toBe(201);
   if(index===10){
    expect((await send('POST',chunks,p.chunks[0])).status).toBe(201);
    await expect(auditReceivedV2Stage(db,p.run.runId)).rejects.toMatchObject({
     code:'V2_INCOMPLETE_CHUNKS'});
   }
   if(index===11){
    expect((await send('POST',chunks,p.chunks[0],
     brokenWrites(db,'INSERT INTO catalog_ingest_v2_chunks',false))).status).toBe(503);
    expect((await send('POST',chunks,p.chunks[0])).status).toBe(201);
   }
   if(index===12){
    expect((await send('POST',chunks,p.chunks[0],
     brokenWrites(db,'INSERT INTO catalog_ingest_v2_chunks',true))).status).toBe(200);
    expect((await send('POST',chunks,p.chunks[0])).status).toBe(200);
   }
   if(index===13){
    expect((await send('POST',chunks,p.chunks[1])).status).toBe(201);
    expect((await send('POST',chunks,p.chunks[0])).status).toBe(201);
    expect((await auditReceivedV2Stage(db,p.run.runId)).recordCount).toBe(2);
   }
   if(index===14){
    expect((await send('POST',chunks,p.chunks[0])).status).toBe(201);
    const records=[{...p.chunks[0]!.records[0]!,name:'conflicting company'}];
    const digest=await sha256(canonical(records));
    const different={...p.chunks[0]!,records,digest,
     idempotencyKey:await sha256(canonical({runId:p.run.runId,index:0,digest}))};
    expect((await send('POST',chunks,different)).status).toBe(409);
   }
   if(index===15){
    expect((await send('POST',base+'/ingest-v2:'+'e'.repeat(64)+'/chunks',p.chunks[0])).status).toBe(409);
   }
   if(index===16){
    await expect(db.prepare(`INSERT INTO catalog_ingest_journal
      (run_id,sequence,phase,proof_digest,previous_digest,event_digest)
      VALUES (?,2,'VERIFIED',?,?,?)`).bind(p.run.runId,'a'.repeat(64),
      'a'.repeat(64),'a'.repeat(64)).run()).rejects.toThrow();
   }
   if(index===17){
    expect((await send('POST',chunks,p.chunks[0])).status).toBe(201);
    expect((await send('POST',chunks,p.chunks[1])).status).toBe(201);
    await advanceCompleteV2IngestJournal(db,p.run.runId);
    await expect(db.prepare(`UPDATE catalog_ingest_journal SET proof_digest=?
     WHERE run_id=? AND sequence=1`).bind('0'.repeat(64),p.run.runId).run()).rejects.toThrow();
    expect((await observeIngestJournal(db,p.run.runId)).phase).toBe('COMPLETE');
   }
   if(index===18){
    expect((await send('POST',chunks,p.chunks[0])).status).toBe(201);
    await expect(db.prepare('DELETE FROM catalog_ingest_v2_runs WHERE id=?')
     .bind(p.run.runId).run()).rejects.toThrow();
    expect((await compactTerminalV2Runs(db)).archived).toBe(0);
    await expect(db.prepare(`INSERT INTO catalog_ingest_v2_archive_runs
     (id,commit_sha,manifest_digest,projection_digest,ledger_digest,
      catalog_content_digest,plan_digest,expected_revision,total_chunks,
      record_count,inventory_digest,principal_digest,run_digest)
     SELECT id,commit_sha,manifest_digest,projection_digest,ledger_digest,
      catalog_content_digest,plan_digest,expected_revision,total_chunks,
      record_count,inventory_digest,principal_digest,run_digest
     FROM catalog_ingest_v2_runs WHERE id=?`).bind(p.run.runId).run()).rejects.toThrow();
   }
 }
 expect(Number(await db.prepare('SELECT count(*) AS n FROM catalog_head').first('n'))).toBe(0);
 expect(Number(await personal.prepare('SELECT count(*) AS n FROM personal_catalog_receipts').first('n'))).toBe(0);
 expect((await db.prepare('PRAGMA foreign_key_check').all()).results).toHaveLength(0);
 },120000);
