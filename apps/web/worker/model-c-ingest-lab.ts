// Detached synthetic-only HTTP handler. NEVER import from the deployable worker
// entrypoint. Does not receive remote bindings, tokens, quotas or owner IDs.
import type {JWTVerifyGetKey} from 'jose';
import {z} from 'zod';
import {canonical,sha256} from '../shared/canonical';
import {validateRun,validateChunk,MAX_INGEST_REQUEST_BYTES} from '../shared/model-c-ingestion';
import type {IngestRunInput,IngestChunkInput} from '../shared/model-c-ingestion';
import {ServiceAuthError,verifyServicePrincipal} from './model-c-service-auth';
import type {ServiceAuthConfig,ServicePrincipal} from './model-c-service-auth';

type OfflineQuota={syntheticVerified:true;writeUnitsRemaining:number};
type IngestLabOptions={
  catalog:D1Database;auth:ServiceAuthConfig;keys:JWTVerifyGetKey;
  quota?:OfflineQuota;
};
type RunRow={id:string;commit_sha:string;manifest_digest:string;projection_digest:string;
  plan_digest:string;expected_revision:number;total_chunks:number;principal_digest:string;
  run_digest:string;state:string};
type ChunkRow={chunk_index:number;chunk_digest:string;record_count:number;idempotency_key:string};
const limit=MAX_INGEST_REQUEST_BYTES;
function response(code:string,status:number,extra:Record<string,unknown>={}){
  return new Response(JSON.stringify({status:code,...extra}),{status,headers:{
    'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store',
    'X-Content-Type-Options':'nosniff',
  }});
}
async function receiveStrictJson(request:Request):Promise<unknown>{
  if(request.headers.get('content-type')?.split(';')[0]?.trim().toLowerCase()!=='application/json'||
      request.headers.has('content-encoding'))throw new ServiceAuthError('invalid_content_type',415);
  const declared=request.headers.get('content-length');
  if(declared && (!/^\d{1,7}$/.test(declared)||Number(declared)>limit))
    throw new ServiceAuthError('payload_too_large',413);
  if(!request.body)throw new ServiceAuthError('invalid_payload',400);
  const reader=request.body.getReader();
  const parts:Uint8Array[]=[];let size=0;
  try{
    while(true){
      const {value,done}=await reader.read();
      if(done)break;
      size+=value.byteLength;
      if(size>limit)throw new ServiceAuthError('payload_too_large',413);
      parts.push(value);
    }
  }finally{reader.releaseLock();}
  const bytes=new Uint8Array(size);let offset=0;
  for(const part of parts){bytes.set(part,offset);offset+=part.byteLength;}
  try{return JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(bytes));}
  catch{throw new ServiceAuthError('invalid_payload',400);}
}
async function readRun(db:D1Database,id:string){
  return db.prepare('SELECT * FROM catalog_ingest_runs WHERE id=?').bind(id).first<RunRow>();
}
async function readChunk(db:D1Database,id:string,index:number){
  return db.prepare('SELECT chunk_index,chunk_digest,record_count,idempotency_key FROM catalog_ingest_chunks WHERE run_id=? AND chunk_index=?')
    .bind(id,index).first<ChunkRow>();
}
const rowMatches=(row:RunRow,input:IngestRunInput,principalDigest:string,runDigest:string)=>
  row.commit_sha===input.commitSha&&row.manifest_digest===input.manifestDigest&&
  row.projection_digest===input.projectionDigest&&row.plan_digest===input.planDigest&&
  row.expected_revision===input.expectedRevision&&row.total_chunks===input.totalChunks&&
  row.principal_digest===principalDigest&&row.run_digest===runDigest&&row.state==='RECEIVING';
const chunkMatches=(row:ChunkRow,input:IngestChunkInput)=>
  row.chunk_index===input.chunkIndex&&row.chunk_digest===input.chunkDigest&&
  row.record_count===input.records.length&&row.idempotency_key===input.idempotencyKey;
