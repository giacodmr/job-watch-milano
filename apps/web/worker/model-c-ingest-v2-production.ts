// M49 deployable but default-denied service-only CATALOG v2 staging.
// No publication or PERSONAL access. Remote activation requires separate Gate B approval.
import type {JWTVerifyGetKey} from 'jose';
import {z} from 'zod';
import {canonical,sha256} from '../shared/canonical';
import {validateCatalogV2Run,validateCatalogV2Chunk} from '../shared/model-c-ingestion-v2';
import type {CatalogV2Run,CatalogV2Chunk} from '../shared/model-c-ingestion-v2';
import {ServiceAuthError,verifyServicePrincipal} from './model-c-service-auth';
import type {ServiceAuthConfig,ServicePrincipal} from './model-c-service-auth';
import {privateAccessConfig} from './private-access';
import type {PrivateAccessEnv} from './private-access';
import {verifiedWriteBudget,reservationStatements} from './data/model-c-quota-admission';
import type {WriteBudget} from './data/model-c-quota-admission';

type Options={catalog:D1Database;auth:ServiceAuthConfig;keys?:JWTVerifyGetKey|undefined;
  quota?:WriteBudget|undefined};
type RunRow={id:string;commit_sha:string;manifest_digest:string;projection_digest:string;
 ledger_digest:string;catalog_content_digest:string;plan_digest:string;expected_revision:number;
 total_chunks:number;record_count:number;inventory_digest:string;principal_digest:string;
 run_digest:string};
type ChunkRow={chunk_index:number;chunk_digest:string;idempotency_key:string;record_count:number};
const base='/api/model-c/sync/v2/runs';
const idPattern=/^ingest-v2:[a-f0-9]{64}$/;
const MAX_BYTES=56*1024;
function reply(status:string,code:number,other:Record<string,unknown>={}){
 return new Response(JSON.stringify({status,...other}),{status:code,headers:{
 'content-type':'application/json;charset=utf-8','cache-control':'no-store',
 'x-content-type-options':'nosniff'}});
}
async function json(request:Request){
 if(request.headers.get('content-type')?.split(';')[0]?.trim().toLowerCase()!=='application/json'
    ||request.headers.has('content-encoding'))throw new ServiceAuthError('invalid_content_type',415);
 const size=request.headers.get('content-length');
 if(size&&(!/^\d{1,7}$/.test(size)||Number(size)>MAX_BYTES))
   throw new ServiceAuthError('payload_too_large',413);
 if(!request.body)throw new ServiceAuthError('invalid_payload',400);
 const reader=request.body.getReader();const parts:Uint8Array[]=[];let bytes=0;
 try{
   while(true){const {value,done}=await reader.read();if(done)break;
     bytes+=value.byteLength;
     if(bytes>MAX_BYTES)throw new ServiceAuthError('payload_too_large',413);
     parts.push(value);
   }
 }finally{reader.releaseLock();}
 const all=new Uint8Array(bytes);let at=0;
 for(const part of parts){all.set(part,at);at+=part.length;}
 try{return JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(all));}
 catch{throw new ServiceAuthError('invalid_payload',400);}
}
const liveRun=(db:D1Database,id:string)=>db.prepare('SELECT * FROM catalog_ingest_v2_runs WHERE id=?').bind(id).first<RunRow>();
const archiveRun=(db:D1Database,id:string)=>db.prepare('SELECT * FROM catalog_ingest_v2_archive_runs WHERE id=?').bind(id).first<RunRow>();
const liveChunk=(db:D1Database,id:string,index:number)=>db.prepare(
 'SELECT chunk_index,chunk_digest,idempotency_key,record_count FROM catalog_ingest_v2_chunks WHERE run_id=? AND chunk_index=?'
).bind(id,index).first<ChunkRow>();
const archivedChunk=(db:D1Database,id:string,index:number)=>db.prepare(
 'SELECT chunk_index,chunk_digest,idempotency_key,record_count FROM catalog_ingest_v2_archive_chunks WHERE run_id=? AND chunk_index=?'
).bind(id,index).first<ChunkRow>();
const sameRun=(row:RunRow,run:CatalogV2Run,pd:string,digest:string)=>
 row.id===run.runId&&row.commit_sha===run.commitSha&&
 row.manifest_digest===run.manifestDigest&&row.projection_digest===run.projectionDigest&&
 row.ledger_digest===run.ledgerDigest&&row.catalog_content_digest===run.catalogContentDigest&&
 row.plan_digest===run.planDigest&&row.expected_revision===run.expectedRevision&&
 row.total_chunks===run.totalChunks&&row.record_count===run.recordCount&&
 row.inventory_digest===run.inventoryDigest&&row.principal_digest===pd&&row.run_digest===digest;
