// PR #41: synthetic-only PERSONAL mutations; no production auth or remote write path.
// D1.batch is the atomic boundary. The imported GitHub projection is NEVER updated.
import {z} from 'zod';
import {canonical,sha256} from '../../shared/canonical';
import {getModelCCatalogSnapshot} from './model-c-catalog';
import type {TrustedOwner} from './model-c-personal';

const jobId=z.string().regex(/^job:[a-f0-9]{64}$/);
const key=z.string().uuid();
const common={
  jobId,expectedRevision:z.number().int().min(0).max(2147483646),
  idempotencyKey:key,
};
export const decisionCommandSchema=z.strictObject({
  ...common,decision:z.enum(['TO_REVIEW','INTERESTED','APPLIED','NOT_INTERESTED']).nullable(),
  reason:z.string().trim().max(360).optional(),
  catalogRevision:z.number().int().positive().optional(),
});
export const savedCommandSchema=z.strictObject({
  ...common,action:z.enum(['activate','deactivate']),
  catalogRevision:z.number().int().positive().optional(),
});
export type PersonalCommand =
  | {kind:'DECISION';payload:z.infer<typeof decisionCommandSchema>}
  | {kind:'SAVED';payload:z.infer<typeof savedCommandSchema>};

export class ModelCWriteError extends Error {
  constructor(readonly code:string,readonly status:number){super(code);}
}
type LocalRow={
  revision:number;decisionTouched:number;decision:string|null;decisionAt:string|null;
  decisionReason:string|null;savedTouched:number;savedActive:number;
};
type ImportedRow={decision:string|null;savedActive:number};
type Operation={payloadHash:string;resultJson:string};
export type CommandResult={
  status:'saved';replayed:boolean;eventId:string;appRevision:number;
  decision:string|null;saved:boolean;decisionSource:'APP'|'IMPORT'|null;
  savedSource:'APP'|'IMPORT'|null;jobId:string;
};

