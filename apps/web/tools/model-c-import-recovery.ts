// M47 offline-only readback of cross-D1 publication/reconciliation evidence.
// This is an observation, NOT an atomic cross-database transaction, a repair
// command, or a service/interactive HTTP authorization adapter.
import {canonical,sha256} from '../shared/canonical';

export class ModelCRecoveryInspectionError extends Error {
  constructor(readonly code:string){super(code);}
}
const fail=(code:string):never=>{throw new ModelCRecoveryInspectionError(code);};
type CatalogHead={syncRevision:number;runId:string;contentRevision:number;
  ledgerRevision:number;ledgerDigest:string;observedCommit:string;state:string};
type PersonalReceipt={catalog_sync_revision:number;catalog_content_revision:number;
  observed_commit:string;ledger_digest:string;head_digest:string};
type PersonalRef={job_id:string};
type Recon={job_id:string;state:string;receipt_id:string|null;personal_revision:number};
const readHead=async (db:D1Database)=>db.prepare(`SELECT h.sync_revision AS syncRevision,
  h.run_id AS runId,h.content_revision AS contentRevision,
  h.ledger_revision AS ledgerRevision,l.ledger_digest AS ledgerDigest,
  r.observed_commit AS observedCommit,r.state
  FROM catalog_head h JOIN catalog_runs r ON r.id=h.run_id
  JOIN catalog_ledger_checkpoints l ON l.revision=h.ledger_revision
  WHERE h.scope='catalog'`).first<CatalogHead>();

/** The trusted local caller supplies a server-validated owner binding.
 * No service-auth JWT, user ID header or owner override can reach this module.
 * It NEVER mutates either database. Re-read heads at end to reject races.
 */
export async function inspectPublishedModelCRecovery(catalog:D1Database,personal:D1Database,
  owner:{ownerId:string}){
  if(catalog===personal)return fail('CROSS_DATABASE_SCOPE_COLLISION');
  if(!owner||typeof owner.ownerId!=='string'||owner.ownerId.length<1||
      owner.ownerId.length>200)return fail('TRUSTED_OWNER_REQUIRED');
  const [cv,pv]=await Promise.all([
    catalog.prepare("SELECT version FROM model_c_schema WHERE scope='CATALOG'").first<number>('version'),
    personal.prepare("SELECT version FROM model_c_schema WHERE scope='PERSONAL'").first<number>('version'),
  ]);
  if(cv!==5||pv!==3)return fail('MODEL_C_SCHEMA_MISMATCH');
  const head=await readHead(catalog);
  if(!head)return {status:'NO_PUBLISHED_CATALOG' as const,
    crossDatabaseAtomicity:false as const,remoteExecutionAuthorized:false as const};
  if(head.state!=='PUBLISHED')return fail('CATALOG_HEAD_UNTRUSTED');
  const receiptId='receipt:'+head.runId;
  const headDigest=await sha256(canonical({syncRevision:head.syncRevision,
    run:head.runId,contentRevision:head.contentRevision,
    ledgerRevision:head.ledgerRevision,ledgerDigest:head.ledgerDigest}));
  const [ownerRow,personalHead,appRevision,receipt,refs,recons]=await Promise.all([
    personal.prepare('SELECT owner_id FROM personal_owners WHERE owner_id=?')
      .bind(owner.ownerId).first<{owner_id:string}>(),
    personal.prepare('SELECT revision,context_digest FROM personal_heads WHERE owner_id=?')
      .bind(owner.ownerId).first<{revision:number;context_digest:string}>(),
    personal.prepare('SELECT revision FROM personal_app_heads WHERE owner_id=?')
      .bind(owner.ownerId).first<number>('revision'),
    personal.prepare('SELECT * FROM personal_catalog_receipts WHERE id=?')
      .bind(receiptId).first<PersonalReceipt>(),
    personal.prepare('SELECT job_id FROM personal_job_refs WHERE owner_id=?')
      .bind(owner.ownerId).all<PersonalRef>(),
    personal.prepare('SELECT job_id,state,receipt_id,personal_revision FROM personal_reconciliation WHERE owner_id=?')
      .bind(owner.ownerId).all<Recon>(),
  ]);
  if(!ownerRow)return fail('OWNER_NOT_FOUND');
  if(!personalHead)return fail('PERSONAL_HEAD_NOT_FOUND');
  const match=!!receipt && receipt.catalog_sync_revision===head.syncRevision &&
    receipt.catalog_content_revision===head.contentRevision &&
    receipt.observed_commit===head.observedCommit&&
    receipt.ledger_digest===head.ledgerDigest&&receipt.head_digest===headDigest;
  const byJob=new Map(recons.results.map(r=>[r.job_id,r]));
  const conflict=refs.results.some(r=>byJob.get(r.job_id)?.state==='CONFLICT');
  const unverified=refs.results.some(r=>{
    const entry=byJob.get(r.job_id);
    return !entry||entry.state!=='VERIFIED'||entry.receipt_id!==receiptId||
      entry.personal_revision!==personalHead.revision;
  });
  const [headAfter,personalAfter,appAfter]=await Promise.all([
    readHead(catalog),
    personal.prepare('SELECT revision,context_digest FROM personal_heads WHERE owner_id=?')
      .bind(owner.ownerId).first<{revision:number;context_digest:string}>(),
    personal.prepare('SELECT revision FROM personal_app_heads WHERE owner_id=?')
      .bind(owner.ownerId).first<number>('revision'),
  ]);
  if(canonical(head)!==canonical(headAfter)||
     canonical(personalHead)!==canonical(personalAfter)||
     (appRevision??0)!==(appAfter??0))return fail('CHECKPOINT_CHANGED_DURING_READ');

  const status=conflict?'PERSONAL_CONFLICT' as const:
    !match||unverified?'CATALOG_PUBLISHED_PERSONAL_PENDING' as const:
    (appRevision??0)>0?'APP_CONTEXT_REQUIRES_REVALIDATION' as const:
    'PUBLISHED_RECEIPTS_RECONCILED' as const;
  return {status,catalogRunId:head.runId,catalogRevision:head.syncRevision,
    personalRevision:personalHead.revision,appRevision:appRevision??0,
    references:refs.results.length,receiptMatchesPublishedHead:match,
    pendingReferences:refs.results.filter(r=>{
      const item=byJob.get(r.job_id);
      return !item||item.state!=='VERIFIED'||item.receipt_id!==receiptId||
        item.personal_revision!==personalHead.revision;
    }).length,
    // Readback is not a cryptographic proof of the complete Git projection,
    // and does not imply Cloudflare remote consistency or recovery authorization.
    independentlyVerifiedGit:false as const,
    crossDatabaseAtomicity:false as const,
    remoteExecutionAuthorized:false as const};
}
