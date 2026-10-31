// Owner-scoped Model C PERSONAL reader, accessible only through the synthetic local HTTP adapter.
// IMPORTANT: a future production adapter must authenticate and supply ownerId.
// This module enforces owner-scoped SQL, not authentication or authorization.
import { z } from 'zod';
import { canonical, sha256 } from '../../shared/canonical';

export class ModelCPersonalReadError extends Error {
  constructor(public readonly code: string, public readonly status: number) { super(code); }
}
export type TrustedOwner = { ownerId: string };
const ownerSchema = z.string().min(1).max(200);
const jobIdSchema = z.string().regex(/^job:[a-f0-9]{64}$/);
const pagingSchema = z.strictObject({
  limit: z.coerce.number().int().min(1).max(50).default(25),
  cursor: z.string().max(5000).optional(),
  q: z.string().trim().max(120).default(''),
  view: z.enum(['all','to_apply','applied','dismissed']).default('all'),
  decision: z.enum(['TO_REVIEW','INTERESTED','APPLIED','NOT_INTERESTED']).optional(),
  reference: z.enum(['SAVED','APPLICATION','DISMISSED']).optional(),
});
const cursorSchema = z.strictObject({
  ownerDigest: z.string().regex(/^[a-f0-9]{64}$/),
  personalRevision: z.number().int().positive(),
  catalogRevision: z.number().int().positive(),
  catalogRun: z.string().min(1),
  personalDigest: z.string().regex(/^[a-f0-9]{64}$/),
  appRevision: z.number().int().nonnegative().optional(),
  lastId: jobIdSchema,
  filters: z.string().optional(),
});
type Cursor = z.infer<typeof cursorSchema>;
const encodeCursor = (value: Cursor) =>
  btoa(String.fromCharCode(...new TextEncoder().encode(JSON.stringify(value))))
    .replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
const decodeCursor = (encoded: string): Cursor => {
  try {
    return cursorSchema.parse(JSON.parse(new TextDecoder().decode(
      Uint8Array.from(atob(encoded.replace(/-/g, '+').replace(/_/g, '/')),
        character => character.charCodeAt(0)))));
  } catch { throw new ModelCPersonalReadError('INVALID_CURSOR', 400); }
};

