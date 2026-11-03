// Detached, operator-only v2 stage transport for a private password Worker.
// No Worker route, service JWT, PERSONAL write or generic SQL endpoint is exposed.
// The trusted Git importer separately verifies every persisted byte before HEAD.
import {canonical,sha256} from '../shared/canonical';
import {validateCatalogV2Run,validateCatalogV2Chunk} from '../shared/model-c-ingestion-v2';
import type {CatalogV2Run,CatalogV2Chunk} from '../shared/model-c-ingestion-v2';
import {isM50AuthorizedRemoteInitialPair} from './model-c-m50-d1-rest';
import {advanceCompleteV2IngestJournal,observeIngestJournal} from './model-c-publication-journal';
import {auditReceivedV2Stage} from './model-c-v2-stage-attestation';

type Packet={run:CatalogV2Run;chunks:CatalogV2Chunk[]};
type Budget={day:string;availableRows:number};
type RunReceipt={id:string;run_digest:string;principal_digest:string;
  expected_revision:number;total_chunks:number;record_count:number;inventory_digest:string};
type ChunkReceipt={chunk_index:number;chunk_digest:string;idempotency_key:string;record_count:number};
const deny=(s:string):never=>{throw Error(s);};
// Stable, public scope marker, not an authentication secret. The runtime
// capability is the independent authorization boundary.
const OPERATOR_SCOPE='job-watch-m50-operator-v2-initial/1';
const stageRow=(db:D1Database,runId:string)=>db.prepare(
 'SELECT id,run_digest,principal_digest,expected_revision,total_chunks,record_count,inventory_digest FROM catalog_ingest_v2_runs WHERE id=?'
).bind(runId).first<RunReceipt>();
const chunkRows=(db:D1Database,runId:string)=>db.prepare(
 'SELECT chunk_index,chunk_digest,idempotency_key,record_count FROM catalog_ingest_v2_chunks WHERE run_id=? ORDER BY chunk_index'
).bind(runId).all<ChunkReceipt>();
const sameChunk=(a:ChunkReceipt,c:CatalogV2Chunk)=>
  a.chunk_index===c.index&&a.chunk_digest===c.digest&&
  a.idempotency_key===c.idempotencyKey&&a.record_count===c.count;

/**
 * One resumable bounded staging slice. A caller must re-attest the operator
 * capability and today's account-wide Free quota for each invocation.
 * No automatic retry on uncertain writes: all outcomes are resolved by
 * immutable D1 receipts, or return REQUIRES_OPERATOR_RECOVERY.
 */
