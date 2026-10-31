// M47: read-only integrity audit of durable M46 staging receipts.
// This is NOT independent Git provenance verification and never authorizes publication.
// Detached Node/test-only module: do not import from any deployable Worker entrypoint.
import {canonical,sha256} from '../shared/canonical';
import {INGESTION_CONTRACT,validateChunk,validateRun,MAX_INGEST_REQUEST_BYTES} from '../shared/model-c-ingestion';
import type {IngestRecord} from '../shared/model-c-ingestion';

type RunRow={id:string;commit_sha:string;manifest_digest:string;projection_digest:string;
  plan_digest:string;expected_revision:number;total_chunks:number;principal_digest:string;
  run_digest:string;state:string};
type ChunkRow={run_id:string;chunk_index:number;chunk_digest:string;idempotency_key:string;
  record_count:number;records_json:string};
export class StageAuditError extends Error {
  constructor(readonly code:string){super(code);}
}
const deny=(code:string):never=>{throw new StageAuditError(code);};
const validRunId=(id:string)=>/^ingest:[a-f0-9]{64}$/.test(id);

/** A content-integrity gate only. Caller MUST separately verify Git ancestry,
 * authoritative projection, trusted selection/ledger, plan and PERSONAL context
 * before any future promotion. It performs no mutations on either database.
 */
export async function auditReceivedIngestStage(catalog:D1Database,runId:string){
  if(!validRunId(runId))return deny('INVALID_RUN_ID');
  const version=await catalog.prepare("SELECT version FROM model_c_schema WHERE scope='CATALOG'")
    .first<number>('version');
  if(version!==5)return deny('CATALOG_SCHEMA_MISMATCH');
  const row=await catalog.prepare('SELECT * FROM catalog_ingest_runs WHERE id=?')
    .bind(runId).first<RunRow>();
  if(!row)return deny('RUN_NOT_FOUND');
  if(row.state!=='RECEIVING')return deny('INVALID_RUN_STATE');
  if(!/^[a-f0-9]{64}$/.test(row.principal_digest))return deny('INVALID_PRINCIPAL_RECEIPT');
  const runData={
    contract:INGESTION_CONTRACT,scope:'CATALOG' as const,runId:row.id,
    commitSha:row.commit_sha,manifestDigest:row.manifest_digest,
    projectionDigest:row.projection_digest,planDigest:row.plan_digest,
    expectedRevision:row.expected_revision,schemaVersion:5 as const,
    totalChunks:row.total_chunks,
  };
  try{await validateRun(runData);}
  catch{return deny('RUN_RECEIPT_INVALID');}
  if(row.run_digest!==await sha256(canonical(runData)))return deny('RUN_RECEIPT_INVALID');
  const head=await catalog.prepare("SELECT sync_revision FROM catalog_head WHERE scope='catalog'")
    .first<number>('sync_revision');
  if((head??0)!==row.expected_revision)return deny('STALE_CATALOG_REVISION');

  const results=(await catalog.prepare('SELECT * FROM catalog_ingest_chunks WHERE run_id=? ORDER BY chunk_index')
    .bind(runId).all<ChunkRow>()).results;
  if(results.length!==row.total_chunks)return deny('INCOMPLETE_CHUNKS');
  const records:IngestRecord[]=[],ids=new Set<string>();
  const chunkDigests:string[]=[];
  for(let i=0;i<results.length;i++){
    const chunk=results[i]!;
    if(chunk.run_id!==runId||chunk.chunk_index!==i)return deny('CHUNK_INDEX_GAP');
    if(new TextEncoder().encode(chunk.records_json).byteLength>MAX_INGEST_REQUEST_BYTES)
      return deny('OVERSIZED_CHUNK');
    let parsed:unknown;
    try{parsed=JSON.parse(chunk.records_json);}
    catch{return deny('INVALID_CHUNK_PAYLOAD');}
    let valid:Awaited<ReturnType<typeof validateChunk>>;
    try{valid=await validateChunk({
      contract:INGESTION_CONTRACT,scope:'CATALOG',runId,chunkIndex:i,
      totalChunks:row.total_chunks,chunkDigest:chunk.chunk_digest,
      idempotencyKey:chunk.idempotency_key,records:parsed,
    });}
    catch{return deny('CHUNK_RECEIPT_INVALID');}
    if(valid.records.length!==chunk.record_count||
       canonical(valid.records)!==chunk.records_json)return deny('CHUNK_RECEIPT_INVALID');
    chunkDigests.push(valid.chunkDigest);
    for(const record of valid.records){
      const key=record.kind+':'+record.id;
      if(ids.has(key))return deny('DUPLICATE_RECORD');
      ids.add(key);records.push(record);
    }
  }
  const companies=new Set(records.filter(r=>r.kind==='company').map(r=>r.id));
  const sources=new Map(records.filter(r=>r.kind==='source').map(r=>[r.id,r.companyId]));
  for(const record of records){
    if(record.kind==='source'&&!companies.has(record.companyId))return deny('UNKNOWN_COMPANY');
    if(record.kind==='job'&&(!companies.has(record.companyId)||
      (record.sourceId!==null&&sources.get(record.sourceId)!==record.companyId)))
      return deny('UNKNOWN_JOB_SOURCE');
  }
  return {
    status:'PACKET_INTEGRITY_VERIFIED_ONLY' as const,
    runId,expectedRevision:row.expected_revision,receivedChunks:results.length,
    recordCount:records.length,
    packetDigest:await sha256(canonical({run:runData,chunkDigests})),
    // These claims explicitly do NOT attest to Git ancestry, source completeness
    // or the full CATALOG projection (M46 v1 is lossy by design).
    gitProvenanceVerified:false as const,
    fullCatalogProjectionVerified:false as const,
    publicationAuthorized:false as const,
  };
}
