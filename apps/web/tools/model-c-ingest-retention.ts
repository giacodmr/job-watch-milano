// M47 trusted offline-only terminal-run compaction.
// Never exported by Worker entrypoints; no service principal can invoke it.
// Immutable journal + archive receipts survive the deletion of bulky M46 rows.
import {observeIngestJournal} from './model-c-publication-journal';

export class RetentionError extends Error{
  constructor(readonly code:string){super(code);}
}
const denied=(code:string):never=>{throw new RetentionError(code);};
type ArchivedRow={id:string;run_digest:string;principal_digest:string;total_chunks:number};
export async function lookupArchivedIngest(db:D1Database,runId:string){
  if(!/^ingest:[a-f0-9]{64}$/.test(runId))return denied('INVALID_ARCHIVE_RUN');
  return db.prepare('SELECT * FROM catalog_ingest_archive_runs WHERE id=?')
    .bind(runId).first<ArchivedRow>();
}
/** Limit work per call; each D1 batch atomically moves one terminal run.
 * No elapsed-time threshold: proof of terminal status and non-current head is
 * the safety condition. Caller chooses retention cadence; unknown quota DENY.
 */
export async function compactTerminalIngestRuns(db:D1Database,{limit=3}:{limit?:number}={}){
  if(!Number.isSafeInteger(limit)||limit<1||limit>5)return denied('INVALID_RETENTION_LIMIT');
  if(await db.prepare("SELECT version FROM model_c_schema WHERE scope='CATALOG'")
    .first('version')!==7)return denied('RETENTION_SCHEMA_MISMATCH');
  const candidates=(await db.prepare(`SELECT r.id FROM catalog_ingest_runs r
    JOIN catalog_runs p ON p.id=r.id AND p.state='PUBLISHED'
    WHERE EXISTS(SELECT 1 FROM catalog_ingest_journal j
      WHERE j.run_id=r.id AND j.phase='COMPLETED')
    AND NOT EXISTS(SELECT 1 FROM catalog_head h
      WHERE h.scope='catalog' AND h.run_id=r.id)
    ORDER BY r.id LIMIT ?`).bind(limit).all<{id:string}>()).results;
  const result:{archived:number;payloadChunksReclaimed:number;writeRows:number;runIds:string[]}={
    archived:0,payloadChunksReclaimed:0,writeRows:0,runIds:[],
  };
  for(const {id} of candidates){
    const journal=await observeIngestJournal(db,id);
    if(journal.phase!=='COMPLETED')return denied('RETENTION_NON_TERMINAL');
    const run=await db.prepare('SELECT run_digest,total_chunks FROM catalog_ingest_runs WHERE id=?')
      .bind(id).first<{run_digest:string;total_chunks:number}>();
    if(!run)return denied('RETENTION_RUN_DISAPPEARED');
    const chunks=await db.prepare(
      'SELECT count(*) AS n FROM catalog_ingest_chunks WHERE run_id=?')
      .bind(id).first<number>('n');
    if(chunks!==run.total_chunks)return denied('RETENTION_INCOMPLETE_SOURCE');
    let rowsWritten=0;
    try{
      const sql=[
        db.prepare(`INSERT INTO catalog_ingest_archive_runs
          (id,commit_sha,manifest_digest,projection_digest,plan_digest,
            expected_revision,total_chunks,principal_digest,run_digest)
          SELECT id,commit_sha,manifest_digest,projection_digest,plan_digest,
            expected_revision,total_chunks,principal_digest,run_digest
          FROM catalog_ingest_runs WHERE id=?`).bind(id),
        db.prepare(`INSERT INTO catalog_ingest_archive_chunks
          (run_id,chunk_index,chunk_digest,idempotency_key,record_count)
          SELECT run_id,chunk_index,chunk_digest,idempotency_key,record_count
          FROM catalog_ingest_chunks WHERE run_id=?`).bind(id),
        db.prepare('DELETE FROM catalog_ingest_chunks WHERE run_id=?').bind(id),
        db.prepare('DELETE FROM catalog_ingest_runs WHERE id=?').bind(id),
      ];
      const executed=await db.batch(sql);
      rowsWritten=executed.reduce((n,r)=>n+(r.meta.rows_written??0),0);
    }catch{
      // A failed batch or lost response is ambiguous until the durable
      // archive and live rows are inspected. No blind deletion/retry.
      const archived=await lookupArchivedIngest(db,id);
      const live=await db.prepare('SELECT id FROM catalog_ingest_runs WHERE id=?')
        .bind(id).first();
      if(archived&&!live)continue;
      return denied('RETENTION_OUTCOME_UNKNOWN');
    }
    const archived=await lookupArchivedIngest(db,id);
    const live=await db.prepare('SELECT id FROM catalog_ingest_runs WHERE id=?')
      .bind(id).first();
    const archivedChunks=await db.prepare(
      'SELECT count(*) AS n FROM catalog_ingest_archive_chunks WHERE run_id=?')
      .bind(id).first<number>('n');
    if(!archived||live||archived.run_digest!==run.run_digest||
      archivedChunks!==chunks)return denied('RETENTION_POSTCOMMIT_MISMATCH');
    result.archived++;
    result.payloadChunksReclaimed+=chunks;
    result.writeRows+=rowsWritten;
    result.runIds.push(id);
  }
  return {...result,remoteExecutionAuthorized:false as const};
}
