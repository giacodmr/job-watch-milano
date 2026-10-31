// Detached, read-only D1 v2 integrity audit and independent trusted projection comparison.
// Never treats a service JWT, a client digest or a journal row as Git authority.
import {canonical,sha256} from '../shared/canonical';
import {CATALOG_V2_CONTRACT,validateCatalogV2Run,validateCatalogV2Chunk,
 verifyCatalogV2AgainstTrusted,prepareCatalogV2Packets} from '../shared/model-c-ingestion-v2';
import type {CatalogV2Chunk} from '../shared/model-c-ingestion-v2';

export class V2StageError extends Error{constructor(readonly code:string){super(code);}}
const deny=(code:string):never=>{throw new V2StageError(code);};
type RunRow={id:string;commit_sha:string;manifest_digest:string;projection_digest:string;
 ledger_digest:string;catalog_content_digest:string;plan_digest:string;expected_revision:number;
 total_chunks:number;record_count:number;inventory_digest:string;principal_digest:string;
 run_digest:string;state:string};
type ChunkRow={chunk_index:number;chunk_digest:string;idempotency_key:string;record_count:number;
 records_json:string};
export async function auditReceivedV2Stage(db:D1Database,id:string){
 if(!/^ingest-v2:[a-f0-9]{64}$/.test(id))return deny('V2_INVALID_RUN');
 if(await db.prepare("SELECT version FROM model_c_schema WHERE scope='CATALOG'").first('version')!==7)
   return deny('V2_SCHEMA_MISMATCH');
 const row=await db.prepare('SELECT * FROM catalog_ingest_v2_runs WHERE id=?')
   .bind(id).first<RunRow>();
 if(!row)return deny('V2_UNKNOWN_RUN');
 if(row.state!=='RECEIVING'||!/^[a-f0-9]{64}$/.test(row.principal_digest))
   return deny('V2_INVALID_RUN_RECEIPT');
 const run=await validateCatalogV2Run({
  contract:CATALOG_V2_CONTRACT,scope:'CATALOG',runId:row.id,
  commitSha:row.commit_sha,manifestDigest:row.manifest_digest,
  projectionDigest:row.projection_digest,ledgerDigest:row.ledger_digest,
  catalogContentDigest:row.catalog_content_digest,planDigest:row.plan_digest,
  expectedRevision:row.expected_revision,schemaVersion:7,totalChunks:row.total_chunks,
  recordCount:row.record_count,inventoryDigest:row.inventory_digest,
 }).catch(()=>deny('V2_INVALID_RUN_RECEIPT'));
 if(row.run_digest!==await sha256(canonical(run)))return deny('V2_INVALID_RUN_RECEIPT');
 const chunks=(await db.prepare(`SELECT chunk_index,chunk_digest,idempotency_key,
   record_count,records_json FROM catalog_ingest_v2_chunks
   WHERE run_id=? ORDER BY chunk_index`).bind(id).all<ChunkRow>()).results;
 if(chunks.length!==run.totalChunks)return deny('V2_INCOMPLETE_CHUNKS');
 const received:CatalogV2Chunk[]=[];let count=0;
 for(let i=0;i<chunks.length;i++){
  const c=chunks[i]!;
  if(c.chunk_index!==i||new TextEncoder().encode(c.records_json).byteLength>48*1024)
    return deny('V2_CHUNK_INDEX_OR_SIZE');
  let records:unknown;
  try{records=JSON.parse(c.records_json);}catch{return deny('V2_CORRUPTED_JSON');}
  const checked=await validateCatalogV2Chunk({
   contract:CATALOG_V2_CONTRACT,scope:'CATALOG',runId:id,index:i,
   count:c.record_count,totalChunks:run.totalChunks,digest:c.chunk_digest,
   idempotencyKey:c.idempotency_key,records,
  }).catch(()=>deny('V2_INVALID_CHUNK_RECEIPT'));
  if(canonical(checked.records)!==c.records_json)return deny('V2_UNCANONICAL_CHUNK');
  count+=checked.count;received.push(checked);
 }
 if(count!==run.recordCount)return deny('V2_RECORD_COUNT_MISMATCH');
 if(await sha256(canonical(received.flatMap(c=>c.records)))!==run.inventoryDigest)
  return deny('V2_INVENTORY_MISMATCH');
 const head=Number(await db.prepare("SELECT sync_revision FROM catalog_head WHERE scope='catalog'").first('sync_revision')??0);
 if(head!==run.expectedRevision)return deny('V2_STALE_CATALOG_HEAD');
 const packetDigest=await sha256(canonical({run,chunkDigests:received.map(c=>c.digest)}));
 return {run,chunks:received,packetDigest,recordCount:count,
  independentlyVerifiedGit:false as const,publicationAuthorized:false as const};
}
type Trusted=Awaited<ReturnType<typeof prepareCatalogV2Packets>>;
/** Called only with packets independently rebuilt from verified Git, selection,
 * identity ledger and trusted plan. Full canonical comparison detects omissions. */
export async function verifyPersistedV2AgainstTrusted(db:D1Database,id:string,expected:Trusted){
 const receipt=await auditReceivedV2Stage(db,id);
 if(receipt.run.runId!==expected.run.runId)return deny('V2_TRUSTED_RUN_MISMATCH');
 const result=await verifyCatalogV2AgainstTrusted({
   run:receipt.run,chunks:receipt.chunks},expected);
 return {...result,runId:id,packetDigest:receipt.packetDigest,
  expectedRevision:receipt.run.expectedRevision,commitSha:receipt.run.commitSha,
  inventoryCount:receipt.recordCount,remoteExecutionAuthorized:false as const};
}