const sameChunk=(row:ChunkRow,c:CatalogV2Chunk)=>
 row.chunk_index===c.index&&row.chunk_digest===c.digest&&
 row.idempotency_key===c.idempotencyKey&&row.record_count===c.count;
async function create(db:D1Database,run:CatalogV2Run,p:ServicePrincipal,budget:WriteBudget){
 const pd=await sha256(p.clientId),digest=await sha256(canonical(run));
 const existing=await liveRun(db,run.runId);
 if(existing)return reply(sameRun(existing,run,pd,digest)?'REPLAY':'RUN_CONFLICT',
   sameRun(existing,run,pd,digest)?200:409);
 const archive=await archiveRun(db,run.runId);
 if(archive)return reply(sameRun(archive,run,pd,digest)?'ARCHIVED_REPLAY':'RUN_CONFLICT',
   sameRun(archive,run,pd,digest)?200:409);
 if(await db.prepare("SELECT version FROM model_c_schema WHERE scope='CATALOG'").first('version')!==7)
   return reply('schema_unavailable',503);
 const revision=Number(await db.prepare("SELECT sync_revision FROM catalog_head WHERE scope='catalog'").first('sync_revision')??0);
 if(revision!==run.expectedRevision)return reply('STALE_CHECKPOINT',409);
 try{
  const out=(await db.batch([...reservationStatements(db,budget,64),db.prepare(`INSERT INTO catalog_ingest_v2_runs
   (id,commit_sha,manifest_digest,projection_digest,ledger_digest,catalog_content_digest,
    plan_digest,expected_revision,total_chunks,record_count,inventory_digest,
    principal_digest,run_digest)
    SELECT ?,?,?,?,?,?,?,?,?,?,?,?,?
    WHERE ?=coalesce((SELECT sync_revision FROM catalog_head WHERE scope='catalog'),0)
    AND ((SELECT count(*) FROM catalog_ingest_runs)+
         (SELECT count(*) FROM catalog_ingest_v2_runs))<8`)
   .bind(run.runId,run.commitSha,run.manifestDigest,run.projectionDigest,run.ledgerDigest,
     run.catalogContentDigest,run.planDigest,run.expectedRevision,run.totalChunks,
     run.recordCount,run.inventoryDigest,pd,digest,run.expectedRevision)]))[2]!;
  const observed=await liveRun(db,run.runId);
  if(observed)return reply(sameRun(observed,run,pd,digest)?
     ((out.meta.changes??0)>0?'RUN_CREATED':'REPLAY'):'RUN_CONFLICT',
     sameRun(observed,run,pd,digest)?((out.meta.changes??0)>0?201:200):409);
  const newRev=Number(await db.prepare("SELECT sync_revision FROM catalog_head WHERE scope='catalog'").first('sync_revision')??0);
  if(newRev!==run.expectedRevision)return reply('STALE_CHECKPOINT',409);
  const count=Number(await db.prepare(`SELECT (SELECT count(*) FROM catalog_ingest_runs)+
    (SELECT count(*) FROM catalog_ingest_v2_runs) AS n`).first('n'));
  return count>=8?reply('STAGING_CAPACITY',429):reply('WRITE_OUTCOME_UNKNOWN',503);
 }catch{
  try{const current=await liveRun(db,run.runId);
   if(current)return reply(sameRun(current,run,pd,digest)?'REPLAY':'RUN_CONFLICT',
    sameRun(current,run,pd,digest)?200:409);
  }catch{/* outcome unknown */}
  return reply('WRITE_OUTCOME_UNKNOWN',503);
 }
}
async function add(db:D1Database,c:CatalogV2Chunk,p:ServicePrincipal,budget:WriteBudget){
 const pd=await sha256(p.clientId),run=await liveRun(db,c.runId);
 if(!run){
  const archive=await archiveRun(db,c.runId);
  if(!archive||archive.principal_digest!==pd)return reply('RUN_NOT_FOUND',404);
  const item=await archivedChunk(db,c.runId,c.index);
  return reply(item&&sameChunk(item,c)?'ARCHIVED_REPLAY':'CHUNK_CONFLICT',
    item&&sameChunk(item,c)?200:409);
 }
 if(run.principal_digest!==pd)return reply('RUN_NOT_FOUND',404);
 if(run.total_chunks!==c.totalChunks||c.index>=run.total_chunks)return reply('RUN_CONFLICT',409);
 const original=await liveChunk(db,c.runId,c.index);
 if(original)return reply(sameChunk(original,c)?'REPLAY':'CHUNK_CONFLICT',
   sameChunk(original,c)?200:409);
 const records=canonical(c.records);
 if(new TextEncoder().encode(records).byteLength>48*1024)return reply('payload_too_large',413);
 try{
  const result=(await db.batch([...reservationStatements(db,budget,16),db.prepare(`INSERT INTO catalog_ingest_v2_chunks
   (run_id,chunk_index,chunk_digest,idempotency_key,record_count,records_json)
   SELECT id,?,?,?,?,? FROM catalog_ingest_v2_runs WHERE id=? AND principal_digest=?
    AND total_chunks=? AND expected_revision=coalesce(
      (SELECT sync_revision FROM catalog_head WHERE scope='catalog'),0)
    AND NOT EXISTS (SELECT 1 FROM catalog_ingest_v2_chunks WHERE run_id=? AND chunk_index=?)`)
   .bind(c.index,c.digest,c.idempotencyKey,c.count,records,
     c.runId,pd,c.totalChunks,c.runId,c.index)]))[2]!;
  const now=await liveChunk(db,c.runId,c.index);
  if(now)return reply(sameChunk(now,c)?
    ((result.meta.changes??0)>0?'CHUNK_STAGED':'REPLAY'):'CHUNK_CONFLICT',
    sameChunk(now,c)?((result.meta.changes??0)>0?201:200):409);
  return reply('STALE_OR_UNKNOWN',503);
 }catch{
  try{const now=await liveChunk(db,c.runId,c.index);
   if(now)return reply(sameChunk(now,c)?'REPLAY':'CHUNK_CONFLICT',
      sameChunk(now,c)?200:409);
  }catch{/* unknown */}
  return reply('WRITE_OUTCOME_UNKNOWN',503);
 }
}
async function status(db:D1Database,id:string,p:ServicePrincipal){
 const pd=await sha256(p.clientId);
 const run=await liveRun(db,id),archive=run?null:await archiveRun(db,id);
 if(!run&&!archive||((run??archive)!.principal_digest!==pd))return reply('RUN_NOT_FOUND',404);
 const table=run?'catalog_ingest_v2_chunks':'catalog_ingest_v2_archive_chunks';
 const chunks=(await db.prepare(`SELECT chunk_index,chunk_digest,idempotency_key,record_count
   FROM ${table} WHERE run_id=? ORDER BY chunk_index`).bind(id).all<ChunkRow>()).results;
 const expected=(run??archive)!.total_chunks;
 const present=new Set(chunks.map(c=>c.chunk_index)),missing:number[]=[];
 // Status remains bounded even for very large manifests; clients can consult
 // the first missing 512 indices without an unbounded missing[] response.
 for(let i=0;i<expected&&missing.length<512;i++)if(!present.has(i))missing.push(i);
 const complete=chunks.length===expected&&chunks.every((c,i)=>c.chunk_index===i);
 if(!run&&!complete)return reply('archive_receipt_incomplete',503);
 return reply(run?'RECEIVING':'ARCHIVED',200,{complete,received:chunks.length,
   expected,missing,missingTruncated:!complete&&missing.length===512,
   receipts:chunks.length<=512?chunks:chunks.slice(0,512),
   receiptsTruncated:chunks.length>512});
}
function createPrivateV2Receiver(opts:Options){
 return async(request:Request):Promise<Response>=>{
  try{
   const p=await verifyServicePrincipal(request,opts.auth,opts.keys);
   const url=new URL(request.url);
   if(url.search)return reply('invalid_query',400);
   const match=new RegExp('^'+base+'/('+idPattern.source.slice(1,-1)+')/(chunks|status)$').exec(url.pathname);
   if(url.pathname!==base&&!match)return reply('not_found',404);
   if(url.pathname===base&&request.method!=='POST'||
       match?.[2]==='chunks'&&request.method!=='POST'||
       match?.[2]==='status'&&request.method!=='GET')
      return reply('method_not_allowed',405);
   if(match?.[2]==='status')return status(opts.catalog,match[1]!,p);
   if(!opts.quota||opts.quota.operatorVerified!==true||
     !Number.isSafeInteger(opts.quota.writeUnitsRemaining)||
     opts.quota.writeUnitsRemaining<100)return reply('quota_unverified',503);
   if(url.pathname===base){
   const run=await validateCatalogV2Run(await json(request));
   if(run.totalChunks>512||run.recordCount>20000)return reply('RUN_TOO_LARGE',413);
   return create(opts.catalog,run,p,opts.quota);
  }
   const c=await validateCatalogV2Chunk(await json(request));
   if(c.runId!==match![1])return reply('RUN_CONFLICT',409);
   return add(opts.catalog,c,p,opts.quota);
  }catch(e){
   if(e instanceof ServiceAuthError)return reply(e.code,e.status);
   if(e instanceof z.ZodError)return reply('invalid_payload',400);
   if(e instanceof Error&&/^V2_/.test(e.message))return reply('invalid_digest',400);
   return reply('database_unavailable',503);
  }
 };
}