export async function stageM50InitialV2WithOperator(
 catalog:D1Database,personal:D1Database,packet:Packet,
 capability:object,budget:Budget,maxChunks=20,
){
 if(!isM50AuthorizedRemoteInitialPair(capability,catalog,personal,budget))
   deny('M50_INITIAL_STAGE_OPERATOR_NOT_AUTHORIZED');
 if(!Number.isSafeInteger(maxChunks)||maxChunks<1||maxChunks>20)
   deny('M50_INITIAL_STAGE_BATCH_UNBOUNDED');
 const run=await validateCatalogV2Run(packet.run);
 if(!Array.isArray(packet.chunks)||packet.chunks.length!==run.totalChunks||
    run.totalChunks>512||run.recordCount>20000)
   deny('M50_INITIAL_STAGE_PACKET_COUNT');
 const chunks=await Promise.all(packet.chunks.map(validateCatalogV2Chunk));
 chunks.sort((a,b)=>a.index-b.index);
 if(chunks.some((c,i)=>c.index!==i||c.runId!==run.runId||
      c.totalChunks!==run.totalChunks)||
    chunks.reduce((n,c)=>n+c.count,0)!==run.recordCount||
    await sha256(canonical(chunks.flatMap(c=>c.records)))!==run.inventoryDigest)
   deny('M50_INITIAL_STAGE_PACKET_PROOF');
 for(const chunk of chunks){
   if(new TextEncoder().encode(canonical(chunk.records)).byteLength>48*1024)
     deny('M50_INITIAL_STAGE_CHUNK_TOO_LARGE');
 }
 const principalDigest=await sha256(OPERATOR_SCOPE);
 const runDigest=await sha256(canonical(run));
 const expectedRun=(r:RunReceipt|null)=>
  !!r&&r.id===run.runId&&r.run_digest===runDigest&&
  r.principal_digest===principalDigest&&
  r.expected_revision===run.expectedRevision&&
  r.total_chunks===run.totalChunks&&r.record_count===run.recordCount&&
  r.inventory_digest===run.inventoryDigest;
 if(await catalog.prepare("SELECT version FROM model_c_schema WHERE scope='CATALOG'").first('version')!==7)
   deny('M50_INITIAL_STAGE_SCHEMA_MISMATCH');
 let row=await stageRow(catalog,run.runId);
 if(!row){
   const archived=await catalog.prepare('SELECT id FROM catalog_ingest_v2_archive_runs WHERE id=?')
     .bind(run.runId).first('id');
   if(archived)deny('M50_INITIAL_STAGE_ARCHIVED_REQUIRES_RECOVERY');
   const head=Number(await catalog.prepare(
     "SELECT sync_revision FROM catalog_head WHERE scope='catalog'"
   ).first('sync_revision')??0);
   if(head!==run.expectedRevision)deny('M50_INITIAL_STAGE_STALE_HEAD');
   // Bound admission is conservative, including journal trigger and indexes.
   // Staging writes are independent of importer reservations and must be
   // counted by the account-wide operator budget, not treated as free.
   if(budget.availableRows<maxChunks*8+32)
     deny('M50_INITIAL_STAGE_BUDGET_INSUFFICIENT');
   const count=Number(await catalog.prepare(
     'SELECT (SELECT count(*) FROM catalog_ingest_runs)+(SELECT count(*) FROM catalog_ingest_v2_runs) AS n'
   ).first('n')??0);
   if(count>=8)deny('M50_INITIAL_STAGE_CAPACITY');
   try{
     await catalog.prepare(`INSERT INTO catalog_ingest_v2_runs
      (id,commit_sha,manifest_digest,projection_digest,ledger_digest,catalog_content_digest,
       plan_digest,expected_revision,total_chunks,record_count,inventory_digest,
       principal_digest,run_digest)
      SELECT ?,?,?,?,?,?,?,?,?,?,?,?,?
      WHERE ?=coalesce((SELECT sync_revision FROM catalog_head WHERE scope='catalog'),0)
      AND ((SELECT count(*) FROM catalog_ingest_runs)+
           (SELECT count(*) FROM catalog_ingest_v2_runs))<8`)
      .bind(run.runId,run.commitSha,run.manifestDigest,run.projectionDigest,run.ledgerDigest,
        run.catalogContentDigest,run.planDigest,run.expectedRevision,run.totalChunks,
        run.recordCount,run.inventoryDigest,principalDigest,runDigest,run.expectedRevision).run();
   }catch{
     // A failed response may follow a committed insert; read only, never retry.
   }
   row=await stageRow(catalog,run.runId);
   if(!row)deny('M50_INITIAL_STAGE_RUN_OUTCOME_UNKNOWN');
 }
 if(!expectedRun(row))deny('M50_INITIAL_STAGE_RUN_CONFLICT');
 const existing=(await chunkRows(catalog,run.runId)).results;
 for(const receipt of existing){
   const desired=chunks[receipt.chunk_index];
   if(!desired||!sameChunk(receipt,desired))
     deny('M50_INITIAL_STAGE_RECEIPT_CONFLICT');
 }
 let received=existing.length,added=0,estimatedUpperBound=0;
 for(const chunk of chunks){
   if(existing.some(r=>r.chunk_index===chunk.index))continue;
   if(added>=maxChunks)break;
   if(!isM50AuthorizedRemoteInitialPair(capability,catalog,personal,budget))
     deny('M50_INITIAL_STAGE_OPERATOR_EXPIRED');
   // 8 write units per chunk is an admission allowance, not a measured
   // platform-wide bound; track other writers separately on the Free account.
   if(estimatedUpperBound+8+32>budget.availableRows)
     deny('M50_INITIAL_STAGE_BUDGET_INSUFFICIENT');
   const records=canonical(chunk.records);
   try{
     await catalog.prepare(`INSERT INTO catalog_ingest_v2_chunks
       (run_id,chunk_index,chunk_digest,idempotency_key,record_count,records_json)
       SELECT id,?,?,?,?,? FROM catalog_ingest_v2_runs
       WHERE id=? AND principal_digest=? AND total_chunks=?
       AND expected_revision=coalesce(
          (SELECT sync_revision FROM catalog_head WHERE scope='catalog'),0)
       AND NOT EXISTS(SELECT 1 FROM catalog_ingest_v2_chunks WHERE run_id=? AND chunk_index=?)`)
       .bind(chunk.index,chunk.digest,chunk.idempotencyKey,chunk.count,records,
         run.runId,principalDigest,run.totalChunks,run.runId,chunk.index).run();
   }catch{
     // Read-back below is the ONLY recovery step for a failed ACK.
   }
   const receipt=await catalog.prepare(
     'SELECT chunk_index,chunk_digest,idempotency_key,record_count FROM catalog_ingest_v2_chunks WHERE run_id=? AND chunk_index=?'
   ).bind(run.runId,chunk.index).first<ChunkReceipt>();
   if(!receipt)deny('M50_INITIAL_STAGE_CHUNK_OUTCOME_UNKNOWN');
   if(!sameChunk(receipt,chunk))deny('M50_INITIAL_STAGE_CHUNK_CONFLICT');
   added++;received++;estimatedUpperBound+=8;
 }
 const verifiedRows=(await chunkRows(catalog,run.runId)).results;
 if(verifiedRows.length!==received||verifiedRows.some((r,i)=>!sameChunk(r,chunks[r.chunk_index]!)||
    r.chunk_index!==i))deny('M50_INITIAL_STAGE_RECEIPT_MISMATCH');
 if(received!==run.totalChunks)return {
   status:'STAGING_IN_PROGRESS' as const,runId:run.runId,
   received,total:run.totalChunks,added,estimatedUpperBound:estimatedUpperBound+32,
   publicationAuthorized:false as const,
 };
 const proof=await auditReceivedV2Stage(catalog,run.runId);
 const journal=await observeIngestJournal(catalog,run.runId);
 if(journal.phase==='RECEIVING'){
   if(!isM50AuthorizedRemoteInitialPair(capability,catalog,personal,budget))
     deny('M50_INITIAL_STAGE_OPERATOR_EXPIRED');
   await advanceCompleteV2IngestJournal(catalog,run.runId);
 }
 const completed=await observeIngestJournal(catalog,run.runId);
 if(completed.phase!=='COMPLETE'||proof.packetDigest!==completed.events[1]?.proofDigest)
   deny('M50_INITIAL_STAGE_JOURNAL_UNVERIFIED');
 return {status:'STAGED_NOT_PUBLISHED' as const,runId:run.runId,
   received,total:run.totalChunks,added,estimatedUpperBound:estimatedUpperBound+40,
   publicationAuthorized:false as const};
}
