// M47 detached trusted-only v2 payload compaction. Archive digests and journal
// remain append-only; no service principal and no remote D1 path can invoke it.
import {observeIngestJournal} from './model-c-publication-journal';
export class V2RetentionError extends Error{constructor(readonly code:string){super(code);}}
const fail=(code:string):never=>{throw new V2RetentionError(code);};
type Run={id:string;run_digest:string;total_chunks:number;record_count:number;
 inventory_digest:string};
export async function compactTerminalV2Runs(db:D1Database,{limit=3}:{limit?:number}={}){
 if(!Number.isSafeInteger(limit)||limit<1||limit>5)return fail('V2_RETENTION_LIMIT');
 if(await db.prepare("SELECT version FROM model_c_schema WHERE scope='CATALOG'").first('version')!==7)
  return fail('V2_RETENTION_SCHEMA');
 const candidates=(await db.prepare(`SELECT r.id FROM catalog_ingest_v2_runs r
  JOIN catalog_runs p ON p.id=r.id AND p.state='PUBLISHED'
  WHERE EXISTS(SELECT 1 FROM catalog_ingest_journal j
    WHERE j.run_id=r.id AND j.phase='COMPLETED')
  AND NOT EXISTS(SELECT 1 FROM catalog_head h
    WHERE h.scope='catalog' AND h.run_id=r.id)
  ORDER BY r.id LIMIT ?`).bind(limit).all<{id:string}>()).results;
 const out={archived:0,payloadChunksReclaimed:0,rowsWritten:0,
  recoveredUnknownWriteOutcomes:0,ids:[] as string[]};
 for(const {id} of candidates){
  if((await observeIngestJournal(db,id)).phase!=='COMPLETED')
   return fail('V2_RETENTION_NOT_TERMINAL');
  const run=await db.prepare(`SELECT id,run_digest,total_chunks,record_count,
    inventory_digest FROM catalog_ingest_v2_runs WHERE id=?`).bind(id).first<Run>();
  if(!run)return fail('V2_RETENTION_MISSING_SOURCE');
  const source=await db.prepare(`SELECT count(*) AS n,coalesce(sum(record_count),0) AS records
    FROM catalog_ingest_v2_chunks WHERE run_id=?`).bind(id)
   .first<{n:number;records:number}>();
  if(!source||source.n!==run.total_chunks||source.records!==run.record_count)
   return fail('V2_RETENTION_INCOMPLETE_SOURCE');
  try{
   const steps=[
    db.prepare(`INSERT INTO catalog_ingest_v2_archive_runs
      (id,commit_sha,manifest_digest,projection_digest,ledger_digest,
       catalog_content_digest,plan_digest,expected_revision,total_chunks,
       record_count,inventory_digest,principal_digest,run_digest)
      SELECT id,commit_sha,manifest_digest,projection_digest,ledger_digest,
       catalog_content_digest,plan_digest,expected_revision,total_chunks,
       record_count,inventory_digest,principal_digest,run_digest
      FROM catalog_ingest_v2_runs WHERE id=?`).bind(id),
    db.prepare(`INSERT INTO catalog_ingest_v2_archive_chunks
      (run_id,chunk_index,chunk_digest,idempotency_key,record_count)
      SELECT run_id,chunk_index,chunk_digest,idempotency_key,record_count
      FROM catalog_ingest_v2_chunks WHERE run_id=?`).bind(id),
    db.prepare('DELETE FROM catalog_ingest_v2_chunks WHERE run_id=?').bind(id),
    db.prepare('DELETE FROM catalog_ingest_v2_runs WHERE id=?').bind(id),
   ];
   const completed=await db.batch(steps);
   out.rowsWritten+=completed.reduce((n,r)=>n+(r.meta.rows_written??0),0);
  }catch{
   const [a,b]=await Promise.all([
     db.prepare('SELECT run_digest,total_chunks,record_count,inventory_digest FROM catalog_ingest_v2_archive_runs WHERE id=?')
      .bind(id).first<Run>(),
     db.prepare('SELECT id FROM catalog_ingest_v2_runs WHERE id=?').bind(id).first(),
   ]);
   if(a&&a.run_digest===run.run_digest&&a.inventory_digest===run.inventory_digest&&!b){
    const n=Number(await db.prepare('SELECT count(*) AS n FROM catalog_ingest_v2_archive_chunks WHERE run_id=?')
     .bind(id).first('n'));
    if(n!==run.total_chunks)return fail('V2_RETENTION_ARCHIVE_INCOMPLETE');
    // D1 committed before the network/driver lost its ACK. This is a
    // completed archive, even though meta.rows_written cannot be recovered
    // from the rejected call; account for it separately, never as zero cost.
    out.archived++;out.payloadChunksReclaimed+=run.total_chunks;
    out.recoveredUnknownWriteOutcomes++;out.ids.push(id);
    continue;
   }
   return fail('V2_RETENTION_OUTCOME_UNKNOWN');
  }
  const [archive,live,chunkCount]=await Promise.all([
    db.prepare('SELECT run_digest,inventory_digest,record_count FROM catalog_ingest_v2_archive_runs WHERE id=?')
     .bind(id).first<Run>(),
    db.prepare('SELECT id FROM catalog_ingest_v2_runs WHERE id=?').bind(id).first(),
    db.prepare('SELECT count(*) AS n FROM catalog_ingest_v2_archive_chunks WHERE run_id=?')
     .bind(id).first<number>('n'),
  ]);
  if(!archive||live||archive.run_digest!==run.run_digest||
    archive.inventory_digest!==run.inventory_digest||
    archive.record_count!==run.record_count||chunkCount!==run.total_chunks)
    return fail('V2_RETENTION_POSTCOMMIT_INCOMPLETE');
  out.archived++;out.payloadChunksReclaimed+=run.total_chunks;out.ids.push(id);
 }
 return {...out,remoteExecutionAuthorized:false as const};
}