type CatalogHead = {
  syncRevision: number; contentRevision: number; ledgerRevision: number;
  run: string; observedCommit: string; ledgerDigest: string; state: string;
};
type PersonalHead = { revision: number; contextDigest: string; appRevision: number };
type Context = { catalog: CatalogHead; personal: PersonalHead; ownerId: string; ownerDigest: string; headDigest: string };
async function catalogHead(db: D1Database) {
  const version = await db.prepare("SELECT version FROM model_c_schema WHERE scope='CATALOG'").first<number>('version');
  if (version !== 5) throw new ModelCPersonalReadError('CATALOG_SCHEMA_MISMATCH', 503);
  const head = await db.prepare(`SELECT h.sync_revision AS syncRevision,h.content_revision AS contentRevision,
    h.ledger_revision AS ledgerRevision,h.run_id AS run,r.observed_commit AS observedCommit,
    l.ledger_digest AS ledgerDigest,r.state FROM catalog_head h
    JOIN catalog_runs r ON r.id=h.run_id
    JOIN catalog_ledger_checkpoints l ON l.revision=h.ledger_revision WHERE h.scope='catalog'`)
    .first<CatalogHead>();
  if (!head || head.state !== 'PUBLISHED') throw new ModelCPersonalReadError('NO_PUBLISHED_CATALOG', 503);
  return head;
}
async function personalHead(db: D1Database, ownerId: string) {
  const version = await db.prepare("SELECT version FROM model_c_schema WHERE scope='PERSONAL'").first<number>('version');
  if (version !== 3) throw new ModelCPersonalReadError('PERSONAL_SCHEMA_MISMATCH', 503);
  const head = await db.prepare(`SELECT revision,context_digest AS contextDigest,
   COALESCE((SELECT revision FROM personal_app_heads a WHERE a.owner_id=personal_heads.owner_id),0) AS appRevision
   FROM personal_heads WHERE owner_id=?`)
    .bind(ownerId).first<PersonalHead>();
  if (!head) throw new ModelCPersonalReadError('PERSONAL_CONTEXT_UNAVAILABLE', 404);
  return head;
}
async function context(catalog: D1Database, personal: D1Database, owner: TrustedOwner): Promise<Context> {
  const ownerId = ownerSchema.parse(owner?.ownerId);
  if (catalog === personal) throw new ModelCPersonalReadError('DATABASE_SCOPE_COLLISION', 503);
  const p = await personalHead(personal, ownerId);
  const c = await catalogHead(catalog);
  const headDigest = await sha256(canonical({
    syncRevision:c.syncRevision,run:c.run,contentRevision:c.contentRevision,
    ledgerRevision:c.ledgerRevision,ledgerDigest:c.ledgerDigest,
  }));
  return {catalog:c,personal:p,ownerId,ownerDigest:await sha256(ownerId),headDigest};
}
async function assertUnchanged(catalog: D1Database, personal: D1Database, c: Context) {
  const [p,h] = await Promise.all([personalHead(personal,c.ownerId),catalogHead(catalog)]);
  if (p.revision !== c.personal.revision || p.contextDigest !== c.personal.contextDigest ||
    p.appRevision !== c.personal.appRevision ||
    h.syncRevision !== c.catalog.syncRevision || h.run !== c.catalog.run ||
    h.contentRevision !== c.catalog.contentRevision || h.ledgerRevision !== c.catalog.ledgerRevision ||
    h.observedCommit !== c.catalog.observedCommit || h.ledgerDigest !== c.catalog.ledgerDigest) throw new ModelCPersonalReadError('CONTEXT_CHANGED', 409);
}
type RefRow = {
  jobId:string; capturedTitle:string|null; officialUrl:string|null;
  lastKnownLifecycle:string|null; capturedCommit:string; capturedPath:string;
  capturedSha256:string; revision:number;
  decision:string|null; decidedAt:string|null; rejectionReason:string|null; reasonSummary:string|null;
  appRevision:number|null; decisionSource:'APP'|'GITHUB'|null;
  assessmentMethod:string|null; assessmentFingerprint:string|null; fitScore:number|null;
  reportable:number|null; assessmentSummary:string|null;
  reconciliationState:'PENDING'|'VERIFIED'|'CONFLICT'|null;
  reconciliationRevision:number|null; receiptId:string|null;
  receiptSyncRevision:number|null; receiptContentRevision:number|null;
  receiptObservedCommit:string|null; receiptLedgerDigest:string|null; receiptHeadDigest:string|null;
};
const refSource = `(SELECT owner_id,job_id,captured_title,official_url,last_known_lifecycle,
 captured_commit,captured_path,captured_sha256,revision FROM personal_job_refs
 UNION ALL SELECT app.owner_id,app.job_id,app.captured_title,app.official_url,
 app.last_known_lifecycle,app.captured_commit,app.captured_path,app.captured_sha256,1 AS revision
 FROM personal_app_jobs app WHERE NOT EXISTS
 (SELECT 1 FROM personal_job_refs imported WHERE imported.owner_id=app.owner_id
 AND imported.job_id=app.job_id))`;
const selectRef = `SELECT ref.job_id AS jobId,ref.captured_title AS capturedTitle,
  ref.official_url AS officialUrl,ref.last_known_lifecycle AS lastKnownLifecycle,
  ref.captured_commit AS capturedCommit,ref.captured_path AS capturedPath,
  ref.captured_sha256 AS capturedSha256,ref.revision,
  CASE WHEN app.decision_override=1 THEN app.decision ELSE d.decision END AS decision,
  CASE WHEN app.decision_override=1 THEN app.updated_at ELSE d.decided_at END AS decidedAt,
  CASE WHEN app.decision_override=1 THEN NULL ELSE d.rejection_reason END AS rejectionReason,
  CASE WHEN app.decision_override=1 THEN NULL ELSE d.reason_summary END AS reasonSummary,
  app.revision AS appRevision,
  CASE WHEN app.decision_override=1 THEN 'APP' WHEN d.decision IS NOT NULL THEN 'GITHUB' ELSE NULL END AS decisionSource,
  a.method AS assessmentMethod,a.fingerprint AS assessmentFingerprint,
  a.fit_score AS fitScore,a.reportable,a.summary AS assessmentSummary,
  rec.state AS reconciliationState,rec.personal_revision AS reconciliationRevision,
  rec.receipt_id AS receiptId,receipt.catalog_sync_revision AS receiptSyncRevision,
  receipt.catalog_content_revision AS receiptContentRevision,
  receipt.observed_commit AS receiptObservedCommit,receipt.ledger_digest AS receiptLedgerDigest,
  receipt.head_digest AS receiptHeadDigest
  FROM ${refSource} ref
  LEFT JOIN personal_app_current app ON app.owner_id=ref.owner_id AND app.job_id=ref.job_id
  LEFT JOIN personal_decision_current dc ON dc.owner_id=ref.owner_id AND dc.job_id=ref.job_id
  LEFT JOIN personal_decision_events d ON d.owner_id=dc.owner_id AND d.id=dc.event_id AND d.job_id=dc.job_id
  LEFT JOIN personal_assessment_current ac ON ac.owner_id=ref.owner_id AND ac.job_id=ref.job_id
  LEFT JOIN personal_assessment_events a ON a.owner_id=ac.owner_id AND a.id=ac.event_id AND a.job_id=ac.job_id
  LEFT JOIN personal_reconciliation rec ON rec.owner_id=ref.owner_id AND rec.job_id=ref.job_id
  LEFT JOIN personal_catalog_receipts receipt ON receipt.id=rec.receipt_id`;
