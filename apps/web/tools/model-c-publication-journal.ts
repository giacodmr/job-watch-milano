// M47: trusted Node-only, durable CATALOG transition evidence.
// No Worker routes, service tokens, remote D1 or owner identifiers are accepted.
// The journal documents independently verified outcomes; it is NOT a source of
// Git provenance, nor a distributed transaction across CATALOG/PERSONAL.
import {canonical,sha256} from '../shared/canonical';
import {auditReceivedIngestStage} from './model-c-stage-attestation';

export const INGEST_PHASES=[
  'RECEIVING','COMPLETE','VERIFIED','PERSONAL_PREPARED',
  'CATALOG_PUBLISHED','PERSONAL_RECONCILED','COMPLETED',
  'RECOVERY_REQUIRED','CONFLICT','STALE','UNVERIFIABLE',
] as const;
export type IngestPhase=typeof INGEST_PHASES[number];
type Row={run_id:string;sequence:number;phase:IngestPhase;
  proof_digest:string;previous_digest:string;event_digest:string};
export class JournalError extends Error {
  constructor(readonly code:string){super(code);}
}
const deny=(code:string):never=>{throw new JournalError(code);};
const zero='0'.repeat(64);
const digest=/^[0-9a-f]{64}$/;
const runPattern=/^ingest:[0-9a-f]{64}$/;
const expectedNext:Record<string,string>={
  RECEIVING:'COMPLETE',COMPLETE:'VERIFIED',VERIFIED:'PERSONAL_PREPARED',
  PERSONAL_PREPARED:'CATALOG_PUBLISHED',
  CATALOG_PUBLISHED:'PERSONAL_RECONCILED',
  PERSONAL_RECONCILED:'COMPLETED',
};
const errorPhases=new Set<IngestPhase>(['RECOVERY_REQUIRED','CONFLICT','STALE','UNVERIFIABLE']);
function guardId(runId:string){
  if(!runPattern.test(runId))return deny('JOURNAL_INVALID_RUN');
}
export async function observeIngestJournal(catalog:D1Database,runId:string){
  guardId(runId);
  if(await catalog.prepare("SELECT version FROM model_c_schema WHERE scope='CATALOG'")
      .first<number>('version')!==6)return deny('JOURNAL_SCHEMA_UNAVAILABLE');
  const run=await catalog.prepare('SELECT run_digest FROM catalog_ingest_runs WHERE id=?')
    .bind(runId).first<{run_digest:string}>();
  if(!run)return deny('JOURNAL_UNKNOWN_RUN');
  const rows=(await catalog.prepare(
    'SELECT * FROM catalog_ingest_journal WHERE run_id=? ORDER BY sequence')
    .bind(runId).all<Row>()).results;
  if(!rows.length)return deny('JOURNAL_MISSING_INITIAL_EVENT');
  if(rows[0]!.phase!=='RECEIVING'||rows[0]!.sequence!==0||
    rows[0]!.proof_digest!==run.run_digest||rows[0]!.event_digest!==run.run_digest||
    rows[0]!.previous_digest!==zero)return deny('JOURNAL_INITIAL_CORRUPTION');
  for(let i=1;i<rows.length;i++){
    const prev=rows[i-1]!,row=rows[i]!;
    if(row.sequence!==i||row.previous_digest!==prev.event_digest||
      !digest.test(row.proof_digest)||!digest.test(row.event_digest)||
      (expectedNext[prev.phase]!==row.phase&&
        !(errorPhases.has(row.phase)&&!['COMPLETED','CONFLICT','STALE','UNVERIFIABLE'].includes(prev.phase))))
      return deny('JOURNAL_INVALID_CHAIN');
    if(row.event_digest!==await sha256(canonical({
      runId,sequence:i,phase:row.phase,proofDigest:row.proof_digest,
      previousDigest:prev.event_digest,
    })))return deny('JOURNAL_DIGEST_MISMATCH');
  }
  const last=rows[rows.length-1]!;
  return {runId,phase:last.phase,sequence:last.sequence,
    eventDigest:last.event_digest,events:rows.map(x=>({
      sequence:x.sequence,phase:x.phase,proofDigest:x.proof_digest,
      eventDigest:x.event_digest,
    }))};
}
export async function nextJournalStatement(db:D1Database,runId:string,
  phase:IngestPhase,proofDigest:string){
  if(!digest.test(proofDigest))return deny('JOURNAL_INVALID_PROOF_DIGEST');
  const current=await observeIngestJournal(db,runId);
  const already=current.events.find(x=>x.phase===phase);
  if(already){
    if(already.proofDigest!==proofDigest)return deny('JOURNAL_REPLAY_CONFLICT');
    return {status:'REPLAY' as const,statement:null};
  }
  if(expectedNext[current.phase]!==phase&&
    !(errorPhases.has(phase)&&!['COMPLETED','CONFLICT','STALE','UNVERIFIABLE'].includes(current.phase)))
    return deny('JOURNAL_INVALID_TRANSITION');
  if(phase==='COMPLETE'){
    const audit=await auditReceivedIngestStage(db,runId);
    if(audit.packetDigest!==proofDigest)return deny('JOURNAL_COMPLETENESS_PROOF_MISMATCH');
  }
  if(phase==='CATALOG_PUBLISHED'){
    // The caller MUST put this statement after the head switch, in the very
    // same D1 transaction. A SQL trigger checks that head/run binding exists.
    // Otherwise an isolated CALL before publication cannot append this phase.
  }
  const sequence=current.sequence+1,previousDigest=current.eventDigest;
  const eventDigest=await sha256(canonical({runId,sequence,phase,proofDigest,previousDigest}));
  return {status:'READY' as const,eventDigest,
    statement:{sql:`INSERT INTO catalog_ingest_journal
      (run_id,sequence,phase,proof_digest,previous_digest,event_digest)
      VALUES (?,?,?,?,?,?)`,
      values:[runId,sequence,phase,proofDigest,previousDigest,eventDigest],
      writes:{catalog_ingest_journal:2},
    }};
}
export async function advanceIngestJournal(db:D1Database,runId:string,
  phase:IngestPhase,proofDigest:string){
  const next=await nextJournalStatement(db,runId,phase,proofDigest);
  if(next.status==='REPLAY')return observeIngestJournal(db,runId);
  try{
    await db.prepare(next.statement!.sql).bind(...next.statement!.values).run();
  }catch{
    // Outcome of the SQL write may be UNKNOWN: reconcile with durable receipt,
    // never issue an automatic second insert into a possibly committed journal.
    const after=await observeIngestJournal(db,runId);
    const found=after.events.find(e=>e.phase===phase);
    if(found&&found.proofDigest===proofDigest)return after;
    return deny('JOURNAL_OUTCOME_UNKNOWN');
  }
  return observeIngestJournal(db,runId);
}
export async function advanceCompleteIngestJournal(db:D1Database,runId:string){
  const audit=await auditReceivedIngestStage(db,runId);
  return advanceIngestJournal(db,runId,'COMPLETE',audit.packetDigest);
}
