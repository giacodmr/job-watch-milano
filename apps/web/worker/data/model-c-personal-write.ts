// PR #41: LOCAL SYNTHETIC ONLY. Never import from a browser bundle.
import {z} from 'zod';
import {canonical,sha256} from '../../shared/canonical';
import {getModelCCatalogJob,ModelCReadError} from './model-c-catalog';
import {ModelCPersonalReadError} from './model-c-personal';
import type {TrustedOwner} from './model-c-personal';

const jobId=z.string().regex(/^job:[a-f0-9]{64}$/);
const operationId=z.string().uuid();
const base={
  jobId,operationId,expectedRevision:z.number().int().min(0).max(2147483646),
  catalogRevision:z.number().int().positive().max(2147483646),
};
export const decisionCommandSchema=z.strictObject({
  ...base,kind:z.literal('DECISION'),
  decision:z.enum(['TO_REVIEW','INTERESTED','APPLIED','NOT_INTERESTED']).nullable(),
  reasonSummary:z.string().trim().max(360).nullable().default(null),
});
export const savedCommandSchema=z.strictObject({
  ...base,kind:z.literal('SAVED'),active:z.boolean(),
});
export const personalCommandSchema=z.discriminatedUnion('kind',[decisionCommandSchema,savedCommandSchema]);
export type PersonalCommand=z.infer<typeof personalCommandSchema>;
export class ModelCPersonalWriteError extends Error {
  constructor(public readonly code:string,public readonly status:number){super(code);}
}
type Current={revision:number;decision_override:number;decision:string|null;saved_override:number;saved_active:number};
type Imported={decision:string|null;saved:number};
type Operation={payload_sha256:string;response_json:string};
const checkSchema=async (db:D1Database)=>{
  const version=await db.prepare("SELECT version FROM model_c_schema WHERE scope='PERSONAL'").first<number>('version');
  if(version!==3)throw new ModelCPersonalWriteError('PERSONAL_SCHEMA_MISMATCH',503);
};
const readOperation=async(db:D1Database,owner:string,id:string)=>db.prepare(
  'SELECT payload_sha256,response_json FROM personal_app_operations WHERE owner_id=? AND operation_id=?')
  .bind(owner,id).first<Operation>();
function replay(existing:Operation,digest:string){
  if(existing.payload_sha256!==digest)throw new ModelCPersonalWriteError('IDEMPOTENCY_KEY_REUSED',409);
  return {...JSON.parse(existing.response_json) as Record<string,unknown>,replayed:true};
}
/** A single D1 batch is one transaction. A failing CAS assertion rolls back every statement.
 * No write ever targets CATALOG or imported PERSONAL projection tables. */