type CatalogInfo = { company:string; companyId:string; title:string|null; location:string|null;
  lifecycle:string; canonicalUrl:string|null; applyUrl:string|null; firstSeenAt:string|null; lastSeenAt:string|null };
type Flags = { knownIdentity:boolean; currentlyVisible:boolean; currentFingerprint:string|null;
  activeReferences:string[]; catalog:CatalogInfo|null };
function reconciliation(row: RefRow, c: Context, known: boolean) {
  if (!known) return 'UNRESOLVED_REFERENCE' as const;
  if (row.reconciliationState === 'CONFLICT') return 'CONFLICT' as const;
  if ((row.appRevision??0)>0) return 'PENDING' as const;
  if (row.reconciliationState !== 'VERIFIED') return 'PENDING' as const;
  if (row.reconciliationRevision !== c.personal.revision ||
    row.receiptSyncRevision !== c.catalog.syncRevision ||
    row.receiptContentRevision !== c.catalog.contentRevision ||
    row.receiptObservedCommit !== c.catalog.observedCommit ||
    row.receiptLedgerDigest !== c.catalog.ledgerDigest ||
    row.receiptHeadDigest !== c.headDigest) return 'STALE' as const;
  return 'VERIFIED' as const;
}
async function flags(catalog:D1Database,personal:D1Database,ownerId:string,ids:string[]) {
  const result = new Map<string,Flags>();
  if (!ids.length) return result;
  const placeholders=ids.map(()=>'?').join(',');
  const [known,visible,refs] = await Promise.all([
    catalog.prepare(`SELECT id FROM catalog_vacancy_identity WHERE id IN (${placeholders})`).bind(...ids).all<{id:string}>(),
    catalog.prepare(`SELECT v.job_id AS id,v.fingerprint,c.display_name AS company,v.company_id AS companyId,
      v.title,v.location,v.lifecycle,v.canonical_url AS canonicalUrl,v.apply_url AS applyUrl,
      v.first_seen_at AS firstSeenAt,v.last_seen_at AS lastSeenAt
      FROM catalog_visible_vacancies v JOIN catalog_visible_companies c ON c.company_id=v.company_id
      WHERE v.job_id IN (${placeholders})`).bind(...ids).all<{id:string;fingerprint:string|null}&CatalogInfo>(),
    personal.prepare(`SELECT job_id AS jobId,kind FROM personal_reference_state
      WHERE owner_id=? AND active=1 AND job_id IN (${placeholders}) ORDER BY kind`)
      .bind(ownerId,...ids).all<{jobId:string;kind:string}>(),
  ]);
  const knownSet = new Set(known.results.map(x=>x.id));
  const visibleMap = new Map(visible.results.map(x=>[x.id,x]));
  for (const id of ids) {
    const row=visibleMap.get(id);
    result.set(id,{knownIdentity:knownSet.has(id),currentlyVisible:!!row,
      currentFingerprint:row?.fingerprint??null,activeReferences:[],
      catalog:row ? {company:row.company,companyId:row.companyId,title:row.title,
        location:row.location,lifecycle:row.lifecycle,canonicalUrl:row.canonicalUrl,
        applyUrl:row.applyUrl,firstSeenAt:row.firstSeenAt,lastSeenAt:row.lastSeenAt}:null});
  }
  for (const r of refs.results) result.get(r.jobId)?.activeReferences.push(r.kind);
  const overrides=await personal.prepare(`SELECT job_id AS jobId,saved_active AS active
    FROM personal_app_current WHERE owner_id=? AND saved_override=1
    AND job_id IN (${placeholders})`).bind(ownerId,...ids).all<{jobId:string;active:number}>();
  for(const x of overrides.results) {
    const state=result.get(x.jobId);
    if(!state)continue;
    state.activeReferences=state.activeReferences.filter(v=>v!=='SAVED');
    if(x.active===1)state.activeReferences.push('SAVED');
    state.activeReferences.sort();
  }
  return result;
}
function record(row:RefRow,c:Context,f:Flags) {
  return {
    jobId:row.jobId,capturedTitle:row.capturedTitle,officialUrl:row.officialUrl,
    lastKnownLifecycle:row.lastKnownLifecycle,capturedCommit:row.capturedCommit,
    capturedPath:row.capturedPath,capturedSha256:row.capturedSha256,
    decision:row.decision,decidedAt:row.decidedAt,decisionSource:row.decisionSource,
    jobRevision:row.appRevision??0,rejectionReason:row.rejectionReason,
    reasonSummary:row.reasonSummary,
    assessment:row.assessmentMethod ? {method:row.assessmentMethod,fingerprint:row.assessmentFingerprint,
      fitScore:row.fitScore,reportable:row.reportable===null?null:row.reportable===1,
      summary:row.assessmentSummary,
      freshness: !f.currentlyVisible || !f.currentFingerprint || !row.assessmentFingerprint
        ? 'UNVERIFIED' as const
        : row.assessmentFingerprint===f.currentFingerprint ? 'CURRENT' as const : 'STALE' as const} : null,
    activeReferences:f.activeReferences,catalog:f.catalog,knownIdentity:f.knownIdentity,
    currentlyVisible:f.currentlyVisible,reconciliation:reconciliation(row,c,f.knownIdentity),
  };
}
function publicContext(c:Context) {
  return {personalRevision:c.personal.revision,appRevision:c.personal.appRevision,
    catalogRevision:c.catalog.syncRevision,productionAccess:false as const};
}
export async function getModelCPersonalSummary(catalog:D1Database,personal:D1Database,owner:TrustedOwner) {
  const c=await context(catalog,personal,owner);
  const counts=await personal.prepare(`SELECT
    count(*) AS referencesCount,
    count(CASE WHEN app.decision_override=1 THEN app.decision ELSE dc.event_id END) AS decisionsCount,
    count(ac.event_id) AS assessmentsCount
    FROM ${refSource} ref
    LEFT JOIN personal_app_current app ON app.owner_id=ref.owner_id AND app.job_id=ref.job_id
    LEFT JOIN personal_decision_current dc ON dc.owner_id=ref.owner_id AND dc.job_id=ref.job_id
    LEFT JOIN personal_assessment_current ac ON ac.owner_id=ref.owner_id AND ac.job_id=ref.job_id
    WHERE ref.owner_id=?`).bind(c.ownerId)
    .first<{referencesCount:number;decisionsCount:number;assessmentsCount:number}>();
  await assertUnchanged(catalog,personal,c);
  return {...publicContext(c),counts:counts??{referencesCount:0,decisionsCount:0,assessmentsCount:0}};
}
export async function listModelCPersonalJobs(catalog:D1Database,personal:D1Database,owner:TrustedOwner,input:unknown={}) {
  const query=pagingSchema.parse(input);
  const c=await context(catalog,personal,owner);
  const cursor = query.cursor ? decodeCursor(query.cursor) : null;
  if(cursor && cursor.ownerDigest !== c.ownerDigest)
    throw new ModelCPersonalReadError('CURSOR_OWNER_MISMATCH',403);
  if(cursor && ((cursor.appRevision??0)!==c.personal.appRevision ||
    cursor.personalRevision !== c.personal.revision || cursor.personalDigest !== c.personal.contextDigest ||
    cursor.catalogRevision !== c.catalog.syncRevision || cursor.catalogRun !== c.catalog.run))
    throw new ModelCPersonalReadError('CONTEXT_CHANGED',409);
  const signature=canonical({q:query.q,view:query.view,decision:query.decision??null,
    reference:query.reference??null});
  if (cursor && cursor.filters !== undefined && cursor.filters !== signature)
    throw new ModelCPersonalReadError('CURSOR_FILTER_MISMATCH',400);
  if (cursor && cursor.filters === undefined &&
    (query.q || query.view!=='all' || query.decision || query.reference))
    throw new ModelCPersonalReadError('CURSOR_FILTER_MISMATCH',400);
  const clauses=['ref.owner_id=?'];
  const args:string[]=[c.ownerId];
  if(query.q) {
    clauses.push("instr(lower(coalesce(ref.captured_title,'')),lower(?))>0");
    args.push(query.q);
  }
  const effectiveDecision="(CASE WHEN app.decision_override=1 THEN app.decision ELSE d.decision END)";
  const importedRef=(kind:string)=>`EXISTS (SELECT 1 FROM personal_reference_state st
    WHERE st.owner_id=ref.owner_id AND st.job_id=ref.job_id
    AND st.kind='${kind}' AND st.active=1)`;
  const savedEffective=`((app.saved_override=1 AND app.saved_active=1)
    OR (COALESCE(app.saved_override,0)=0 AND ${importedRef('SAVED')}))`;
  if(query.decision) { clauses.push(effectiveDecision+'=?');args.push(query.decision); }
  if(query.reference){
    if(query.reference==='SAVED')clauses.push(savedEffective);
    else clauses.push(importedRef(query.reference));
  }
  if(query.view==='to_apply') clauses.push(`(${effectiveDecision} IN ('TO_REVIEW','INTERESTED')
    OR ${savedEffective})
    AND (${effectiveDecision} IS NULL OR ${effectiveDecision} NOT IN ('APPLIED','NOT_INTERESTED'))`);
  if(query.view==='applied') clauses.push(`(${effectiveDecision}='APPLIED'
    OR ${importedRef('APPLICATION')})`);
  if(query.view==='dismissed') clauses.push(`(${effectiveDecision}='NOT_INTERESTED'
    OR ${importedRef('DISMISSED')})`);
  const where=clauses.join(' AND ');
  const total=await personal.prepare(`SELECT count(*) AS n FROM (${selectRef} WHERE ${where})`)
    .bind(...args).first<number>('n');
  const rows = await personal.prepare(`${selectRef} WHERE ${where}
    ${cursor?' AND ref.job_id>?':''} ORDER BY ref.job_id LIMIT ?`)
    .bind(...args,...(cursor?[cursor.lastId]:[]),query.limit+1).all<RefRow>();
  const visible=rows.results.slice(0,query.limit);
  const enriched=await flags(catalog,personal,c.ownerId,visible.map(r=>r.jobId));
  await assertUnchanged(catalog,personal,c);
  const last=visible.at(-1);
  const items=visible.map(r=>{
    const state=enriched.get(r.jobId);
    if (!state) throw new ModelCPersonalReadError('REFERENCE_STATE_UNAVAILABLE',503);
    return record(r,c,state);
  });
  return {...publicContext(c),total:total??0,
    items,
    nextCursor:rows.results.length>query.limit&&last?encodeCursor({
      ownerDigest:c.ownerDigest,personalRevision:c.personal.revision,personalDigest:c.personal.contextDigest,
      appRevision:c.personal.appRevision,
      catalogRevision:c.catalog.syncRevision,catalogRun:c.catalog.run,lastId:last.jobId,filters:signature}):null,
  };
}
export async function getModelCPersonalJob(catalog:D1Database,personal:D1Database,owner:TrustedOwner,jobId:string) {
  const id=jobIdSchema.parse(jobId);
  const c=await context(catalog,personal,owner);
  const row=await personal.prepare(`${selectRef} WHERE ref.owner_id=? AND ref.job_id=?`)
    .bind(c.ownerId,id).first<RefRow>();
  if(!row) {
    await assertUnchanged(catalog,personal,c);
    throw new ModelCPersonalReadError('PERSONAL_JOB_NOT_FOUND',404);
  }
  const enriched=await flags(catalog,personal,c.ownerId,[id]);
  const events=await personal.prepare(`SELECT * FROM (
    SELECT id,decision,rejection_reason AS rejectionReason,reason_summary AS reasonSummary,
      fingerprint,decided_at AS decidedAt,result_sha256 AS resultSha256,
      source_commit AS sourceCommit,source_path AS sourcePath,
      source_sha256 AS sourceSha256,'GITHUB' AS origin
    FROM personal_decision_events WHERE owner_id=? AND job_id=?
    UNION ALL
    SELECT event_id AS id,decision,NULL AS rejectionReason,reason_summary AS reasonSummary,
      NULL AS fingerprint,created_at AS decidedAt,payload_sha256 AS resultSha256,
      NULL AS sourceCommit,NULL AS sourcePath,NULL AS sourceSha256,'APP' AS origin
    FROM personal_app_events WHERE owner_id=? AND job_id=? AND kind='DECISION'
  ) ORDER BY decidedAt DESC,id DESC LIMIT 51`).bind(c.ownerId,id,c.ownerId,id).all();
  const appHistory=await personal.prepare(`SELECT event_id AS id,operation_id AS operationId,
    kind,decision,saved_active AS savedActive,previous_decision AS previousDecision,
    previous_saved AS previousSaved,expected_revision AS expectedRevision,revision,
    created_at AS createdAt,reason_summary AS reasonSummary
    FROM personal_app_events WHERE owner_id=? AND job_id=?
    ORDER BY revision DESC LIMIT 51`).bind(c.ownerId,id).all<Record<string,unknown>>();
  const assessments=await personal.prepare(`SELECT id,method,fingerprint,decision,fit_score AS fitScore,
    reportable,summary,evidence_state AS evidenceState,analyzed_at AS analyzedAt,
    result_sha256 AS resultSha256,source_commit AS sourceCommit,source_path AS sourcePath,source_sha256 AS sourceSha256
    FROM personal_assessment_events WHERE owner_id=? AND job_id=?
    ORDER BY analyzed_at DESC,id DESC LIMIT 51`).bind(c.ownerId,id).all<Record<string,unknown>>();
  await assertUnchanged(catalog,personal,c);
  const state=enriched.get(id);
  if (!state) throw new ModelCPersonalReadError('REFERENCE_STATE_UNAVAILABLE',503);
  return {...publicContext(c),job:record(row,c,state),
    decisionEvents:events.results.slice(0,50),
    decisionEventsTruncated:events.results.length>50,
    assessmentEvents:assessments.results.slice(0,50).map(r=>({
      ...r,reportable:r.reportable===null?null:r.reportable===1,
    })),
    assessmentEventsTruncated:assessments.results.length>50,
    appEvents:appHistory.results.slice(0,50).map(r=>({
      ...r,savedActive:r.savedActive===null?null:r.savedActive===1,
      previousSaved:r.previousSaved===null?null:r.previousSaved===1,
    })),
    appEventsTruncated:appHistory.results.length>50,
  };
}