/** All service access is denied in the committed template. These flags are
 * NOT proof of an account-wide quota reservation: M50 must attest budget,
 * CPU, storage, other consumers, and rollback before setting any values.
 */
export type PrivateIngestionEnv=PrivateAccessEnv&{
  PRIVATE_INGESTION_GATE?:string;
  PRIVATE_SERVICE_ACCESS_AUD?:string;
  PRIVATE_SERVICE_ALLOWED_CLIENT_ID?:string;
  PRIVATE_INGESTION_QUOTA_REMAINING?:string;
  PRIVATE_INGESTION_QUOTA_VALID_UNTIL?:string;
};
export function privateServiceGateEnabled(env:PrivateIngestionEnv):boolean{
 return env.APP_ENV==='private' &&
   env.PRIVATE_INGESTION_GATE==='gate-b-approved' &&
   env.PRIVATE_QUOTA_ATTESTED==='verified-under-budget';
}
/** A short-lived server attestation, not a client header or a quota reservation.
 * Lack of a trusted account-wide observation MUST deny all new writes.
 */
export function privateServiceQuota(env:PrivateIngestionEnv,now=Date.now()){
 return verifiedWriteBudget(env,now);
}
/** The service route must be dispatched BEFORE the interactive Access router.
 * It verifies a different application audience and a service-only JWT. */
export async function handlePrivateServiceIngestion(request:Request,
 env:PrivateIngestionEnv,testKeys?:JWTVerifyGetKey):Promise<Response>{
 if(!privateServiceGateEnabled(env))return reply('not_found',404);
 if(!env.CATALOG||!env.PERSONAL||env.CATALOG===env.PERSONAL)
   return reply('database_unavailable',503);
 try{
   const config=privateAccessConfig(env);
   if(!env.PRIVATE_SERVICE_ACCESS_AUD||
      env.PRIVATE_SERVICE_ACCESS_AUD===config.audience||
      !env.PRIVATE_SERVICE_ALLOWED_CLIENT_ID)
     return reply('service_config_missing',503);
   const quota=privateServiceQuota(env);
   return createPrivateV2Receiver({
     catalog:env.CATALOG,keys:testKeys,quota,
     auth:{
       hostname:config.host,issuer:config.issuer,
       audience:env.PRIVATE_SERVICE_ACCESS_AUD,
       allowedClientId:env.PRIVATE_SERVICE_ALLOWED_CLIENT_ID,
     },
   })(request);
 }catch{
   return reply('service_config_unavailable',503);
 }
}