async function recorded(db:D1Database,owner:string,id:string){
  return db.prepare('SELECT payload_hash AS payloadHash,result_json AS resultJson FROM personal_app_operations WHERE owner_id=? AND operation_id=?')
    .bind(owner,id).first<Operation>();
}
function replay(op:Operation,hash:string):CommandResult {
  if(op.payloadHash!==hash)throw new ModelCWriteError('IDEMPOTENCY_KEY_CONFLICT',409);
  return {...JSON.parse(op.resultJson) as CommandResult,replayed:true};
}
/** Caller provides an authenticated/synthetic server-side owner; never a browser owner ID. */
export async function writeModelCPersonal(
  catalog:D1Database,personal:D1Database,trusted:TrustedOwner,command:PersonalCommand,
):Promise<CommandResult>{
  const owner=trusted.ownerId;
  if(!/^synthetic-[a-z][a-z0-9-]{0,63}$/.test(owner))
    throw new ModelCWriteError('SYNTHETIC_OWNER_UNAVAILABLE',403);
  if(catalog===personal)throw new ModelCWriteError('DATABASE_SCOPE_COLLISION',503);
  const data=command.kind==='DECISION'
    ? decisionCommandSchema.parse(command.payload):savedCommandSchema.parse(command.payload);
  const payloadHash=await sha256(canonical({kind:command.kind,payload:data}));
  const prior=await recorded(personal,owner,data.idempotencyKey);
  if(prior)return replay(prior,payloadHash);

  const version=await personal.prepare("SELECT version FROM model_c_schema WHERE scope='PERSONAL'").first<number>('version');
  if(version!==3)throw new ModelCWriteError('PERSONAL_SCHEMA_MISMATCH',503);
  const importedHead=await personal.prepare('SELECT revision FROM personal_heads WHERE owner_id=?')
    .bind(owner).first<{revision:number}>();
  if(!importedHead)throw new ModelCWriteError('PERSONAL_CONTEXT_UNAVAILABLE',404);
  const snapshot=await getModelCCatalogSnapshot(catalog);
  if(!snapshot.snapshot)throw new ModelCWriteError('NO_PUBLISHED_CATALOG',503);
  if(data.catalogRevision!==undefined && snapshot.snapshot.syncRevision!==data.catalogRevision)
    throw new ModelCWriteError('CATALOG_CHANGED',409);
  const known=await catalog.prepare('SELECT id FROM catalog_vacancy_identity WHERE id=?')
    .bind(data.jobId).first('id');
  if(!known)throw new ModelCWriteError('JOB_NOT_FOUND',404);

  const current=await personal.prepare(`SELECT revision,decision_touched AS decisionTouched,
    decision,decision_at AS decisionAt,decision_reason AS decisionReason,
    saved_touched AS savedTouched,saved_active AS savedActive
    FROM personal_app_job_state WHERE owner_id=? AND job_id=?`)
    .bind(owner,data.jobId).first<LocalRow>();
  if((current?.revision??0)!==data.expectedRevision)
    throw new ModelCWriteError('REVISION_CONFLICT',409);

  const imported=await personal.prepare(`SELECT
    d.decision AS decision,
    coalesce((SELECT active FROM personal_reference_state
      WHERE owner_id=? AND job_id=? AND kind='SAVED'),0) AS savedActive
    FROM personal_owners o
    LEFT JOIN personal_decision_current dc ON dc.owner_id=o.owner_id AND dc.job_id=?
    LEFT JOIN personal_decision_events d ON d.owner_id=dc.owner_id AND d.id=dc.event_id
    WHERE o.owner_id=?`)
    .bind(owner,data.jobId,data.jobId,owner).first<ImportedRow>();
  const oldDecision=current?.decisionTouched?current.decision:imported?.decision??null;
  const oldSaved=current?.savedTouched?current.savedActive===1:imported?.savedActive===1;
  const decision=command.kind==='DECISION'?command.payload.decision:oldDecision;
  const saved=command.kind==='SAVED'?command.payload.action==='activate':oldSaved;
  const resultRevision=data.expectedRevision+1;
  const eventId='app:'+crypto.randomUUID();
  const result:CommandResult={
    status:'saved',replayed:false,eventId,appRevision:resultRevision,jobId:data.jobId,
    decision,saved,decisionSource:command.kind==='DECISION'?'APP':
      current?.decisionTouched?'APP':imported?.decision?'IMPORT':null,
    savedSource:command.kind==='SAVED'?'APP':
      current?.savedTouched?'APP':imported?.savedActive?'IMPORT':null,
  };
  const isDecision=command.kind==='DECISION';
  const nextDecision=isDecision?command.payload.decision:null;
  const nextReason=isDecision?(command.payload.reason??null):null;
  const nextSaved=!isDecision&&command.payload.action==='activate'?1:0;
  const now="strftime('%Y-%m-%dT%H:%M:%fZ','now')";
  // A conditional upsert alone is NOT a CAS: a WHERE mismatch affects zero rows.
  // The guard immediately afterwards forces a transactional abort on mismatch.
  const batch=[
    personal.prepare(`INSERT INTO personal_app_job_state
      (owner_id,job_id,revision,decision_touched,decision,decision_at,decision_reason,saved_touched,saved_active,updated_at)
      VALUES (?,?,1,?,?,CASE WHEN ?=1 THEN ${now} ELSE NULL END,?, ?,?,${now})
      ON CONFLICT(owner_id,job_id) DO UPDATE SET
        revision=personal_app_job_state.revision+1,
        decision_touched=CASE WHEN ?=1 THEN 1 ELSE personal_app_job_state.decision_touched END,
        decision=CASE WHEN ?=1 THEN excluded.decision ELSE personal_app_job_state.decision END,
        decision_at=CASE WHEN ?=1 THEN excluded.decision_at ELSE personal_app_job_state.decision_at END,
        decision_reason=CASE WHEN ?=1 THEN excluded.decision_reason ELSE personal_app_job_state.decision_reason END,
        saved_touched=CASE WHEN ?=0 THEN 1 ELSE personal_app_job_state.saved_touched END,
        saved_active=CASE WHEN ?=0 THEN excluded.saved_active ELSE personal_app_job_state.saved_active END,
        updated_at=${now}
      WHERE personal_app_job_state.revision=?`)
      .bind(owner,data.jobId,isDecision?1:0,nextDecision,isDecision?1:0,nextReason,
        isDecision?0:1,nextSaved,
        isDecision?1:0,isDecision?1:0,isDecision?1:0,isDecision?1:0,
        isDecision?1:0,isDecision?1:0,data.expectedRevision),
    personal.prepare(`INSERT INTO personal_app_cas_guard(valid)
      SELECT CASE WHEN EXISTS(SELECT 1 FROM personal_app_job_state
        WHERE owner_id=? AND job_id=? AND revision=?) THEN 1 ELSE 0 END`)
      .bind(owner,data.jobId,resultRevision),
    personal.prepare(`INSERT INTO personal_app_events
      (owner_id,id,job_id,operation_id,command,action,previous_value,next_value,reason,
       expected_revision,result_revision)
      VALUES (?,?,?,?,?,?,?,?,?,?,?)`)
      .bind(owner,eventId,data.jobId,data.idempotencyKey,command.kind,
        isDecision?(nextDecision===null?'REVOKE':'SET'):command.payload.action.toUpperCase(),
        isDecision?oldDecision:oldSaved?'true':'false',
        isDecision?nextDecision:saved?'true':'false',nextReason,
        data.expectedRevision,resultRevision),
    personal.prepare(`INSERT INTO personal_app_operations
      (owner_id,operation_id,job_id,command,payload_hash,event_id,result_json)
      VALUES (?,?,?,?,?,?,?)`)
      .bind(owner,data.idempotencyKey,data.jobId,command.kind,payloadHash,eventId,JSON.stringify(result)),
    personal.prepare(`INSERT INTO personal_app_owner_epochs(owner_id,epoch) VALUES (?,1)
      ON CONFLICT(owner_id) DO UPDATE SET epoch=epoch+1`).bind(owner),
  ];
  try {
    await personal.batch(batch);
  }catch {
    // Another request may have committed the same key while we were attempting the CAS.
    const winner=await recorded(personal,owner,data.idempotencyKey);
    if(winner)return replay(winner,payloadHash);
    const latest=await personal.prepare('SELECT revision FROM personal_app_job_state WHERE owner_id=? AND job_id=?')
      .bind(owner,data.jobId).first<number>('revision');
    if((latest??0)!==data.expectedRevision)
      throw new ModelCWriteError('REVISION_CONFLICT',409);
    throw new ModelCWriteError('DATABASE_WRITE_FAILED',503);
  }
  return result;
}