/** PR #40: read-only owner-scoped batch for a *single bounded CATALOG page*.
 * This is never served on the CATALOG public namespace. No per-job queries. */
export async function getModelCPersonalOverlays(
  catalog:D1Database,personal:D1Database,owner:TrustedOwner,jobIds:readonly string[],
) {
  if (jobIds.length>100 || new Set(jobIds).size!==jobIds.length ||
      jobIds.some(id=>!jobIdSchema.safeParse(id).success))
    throw new ModelCPersonalReadError('INVALID_JOB_ID_BATCH',400);
  const c=await context(catalog,personal,owner);
  const result:Record<string,ReturnType<typeof record>>={};
  if (jobIds.length) {
    const placeholders=jobIds.map(()=>'?').join(',');
    const rows=await personal.prepare(`${selectRef} WHERE ref.owner_id=? AND ref.job_id IN (${placeholders})`)
      .bind(c.ownerId,...jobIds).all<RefRow>();
    const extras=await flags(catalog,personal,c.ownerId,rows.results.map(x=>x.jobId));
    for(const row of rows.results){
      const state=extras.get(row.jobId);
      if(!state)throw new ModelCPersonalReadError('REFERENCE_STATE_UNAVAILABLE',503);
      result[row.jobId]=record(row,c,state);
    }
  }
  await assertUnchanged(catalog,personal,c);
  return {...publicContext(c),items:result};
}