async function runCount(db:D1Database){
  return Number(await db.prepare('SELECT count(*) AS n FROM catalog_ingest_runs').first('n'));
}
function quotaForWrite(q?:OfflineQuota) {
  // Only a synthetic, server-supplied laboratory budget is accepted here.
  // No client request, header or env flag can manufacture a Cloudflare quota attestation.
  if(!q||q.syntheticVerified!==true||!Number.isSafeInteger(q.writeUnitsRemaining)||
    q.writeUnitsRemaining<100)throw new ServiceAuthError('quota_unverified',503);
}
async function createRun(db:D1Database,input:IngestRunInput,principal:ServicePrincipal){
  const pd=await sha256(principal.clientId),digest=await sha256(canonical(input));
  const existing=await readRun(db,input.runId);
  if(existing)return rowMatches(existing,input,pd,digest)?
    response('REPLAY',200):response('RUN_CONFLICT',409);
  const schema=await db.prepare("SELECT version FROM model_c_schema WHERE scope='CATALOG'").first<number>('version');
  if(schema!==5)return response('schema_unavailable',503);
  const current=Number(await db.prepare("SELECT sync_revision FROM catalog_head WHERE scope='catalog'").first('sync_revision')??0);
  if(current!==input.expectedRevision)return response('STALE_CHECKPOINT',409);
  if(await runCount(db)>=8)return response('STAGING_CAPACITY',429);
  try{
    const result=await db.prepare(`INSERT INTO catalog_ingest_runs
      (id,commit_sha,manifest_digest,projection_digest,plan_digest,expected_revision,
       total_chunks,principal_digest,run_digest)
      SELECT ?,?,?,?,?,?,?,?,?
      WHERE ?=coalesce((SELECT sync_revision FROM catalog_head WHERE scope='catalog'),0)`)
      .bind(input.runId,input.commitSha,input.manifestDigest,input.projectionDigest,
        input.planDigest,input.expectedRevision,input.totalChunks,pd,digest,input.expectedRevision).run();
    if((result.meta.changes??0)!==1)return response('STALE_CHECKPOINT',409);
    return response('RUN_CREATED',201);
  }catch{
    // A lost reply can hide a committed D1 write. Inspect durable receipt.
    try{
      const observed=await readRun(db,input.runId);
      if(observed)return rowMatches(observed,input,pd,digest)?
        response('REPLAY',200):response('RUN_CONFLICT',409);
    }catch{/* preserve uncertain outcome */}
    return response('WRITE_OUTCOME_UNKNOWN',503);
  }
}
async function addChunk(db:D1Database,input:IngestChunkInput,principal:ServicePrincipal){
  const pd=await sha256(principal.clientId),run=await readRun(db,input.runId);
  if(!run||run.principal_digest!==pd)return response('RUN_NOT_FOUND',404);
  if(run.total_chunks!==input.totalChunks||run.state!=='RECEIVING')
    return response('RUN_CONFLICT',409);
  const already=await readChunk(db,input.runId,input.chunkIndex);
  if(already)return chunkMatches(already,input)?
    response('REPLAY',200):response('CHUNK_CONFLICT',409);
  const current=Number(await db.prepare("SELECT sync_revision FROM catalog_head WHERE scope='catalog'").first('sync_revision')??0);
  if(current!==run.expected_revision)return response('STALE_CHECKPOINT',409);
  const serialized=canonical(input.records);
  if(new TextEncoder().encode(serialized).length>limit)return response('payload_too_large',413);
  try{
    const result=await db.prepare(`INSERT INTO catalog_ingest_chunks
      (run_id,chunk_index,chunk_digest,idempotency_key,record_count,records_json)
      SELECT id,?,?,?,?,? FROM catalog_ingest_runs
      WHERE id=? AND principal_digest=? AND total_chunks=? AND state='RECEIVING'
        AND expected_revision=coalesce((SELECT sync_revision FROM catalog_head WHERE scope='catalog'),0)`)
      .bind(input.chunkIndex,input.chunkDigest,input.idempotencyKey,input.records.length,
        serialized,input.runId,pd,input.totalChunks).run();
    if((result.meta.changes??0)!==1)return response('RUN_CONFLICT',409);
    return response('CHUNK_STAGED',201);
  }catch{
    try{
      const observed=await readChunk(db,input.runId,input.chunkIndex);
      if(observed)return chunkMatches(observed,input)?
        response('REPLAY',200):response('CHUNK_CONFLICT',409);
    }catch{/* do not speculate */}
    return response('WRITE_OUTCOME_UNKNOWN',503);
  }
}
async function runStatus(db:D1Database,id:string,principal:ServicePrincipal){
  const row=await readRun(db,id);
  if(!row||row.principal_digest!==await sha256(principal.clientId))
    return response('RUN_NOT_FOUND',404);
  const chunks=(await db.prepare('SELECT chunk_index,chunk_digest,record_count,idempotency_key FROM catalog_ingest_chunks WHERE run_id=? ORDER BY chunk_index')
    .bind(id).all<ChunkRow>()).results;
  const missing=Array.from({length:row.total_chunks},(_,i)=>i)
    .filter(i=>!chunks.some(c=>c.chunk_index===i));
  // Staging does NOT validate source ancestry or advance the published head.
  return response('RECEIVING',200,{received:chunks.length,expected:row.total_chunks,
    complete:missing.length===0,missing,receipts:chunks});
}
/** The only constructor for the M46 test-only handler. No deployed routing uses it. */
export function createOfflineServiceIngestionHarness(options:IngestLabOptions){
  const {catalog,auth,keys,quota}=options;
  return async (request:Request):Promise<Response>=>{
    try{
      const principal=await verifyServicePrincipal(request,auth,keys);
      const url=new URL(request.url);
      if(url.search)return response('invalid_query',400);
      const base='/api/model-c/sync/runs';
      const isCreate=url.pathname===base;
      const match=/^\/api\/model-c\/sync\/runs\/(ingest:[a-f0-9]{64})\/(chunks|status)$/.exec(url.pathname);
      if(!isCreate&&!match)return response('not_found',404);
      if(isCreate&&request.method!=='POST'||match?.[2]==='chunks'&&request.method!=='POST'||
        match?.[2]==='status'&&request.method!=='GET')return response('method_not_allowed',405);
      if(!isCreate&&match?.[2]==='status')return await runStatus(catalog,match[1]!,principal);
      quotaForWrite(quota);
      if(isCreate)return await createRun(catalog,await validateRun(await receiveStrictJson(request)),principal);
      const body=await validateChunk(await receiveStrictJson(request));
      if(body.runId!==match![1])return response('RUN_CONFLICT',409);
      return await addChunk(catalog,body,principal);
    }catch(error){
      if(error instanceof ServiceAuthError)return response(error.code,error.status);
      if(error instanceof z.ZodError)return response('invalid_payload',400);
      if(error instanceof Error&&/^INGEST_/.test(error.message))
        return response('invalid_digest',400);
      // SQL, stack, source, credentials, data and D1 failures never escape.
      return response('database_unavailable',503);
    }
  };
}