export async function executePersonalCommand(
 catalog:D1Database,personal:D1Database,owner:TrustedOwner,input:unknown,
){
  const cmd=personalCommandSchema.parse(input);
  if(catalog===personal)throw new ModelCPersonalWriteError('DATABASE_SCOPE_COLLISION',503);
  if(!owner?.ownerId || !/^synthetic-[a-z][a-z0-9-]{0,63}$/.test(owner.ownerId))
    throw new ModelCPersonalWriteError('SYNTHETIC_OWNER_REQUIRED',403);
  await checkSchema(personal);
  const digest=await sha256(canonical(cmd));
  const old=await readOperation(personal,owner.ownerId,cmd.operationId);
  if(old)return replay(old,digest);
  const head=await personal.prepare('SELECT revision FROM personal_heads WHERE owner_id=?')
    .bind(owner.ownerId).first<{revision:number}>();
  if(!head)throw new ModelCPersonalWriteError('PERSONAL_CONTEXT_UNAVAILABLE',404);
  const publication=await getModelCCatalogJob(catalog,cmd.jobId,cmd.catalogRevision);
  const job=publication.job;
  const current=await personal.prepare(`SELECT revision,decision_override,saved_override,
    decision,saved_active FROM personal_app_current WHERE owner_id=? AND job_id=?`)
    .bind(owner.ownerId,cmd.jobId).first<Current>();
  if((current?.revision??0)!==cmd.expectedRevision)
    throw new ModelCPersonalWriteError('REVISION_CONFLICT',409);
  const imported=await personal.prepare(`SELECT d.decision,
    CASE WHEN s.active=1 THEN 1 ELSE 0 END AS saved
    FROM personal_heads h
    LEFT JOIN personal_decision_current dc ON dc.owner_id=h.owner_id AND dc.job_id=?
    LEFT JOIN personal_decision_events d ON d.owner_id=dc.owner_id AND d.id=dc.event_id
    LEFT JOIN personal_reference_state s ON s.owner_id=h.owner_id AND s.job_id=? AND s.kind='SAVED'
    WHERE h.owner_id=?`).bind(cmd.jobId,cmd.jobId,owner.ownerId).first<Imported>();
  const previousDecision=current?.decision_override?current.decision:(imported?.decision??null);
  const previousSaved=current?.saved_override?current.saved_active===1:imported?.saved===1;
  const resultingDecision=cmd.kind==='DECISION'?cmd.decision:previousDecision;
  const resultingSaved=cmd.kind==='SAVED'?cmd.active:previousSaved;
  const version=cmd.expectedRevision+1;
  const eventId='app:'+cmd.operationId;
  const now=new Date().toISOString();
  const response={
    status:'saved' as const,replayed:false as const,productionAccess:false as const,
    eventId,operationId:cmd.operationId,jobId:cmd.jobId,
    jobRevision:version,decision:resultingDecision,saved:resultingSaved,
  };
  const json=JSON.stringify(response);
  // Assertion is inside the same transaction and guards the version actually committed.
  // A raced duplicate operation aborts on the unique idempotency constraint.
  const assert=personal.prepare(`INSERT INTO personal_app_assert(valid)
    SELECT CASE WHEN COALESCE((SELECT revision FROM personal_app_current
      WHERE owner_id=? AND job_id=?),0)=?
      AND EXISTS(SELECT 1 FROM personal_heads WHERE owner_id=?)
      AND NOT EXISTS(SELECT 1 FROM personal_app_operations WHERE owner_id=? AND operation_id=?)
      THEN 1 ELSE 0 END`)
    .bind(owner.ownerId,cmd.jobId,cmd.expectedRevision,owner.ownerId,owner.ownerId,cmd.operationId);
  const jobs=personal.prepare(`INSERT INTO personal_app_jobs
    (owner_id,job_id,captured_title,official_url,last_known_lifecycle,captured_commit,captured_path,captured_sha256)
    VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(owner_id,job_id) DO NOTHING`)
    .bind(owner.ownerId,cmd.jobId,job.title,job.canonicalUrl,job.lifecycle,
      job.originCommit,job.originPath,job.originSha256);
  const event=personal.prepare(`INSERT INTO personal_app_events
    (owner_id,event_id,job_id,operation_id,kind,decision,saved_active,previous_decision,
     previous_saved,reason_summary,expected_revision,revision,created_at,payload_sha256)
    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)`)
    .bind(owner.ownerId,eventId,cmd.jobId,cmd.operationId,cmd.kind,
      cmd.kind==='DECISION'?cmd.decision:null,cmd.kind==='SAVED'?Number(cmd.active):null,
      previousDecision,Number(previousSaved),cmd.kind==='DECISION'?cmd.reasonSummary:null,
      cmd.expectedRevision,version,now,digest);
  const next=cmd.kind==='DECISION'?
    personal.prepare(`INSERT INTO personal_app_current
      (owner_id,job_id,revision,decision_override,decision,saved_override,saved_active,updated_at)
      VALUES (?,?,?,1,?,0,0,?)
      ON CONFLICT(owner_id,job_id) DO UPDATE SET revision=excluded.revision,
      decision_override=1,decision=excluded.decision,updated_at=excluded.updated_at`)
      .bind(owner.ownerId,cmd.jobId,version,cmd.decision,now):
    personal.prepare(`INSERT INTO personal_app_current
      (owner_id,job_id,revision,decision_override,decision,saved_override,saved_active,updated_at)
      VALUES (?,?,?,0,NULL,1,?,?)
      ON CONFLICT(owner_id,job_id) DO UPDATE SET revision=excluded.revision,
      saved_override=1,saved_active=excluded.saved_active,updated_at=excluded.updated_at`)
      .bind(owner.ownerId,cmd.jobId,version,Number(cmd.active),now);
  const headBump=personal.prepare(`INSERT INTO personal_app_heads(owner_id,revision) VALUES (?,1)
    ON CONFLICT(owner_id) DO UPDATE SET revision=personal_app_heads.revision+1`)
    .bind(owner.ownerId);
  const durable=personal.prepare(`INSERT INTO personal_app_operations
    (owner_id,operation_id,payload_sha256,event_id,job_id,response_json)
    VALUES (?,?,?,?,?,?)`).bind(owner.ownerId,cmd.operationId,digest,eventId,cmd.jobId,json);
  try {await personal.batch([assert,jobs,event,next,headBump,durable]);}
  catch(e){
    // If two requests used the same key, only one transaction can win.
    const committed=await readOperation(personal,owner.ownerId,cmd.operationId);
    if(committed)return replay(committed,digest);
    const latest=await personal.prepare('SELECT revision FROM personal_app_current WHERE owner_id=? AND job_id=?')
      .bind(owner.ownerId,cmd.jobId).first<number>('revision');
    if((latest??0)!==cmd.expectedRevision)
      throw new ModelCPersonalWriteError('REVISION_CONFLICT',409);
    // Never leak raw SQL / schema errors to HTTP clients.
    throw new ModelCPersonalWriteError('WRITE_TRANSACTION_FAILED',503);
  }
  return response;
}
