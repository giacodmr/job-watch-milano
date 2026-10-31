// Inactive Node-only Model C importer. No Worker/browser entrypoint or D1 binding.
import { randomUUID } from 'node:crypto';
import {verifyTrustedStagingAgainstSnapshot,verifyPublishedStageReplay} from './model-c-trusted-stage';
import {advanceCompleteIngestJournal,advanceIngestJournal,nextJournalStatement,observeIngestJournal} from './model-c-publication-journal';
import {inspectPublishedModelCRecovery} from './model-c-import-recovery';
import type {prepareSafeRemoteBootstrapPlan} from './model-c-remote-plan';
import { canonical, sha256 } from '../shared/canonical';
import { selectModelC } from '../shared/model-c-selection';
import type { IdentityLedger, SelectionContext } from '../shared/model-c-selection';
import { catalogObservation, verifyProjectionProof } from '../shared/projection-proof';
import type { CatalogObservation } from '../shared/projection-proof';
import { verifyGitProjection } from './model-c-git';
import type { GitSource } from './model-c-git';

type Row = Record<string, string | number | null>;
type Phase = 'staging' | 'promotion' | 'checkpoint' | 'cleanup';
type Step = { sql:string; values:(string | number | null)[]; writes:Record<string,number>; phase?:Phase };
const maxParameters=80, maxStatementSqlBytes=64*1024;
type Selected = Awaited<ReturnType<typeof selectModelC>>;
export interface ImportOptions {
  source: GitSource;
  // Required explicit empty-target authorization; for migration supply v1 instead.
  bootstrap?: 'empty-target';
  v1?: D1Database;
  owner: string;
  oneTimeFreeBootstrap?: boolean;
  executionTarget?: 'local-ephemeral' | 'remote';
  preflightOnly?: boolean;
  // Optional M47 lab-only: bind an M46 staged run to the independently
  // replayed full Git snapshot before ANY importer writes. Never a service grant.
  stagedPublication?: {runId:string;trustedPlan:Awaited<ReturnType<typeof prepareSafeRemoteBootstrapPlan>>};
  budget: { day:string; availableRows:number; extendedAuthorized?:boolean };
}
export interface ImportMetrics {
  reservation:number; personal:number; publication:number; reconciliation:number; cleanup:number;
  total:number; requiredBound:number; reservedBound:number; publicationStatements:number; publicationBytes:number; publicationMs:number;
  staging:number; promotion:number; checkpoint:number;
  maxStatementParameters:number; maxStatementSqlBytes:number; totalParameters:number;
  nodeHeapUsedBytes:number; nodeRssBytes:number;
  writeBounds:Record<string,number>; writeUnits:Record<string,{rows:number;indexes:number;bound:number}>;
}
const catalogTables = ['catalog_head','catalog_runs','catalog_content_revisions','catalog_ledger_checkpoints','catalog_run_proofs',
  'catalog_company_identity','catalog_source_identity','catalog_vacancy_identity','catalog_aliases',
  'catalog_company_current','catalog_source_current','catalog_vacancy_current'];
const personalTables = ['personal_owners','personal_job_refs','personal_reference_state','personal_decision_events','personal_decision_current',
  'personal_assessment_events','personal_assessment_current','personal_heads','personal_reconciliation','personal_catalog_receipts'];
const read = async (db:D1Database, tables:string[]) => {
  const results = await db.batch<Row>(tables.map(t=>db.prepare('SELECT * FROM '+t)));
  return Object.fromEntries(tables.map((t,i)=>[t,results[i]!.results]));
};
const sorted = (rows:Row[]) => [...rows].sort((a,b)=>canonical(a)<canonical(b)?-1:canonical(a)>canonical(b)?1:0);
const digestRows = (data:Record<string,Row[]>) => sha256(canonical(Object.fromEntries(Object.entries(data).map(([t,rows])=>[t,sorted(rows)]))));
function personalGuard(data:Record<string,Row[]>) {
  const checks:Step[]=[];
  let conditions:string[]=[], values:Step['values']=[];
  const flush=()=>{
    if(conditions.length)checks.push({sql:'INSERT INTO personal_import_assert VALUES ('+conditions.join(' AND ')+')',values,writes:{personal_import_assert:2}});
    conditions=[];values=[];
  };
  for (const [t,rows] of Object.entries(data)) {
    conditions.push('(SELECT count(*) FROM '+t+')='+rows.length);
    for (const r of rows) {
      if(values.length+Object.keys(r).length>80)flush();
      conditions.push('EXISTS(SELECT 1 FROM '+t+' WHERE '+Object.keys(r).map(c=>c+' IS ?').join(' AND ')+')');
      values.push(...Object.values(r));
    }
  }
  flush();return checks;
}
const statement = (sql:string, values:Step['values']=[], writes:Step['writes']={}) => ({sql,values,writes});
function insert(table:string, row:Row, update=false):Step {
  const cols=Object.keys(row);
  const suffix = update ? ' ON CONFLICT('+cols[0]+') DO UPDATE SET '+cols.slice(1).map(c=>c+'=excluded.'+c).join(',') : '';
  return statement('INSERT INTO '+table+' ('+cols.join(',')+') VALUES ('+cols.map(()=>'?').join(',')+')'+suffix,Object.values(row),{[table]:update?2:1});
}
/** Group only identical column shapes. Every bound row and index/trigger effect
 * stays in writes, independent of the number of SQL statements emitted. */
function insertMany(table:string, rows:Row[], phase:Phase):Step[] {
  const shapes=new Map<string,Row[]>();
  for(const row of rows) {
    const shape=Object.keys(row).join(',');
    const group=shapes.get(shape)??[];group.push(row);shapes.set(shape,group);
  }
  const steps:Step[]=[];
  for(const [shape,records] of shapes) {
    const columns=shape.split(','), size=Math.floor(maxParameters/columns.length);
    if(!size)throw Error('STATEMENT_LIMIT');
    for(let offset=0;offset<records.length;offset+=size) {
      const part=records.slice(offset,offset+size);
      const sql='INSERT INTO '+table+' ('+shape+') VALUES '+part.map(()=> '('+columns.map(()=>'?').join(',')+')').join(',');
      if(Buffer.byteLength(sql)>maxStatementSqlBytes)throw Error('STATEMENT_LIMIT');
      steps.push({...statement(sql,part.flatMap(r=>columns.map(c=>r[c]!)),{[table]:part.length}),phase});
    }
  }
  return steps;
}
const prepared = (db:D1Database, steps:Step[]) => steps.map(s=>db.prepare(s.sql).bind(...s.values));
async function execute(db:D1Database, steps:Step[]) {
  if (!steps.length) return 0;
  return (await db.batch(prepared(db,steps))).reduce((n,r)=>n+(r.meta.rows_written??0),0);
}
function ledger(data:Record<string,Row[]>):IdentityLedger {
  return {
    identities:data.catalog_vacancy_identity!.map(r=>({jobId:String(r.id),companyId:String(r.company_id),originJobKey:String(r.origin_job_key)})).sort((a,b)=>a.jobId<b.jobId?-1:1),
    mappings:data.catalog_aliases!.map(r=>({key:String(r.alias_key),jobId:String(r.job_id)})).sort((a,b)=>a.key<b.key?-1:1),
  };
}
async function trustedCatalog(db:D1Database) {
  const data=await read(db,catalogTables), head=data.catalog_head![0], fullLedger=ledger(data);
  let previous:CatalogObservation|undefined;
  if (head) {
    const run=data.catalog_runs!.find(r=>r.id===head.run_id), content=data.catalog_content_revisions!.find(r=>r.revision===head.content_revision), checkpoint=data.catalog_ledger_checkpoints!.find(r=>r.revision===head.ledger_revision);
    if (!run || run.state!=='PUBLISHED' || !content || !checkpoint || checkpoint.ledger_digest!==await sha256(canonical(fullLedger)) ||
      checkpoint.identity_count!==fullLedger.identities.length || checkpoint.mapping_count!==fullLedger.mappings.length) throw Error('UNTRUSTED_LEDGER');
    previous={contract:'job-watch-model-c/1',observedGitCommit:String(run.observed_commit),projectionInputDigest:String(run.projection_digest),
      catalogContentDigest:String(content.content_digest),catalogRevision:Number(head.content_revision),contentOrigin:{commitSha:String(content.origin_commit),sourceManifestDigest:String(content.origin_manifest_digest)}};
  } else if (catalogTables.filter(t=>!['catalog_head'].includes(t)).some(t=>data[t]!.length)) throw Error('NONEMPTY_BOOTSTRAP_REFUSED');
  return {data,head,ledger:fullLedger,previous};
}
async function v1Ledger(db:D1Database) {
  if (await db.prepare('SELECT version FROM schema_metadata WHERE id=1').first('version')!==5) throw Error('V1_SCHEMA_REQUIRED');
  const d=await read(db,['sync_checkpoints','sync_snapshots','jobs','job_aliases','job_versions','snapshot_job_aliases','user_decisions','semantic_reviews','snapshot_user_decisions','snapshot_semantic_reviews','companies','sources','source_versions','company_versions']);
  const checkpoint=d.sync_checkpoints!.find(r=>r.scope==='main'), snapshot=d.sync_snapshots!.find(r=>r.id===checkpoint?.snapshot_id);
  if (!checkpoint || !snapshot || snapshot.state!=='CONFIRMED') throw Error('V1_CHECKPOINT_REQUIRED');
  const confirmed=new Map(d.sync_snapshots!.filter(r=>r.state==='CONFIRMED').map(r=>[String(r.id),r]));
  if (d.jobs!.some(j=>!d.job_versions!.some(v=>v.job_id===j.id&&confirmed.has(String(v.snapshot_id)))) ||
    d.job_aliases!.some(a=>!d.snapshot_job_aliases!.some(m=>m.alias_key===a.alias_key&&m.job_id===a.job_id&&confirmed.has(String(m.snapshot_id))))) throw Error('V1_UNCONFIRMED_LEDGER');
  if(d.companies!.some(c=>!d.company_versions!.some(v=>v.company_id===c.id&&confirmed.has(String(v.snapshot_id))))||d.sources!.some(c=>!d.source_versions!.some(v=>v.source_id===c.id&&confirmed.has(String(v.snapshot_id)))))throw Error('V1_UNCONFIRMED_LEDGER');
  const captures:Row[]=[], events:{table:string;row:Row}[]=[];
  for (const [table,membership,idColumn,target] of [['user_decisions','snapshot_user_decisions','decision_id','personal_decision_events'],['semantic_reviews','snapshot_semantic_reviews','review_id','personal_assessment_events']] as const) for (const e of d[table]!) {
    const membershipRow=d[membership]!.find(m=>m[idColumn]===e.id&&confirmed.has(String(m.snapshot_id)));
    if (!membershipRow) throw Error('V1_UNCONFIRMED_PERSONAL_FACT');
    const source=confirmed.get(String(e.snapshot_id));if(!source)throw Error('V1_UNCONFIRMED_PERSONAL_ORIGIN');
    const expected=(table==='user_decisions'?'decision:':'review:')+await sha256(String(e.job_id)+'\0'+String(e.result_sha256));
    if(e.id!==expected)throw Error('V1_EVENT_ID_MISMATCH');
    const row:Row={id:e.id!,job_id:e.job_id!,fingerprint:e.fingerprint!,decision:e.decision!,result_sha256:e.result_sha256!,source_commit:source.commit_sha!,source_path:e.source_path!,source_sha256:e.source_sha256!};
    if(table==='user_decisions')Object.assign(row,{rejection_reason:e.rejection_reason,reason_summary:e.reason_summary,decided_at:e.decided_at});
    else Object.assign(row,{method:e.analysis_method,fit_score:e.fit_score,reportable:e.reportable,summary:e.rationale_summary,evidence_state:e.evidence_state,analyzed_at:e.analyzed_at});
    events.push({table:target,row});
    if(!captures.some(c=>c.job_id===e.job_id)) {
      const versions=d.job_versions!.filter(v=>v.job_id===e.job_id&&confirmed.has(String(v.snapshot_id))).sort((a,b)=>Number(confirmed.get(String(b.snapshot_id))!.published_revision??0)-Number(confirmed.get(String(a.snapshot_id))!.published_revision??0));
      const v=versions[0];if(!v)throw Error('V1_PERSONAL_CAPTURE_REQUIRED');
      captures.push({job_id:e.job_id!,captured_title:v.title!,official_url:v.canonical_url??v.apply_url??null,last_known_lifecycle:v.lifecycle!,captured_commit:confirmed.get(String(v.snapshot_id))!.commit_sha!,captured_path:v.source_path!,captured_sha256:v.source_sha256!,revision:1});
    }
  }
  const identities=d.jobs!.map(r=>({jobId:String(r.id),companyId:String(r.company_id),originJobKey:String(r.origin_job_key)})).sort((a,b)=>a.jobId<b.jobId?-1:1);
  const mappings=new Map(identities.map(r=>[r.originJobKey,r.jobId]));
  for (const r of d.job_aliases!) {
    const key=String(r.alias_key), job=String(r.job_id);
    if (!identities.some(i=>i.jobId===job) || (mappings.has(key)&&mappings.get(key)!==job)) throw Error('V1_LEDGER_CONFLICT');
    mappings.set(key,job);
  }
  return {companies:d.companies!,sources:d.sources!,aliasResolutions:Object.fromEntries(d.job_aliases!.map(a=>[String(a.alias_key),String(a.resolution)])),sourceDigest:await digestRows(d),captures,events,commit:String(snapshot.commit_sha),ledger:{identities,mappings:[...mappings].map(([key,jobId])=>({key,jobId})).sort((a,b)=>a.key<b.key?-1:1)}};
}
function requireSingleOwner(data:Record<string,Row[]>, owner:string) {
  // CATALOG is shared and has no owner scope: do not silently project another
  // owner's choices into it. Multi-owner publication is not supported locally.
  if (data.personal_owners!.some(r=>r.owner_id!==owner) ||
    Object.values(data).some(rows=>rows.some(r=>'owner_id' in r && r.owner_id!==owner))) throw Error('MULTI_OWNER_PERSONAL_UNSUPPORTED');
}
function references(data:Record<string,Row[]>, owner:string) {
  requireSingleOwner(data,owner);
  for (const ref of data.personal_job_refs!) if (!data.personal_heads!.some(h=>h.owner_id===ref.owner_id)) throw Error('PERSONAL_HEAD_REQUIRED');
  return data.personal_reference_state!.filter(r=>r.active===1).map(r=>({jobId:String(r.job_id),kind:r.kind as 'SAVED'|'APPLICATION'|'DISMISSED'}))
    .filter((r,i,rows)=>rows.findIndex(x=>x.jobId===r.jobId&&x.kind===r.kind)===i).sort((a,b)=>canonical(a)<canonical(b)?-1:1);
}
const bool = (v:boolean|null) => v===null?null:Number(v);

/** Bound counts table rows AND every index entry (twice for replacement), plus
 * explicit trigger effects. Schema-role/version checks pin the trigger set.
 * Bounds are admission estimates; actual meta.rows_written is reported separately.
 */
async function estimateWrites(db:D1Database, steps:Step[]) {
  const tables=[...new Set(steps.flatMap(s=>Object.keys(s.writes)))], weights=new Map<string,number>();
  for (const t of tables) weights.set(t,(await db.prepare('PRAGMA index_list('+t+')').all()).results.length);
  const byPhase:Record<string,number>={}, byTable:ImportMetrics['writeUnits']={};
  let total=0;
  for(const step of steps)for(const [table,rows] of Object.entries(step.writes)) {
    const indexes=weights.get(table)!, cost=rows*(1+indexes), phase=step.phase??'checkpoint';
    total+=cost;byPhase[phase]=(byPhase[phase]??0)+cost;
    const entry=byTable[table]??{rows:0,indexes,bound:0};entry.rows+=rows;entry.bound+=cost;byTable[table]=entry;
  }
  return {total,byPhase,byTable};
}
async function bound(db:D1Database, steps:Step[]) {return (await estimateWrites(db,steps)).total;}
async function reserve(db:D1Database, budget:ImportOptions['budget'], rows:number, initial?:Awaited<ReturnType<typeof verifyProjectionProof>>) {
  const limit=initial?95000:budget.extendedAuthorized?60000:30000;
  if (budget.day!==new Date().toISOString().slice(0,10) || !/^\d{4}-\d{2}-\d{2}$/.test(budget.day) || !Number.isSafeInteger(budget.availableRows) || budget.availableRows<0 || budget.availableRows>limit) throw Error('INVALID_WRITE_BUDGET');
  if (rows>budget.availableRows) throw Error('WRITE_BUDGET_INSUFFICIENT');
  const charged=Number(await db.prepare('SELECT charged FROM catalog_write_totals WHERE day=?').bind(budget.day).first('charged')??0);
  if(charged+rows>budget.availableRows)throw Error('WRITE_BUDGET_INSUFFICIENT'); // SQL trigger repeats this atomically
  if(initial)return execute(db,[
    statement('INSERT INTO catalog_cas_guard VALUES (0)',[],{catalog_cas_guard:2}),
    statement('INSERT INTO catalog_write_days VALUES (?,0) ON CONFLICT DO NOTHING',[budget.day],{catalog_write_days:1}),
    statement('INSERT INTO catalog_initial_bootstrap_reservations VALUES (?,?,?,?,?,?,?)',[randomUUID(),budget.day,rows,budget.availableRows,initial.observedGitCommit,initial.sourceManifestDigest,initial.projectionInputDigest],{catalog_initial_bootstrap_reservations:1}),
  ]);
  return execute(db,[statement('INSERT INTO catalog_write_days VALUES (?,0) ON CONFLICT DO NOTHING',[budget.day],{catalog_write_days:1}),
    statement('INSERT INTO catalog_write_reservations VALUES (?,?,?,?)',[randomUUID(),budget.day,rows,budget.availableRows],{catalog_write_reservations:1,catalog_write_days:2})]);
}

/** All current changes, ledger extension, staging/seal, head and trigger audit are
 * committed by ONE batch. An exception before/during it preserves the old head.
 * No API accepts an unverified selection, ledger digest, or ancestry callback.
 */
export class ModelCImportError extends Error {
  constructor(code:string, readonly metrics:ImportMetrics) {super(code);}
}
const emptyMetrics=():ImportMetrics=>({reservation:0,personal:0,publication:0,reconciliation:0,cleanup:0,total:0,requiredBound:0,reservedBound:0,publicationStatements:0,publicationBytes:0,publicationMs:0,staging:0,promotion:0,checkpoint:0,maxStatementParameters:0,maxStatementSqlBytes:0,totalParameters:0,nodeHeapUsedBytes:0,nodeRssBytes:0,writeBounds:{},writeUnits:{}});
/** Read-only preflight used by the importer and boundary probes; never executes SQL. */
export function inspectCatalogPlan(steps:readonly Step[], metrics:ImportMetrics=emptyMetrics()) {
  metrics.publicationStatements=steps.length;metrics.publicationBytes=Buffer.byteLength(canonical(steps));
  metrics.maxStatementParameters=Math.max(0,...steps.map(s=>s.values.length));
  metrics.totalParameters=steps.reduce((n,s)=>n+s.values.length,0);
  metrics.maxStatementSqlBytes=Math.max(0,...steps.map(s=>Buffer.byteLength(s.sql)));
  const memory=process.memoryUsage();metrics.nodeHeapUsedBytes=memory.heapUsed;metrics.nodeRssBytes=memory.rss;
  if(metrics.maxStatementParameters>maxParameters || metrics.maxStatementSqlBytes>maxStatementSqlBytes)throw Error('STATEMENT_LIMIT');
  if (steps.length>8000 || metrics.publicationBytes>8*1024*1024) throw Error('ATOMIC_PUBLICATION_LIMIT');
  return metrics;
}
export async function importModelC(catalog:D1Database, personal:D1Database, options:ImportOptions) {
  const metrics=emptyMetrics();
  try {return await importAttempt(catalog,personal,options,metrics);}
  catch(error) {
    metrics.total=metrics.reservation+metrics.personal+metrics.publication+metrics.reconciliation+metrics.cleanup;
    const message=error instanceof Error?error.message:'';
    const known:{[key:string]:string}={catalog_cas_conflict:'CATALOG_CAS_CONFLICT',incomplete_chunks:'INCOMPLETE_STAGING',write_budget_exhausted:'WRITE_BUDGET_INSUFFICIENT','CHECK constraint failed':'IMPORT_ASSERTION_FAILED'};
    const code=/^[A-Z][A-Z0-9_]+$/.test(message)?message:Object.entries(known).find(([text])=>message.includes(text))?.[1]??'MODEL_C_IMPORT_FAILED';
    // No source paths, SQL, payloads, stack/cause from Python/Git/D1 in errors.
    throw new ModelCImportError(code,metrics);
  }
}
async function importAttempt(catalog:D1Database, personal:D1Database, options:ImportOptions,metrics:ImportMetrics) {
  // A transport marker is NOT an authorization. Never enter the remote
  // mutation path for normal deltas or the exceptional initial bootstrap.
  // Read-only bootstrap preflights may plan with executionTarget='remote'.
  if(!options.preflightOnly && options.executionTarget!=='local-ephemeral')
    throw Error('REMOTE_IMPORT_NOT_AUTHORIZED');
  if (catalog===personal || await catalog.prepare('SELECT version FROM model_c_schema WHERE scope=\'CATALOG\'').first('version')!==6 ||
    await personal.prepare('SELECT version FROM model_c_schema WHERE scope=\'PERSONAL\'').first('version')!==3) throw Error('SEPARATE_MODEL_C_DATABASES_REQUIRED');
  if (!options.owner || options.owner.length>200) throw Error('INVALID_PERSONAL_OWNER');
  const old=await trustedCatalog(catalog), privateData=await read(personal,personalTables), privateDigest=await digestRows(privateData);
  if(options.oneTimeFreeBootstrap!==undefined && typeof options.oneTimeFreeBootstrap!=='boolean')throw Error('INVALID_BOOTSTRAP_AUTHORIZATION');
  if(options.oneTimeFreeBootstrap && old.head)throw Error('ONE_TIME_BOOTSTRAP_NOT_INITIAL');
  if(options.preflightOnly && !options.oneTimeFreeBootstrap)throw Error('FREE_BOOTSTRAP_PREFLIGHT_REQUIRES_MODE');
  let startingLedger=old.ledger, previousCommit=old.previous?.observedGitCommit;
  let legacy:Awaited<ReturnType<typeof v1Ledger>>|undefined;
  if (!old.head && options.v1) { legacy=await v1Ledger(options.v1); startingLedger=legacy.ledger; previousCommit=legacy.commit; }
  if (!old.head && !options.v1 && options.bootstrap!=='empty-target') throw Error('EXPLICIT_BOOTSTRAP_REQUIRED');
  const activeRefs=references(privateData,options.owner);
  const personalDecisionJobIds=[...new Set([...privateData.personal_decision_events!.map(e=>String(e.job_id)),
    ...(legacy?.events.filter(e=>e.table==='personal_decision_events').map(e=>String(e.row.job_id))??[])])].sort();
  const context:SelectionContext={identities:old.head||options.v1 ? {mode:'confirmed-ledger',ledger:startingLedger,expectedDigest:await sha256(canonical(startingLedger))} : {mode:'first-v1-bootstrap'},personalReferences:activeRefs,personalDecisionJobIds};
  const verified=await verifyGitProjection(options.source,context,previousCommit), {bundle}=verified;
  const proof=await verifyProjectionProof(bundle,verified.proof,context), selected=await selectModelC(bundle,context);

  // Check ALL personal references against permanent identities, including inactive
  // refs and historical decisions, not just currently selected vacancies.
  if (privateData.personal_job_refs!.some(r=>!selected.ledger.identities.some(i=>i.jobId===r.job_id)) ||
    privateData.personal_assessment_events!.some(r=>!selected.ledger.identities.some(i=>i.jobId===r.job_id))) throw Error('UNRESOLVED_PERSONAL_REFERENCE');
  const observation=catalogObservation(proof,selected.catalogContentDigest,old.previous);
  const environmentDigest=await sha256(canonical({...proof.inputs,selectionContextDigest:'0'.repeat(64)})), referenceDigest=await sha256(canonical(activeRefs));
  const savedProof=old.data.catalog_run_proofs!.find(p=>p.run_id===old.head?.run_id);
  const same=old.previous?.observedGitCommit===bundle.manifest.commitSha && old.previous.catalogContentDigest===selected.catalogContentDigest &&
    savedProof?.manifest_digest===proof.sourceManifestDigest && savedProof.environment_digest===environmentDigest && savedProof.reference_digest===referenceDigest;
  const recoveryStage=options.stagedPublication && old.head?.run_id===options.stagedPublication.runId;
  if(options.stagedPublication){
    if(recoveryStage){
      // An already published run must ONLY be replayed/reconciled, never
      // promoted again with a new revision or a changed selection context.
      if(!same)throw Error('STAGED_REPLAY_CONTEXT_CHANGED');
      await verifyPublishedStageReplay(catalog,options.stagedPublication.runId,
        proof,options.stagedPublication.trustedPlan);
    }else{
      await verifyTrustedStagingAgainstSnapshot(catalog,options.stagedPublication.runId,
        bundle,selected,proof,options.stagedPublication.trustedPlan);
    }
  }
  // Reuse the immutable M46 ingest run ID as the published CATALOG run ID.
  // The shared key is a durable cross-phase binding without a new D1 schema
  // or a fictitious cross-database transaction.
  const run=same?String(old.head!.run_id):
    options.stagedPublication?.runId??'import:'+await sha256(canonical({
      commit:bundle.manifest.commitSha,projection:proof.projectionInputDigest,
      expected:old.head?.sync_revision??0,
    }));
  if (legacy&&options.v1&&(await v1Ledger(options.v1)).sourceDigest!==legacy.sourceDigest)throw Error('V1_CONTEXT_CHANGED');
  const personalSteps=await planPersonal(privateData,selected,bundle.chunks.flat(),options.owner,bundle.manifest.commitSha,legacy);
  if (!same) for (const ref of privateData.personal_job_refs!) {
    if (personalSteps.some(s=>s.sql.startsWith('INSERT INTO personal_reconciliation')&&s.values[0]===ref.owner_id&&s.values[1]===ref.job_id)) continue;
    const h=privateData.personal_heads!.find(h=>h.owner_id===ref.owner_id)!;
    const r=privateData.personal_reconciliation!.find(r=>r.owner_id===ref.owner_id&&r.job_id===ref.job_id);
    if(r?.state==='PENDING'&&r.personal_revision===h.revision)continue;
    personalSteps.push(statement("INSERT INTO personal_reconciliation VALUES (?,?,?,'PENDING',NULL,NULL) ON CONFLICT(owner_id,job_id) DO UPDATE SET personal_revision=excluded.personal_revision,state='PENDING',receipt_id=NULL,error_code=NULL",[ref.owner_id!,ref.job_id!,h.revision!],{personal_reconciliation:2}));
  }
  const expected=Number(old.head?.sync_revision??0), syncRevision=same?expected:expected+1;
  const contentRevision=observation.catalogRevision, ledgerChanged=await sha256(canonical(old.ledger))!==selected.ledgerDigest;
  const ledgerRevision=old.head?Number(old.head.ledger_revision)+(ledgerChanged?1:0):1;
  const publication:Step[]=same?[]:await planCatalog(old,selected,bundle.chunks.flat(),run,proof,contentRevision,ledgerRevision,environmentDigest,referenceDigest,legacy);
  const cleanup=await cleanupPlan(catalog,same?run:undefined);
  // New run's staged rows will also be cleaned after publication.
  if (!same) cleanup.push(...cleanupFor(run,publication));
  for(const step of cleanup)step.phase='cleanup';
  const receipt={id:'receipt:'+run,catalog_sync_revision:syncRevision,catalog_content_revision:contentRevision,observed_commit:bundle.manifest.commitSha,
    ledger_digest:selected.ledgerDigest,head_digest:await sha256(canonical({syncRevision,run,contentRevision,ledgerRevision,ledgerDigest:selected.ledgerDigest}))};
  // Reconciliation runs after PERSONAL append + catalog commit, using a new read.
  const newPrivateRows=personalSteps.filter(s=>personalTables.some(t=>s.sql.startsWith('INSERT INTO '+t+' '))).length;
  const newRefs=personalSteps.filter(s=>s.sql.startsWith('INSERT INTO personal_job_refs ')).length;
  const reconBound=await bound(personal,personalGuard(privateData))+newPrivateRows*2+(privateData.personal_job_refs!.length+newRefs)*4+12;
  inspectCatalogPlan(publication,metrics);
  // Even an owner with ZERO personal_job_refs must have a durable, exactly
  // matching catalog receipt. Otherwise a lost acknowledgment after CATALOG
  // commit could incorrectly return RECOVERED while PERSONAL remains unbound.
  const receiptMatches=privateData.personal_catalog_receipts!.some(r=>
    r.id===receipt.id&&canonical(r)===canonical(receipt));
  const pendingReconciliation=!same || personalSteps.length>0 || !receiptMatches ||
    privateData.personal_job_refs!.some(r=>!privateData.personal_reconciliation!.some(v=>
      v.owner_id===r.owner_id&&v.job_id===r.job_id&&v.state==='VERIFIED'&&
      v.receipt_id===receipt.id&&v.personal_revision===
        privateData.personal_heads!.find(h=>h.owner_id===r.owner_id)?.revision));
  const catalogEstimate=await estimateWrites(catalog,[...publication,...cleanup]);
  const privateBound=await bound(personal,personalSteps.length?[...personalGuard(privateData),...personalSteps]:[]);
  const estimated=catalogEstimate.total+privateBound+(pendingReconciliation?reconBound:0);
  const journalSnapshot=options.stagedPublication?await observeIngestJournal(catalog,run):null;
  // Every pre-/post-publication journal write is included in the conservative
  // bound, including a replay that must finalize previously reconciled facts.
  const journalBound=options.stagedPublication&&journalSnapshot?.phase!=='COMPLETED'?40:0;
  if (estimated===0&&journalBound===0) return {status:'REPLAY' as const,run,observation,syncRevision,metrics};
  metrics.writeBounds={...catalogEstimate.byPhase,personal:privateBound,
    reconciliation:pendingReconciliation?reconBound:0,reservation:20,journal:journalBound};
  metrics.writeUnits=catalogEstimate.byTable;
  metrics.requiredBound=estimated+20+journalBound; // all aggregated rows, indexes, known trigger effects and reservation itself
  if(options.preflightOnly)return {status:'PREFLIGHT' as const,run,observation,syncRevision,metrics,
    provenance:{observedCommit:proof.observedGitCommit,manifestDigest:proof.sourceManifestDigest,projectionDigest:proof.projectionInputDigest},
    budgetDay:options.budget.day,priorLocalReservations:Number(await catalog.prepare('SELECT charged FROM catalog_write_totals WHERE day=?').bind(options.budget.day).first('charged')??0),
    remoteQuotaStatus:'QUOTA_VERIFICATION_REQUIRED' as const,remoteExecutionAuthorized:false as const};
  // No remote transport/account meter is enabled. Explicit local-only attestation
  // is required; a separate read-only quota assessment never authorizes execution.
  if(options.oneTimeFreeBootstrap && options.executionTarget!=='local-ephemeral')throw Error('QUOTA_VERIFICATION_REQUIRED');
  metrics.reservation=await reserve(catalog,options.budget,metrics.requiredBound,options.oneTimeFreeBootstrap?proof:undefined);
  metrics.reservedBound=metrics.requiredBound; // only after the daily reservation really committed
  const m47=options.stagedPublication;
  const stageVerifiedDigest=m47?await sha256(canonical({
    run,phase:'VERIFIED',commit:proof.observedGitCommit,
    manifest:m47.trustedPlan.origin.manifestDigest,
    projection:m47.trustedPlan.origin.projectionDigest,
    ledger:selected.ledgerDigest,content:selected.catalogContentDigest,
    plan:m47.trustedPlan.digest,
  })):null;
  const personalPreparedDigest=m47?await sha256(canonical({
    run,phase:'PERSONAL_PREPARED',source:m47.trustedPlan.origin.projectionDigest,
    // Bind replay to the ORIGINAL immutable ingestion revision, never the
    // already-advanced catalog HEAD observed during recovery.
    expectedRevision:m47.trustedPlan.syncRevision-1,
  })):null;
  const catalogPublishedDigest=m47?await sha256(canonical({
    run,phase:'CATALOG_PUBLISHED',syncRevision,contentRevision,ledgerRevision,
    headDigest:receipt.head_digest,
  })):null;
  if(m47){
    const current=await observeIngestJournal(catalog,run);
    if(current.phase==='RECEIVING'){
      await advanceCompleteIngestJournal(catalog,run);
      metrics.publication++;
    }
    const before=await observeIngestJournal(catalog,run);
    const after=await advanceIngestJournal(catalog,run,'VERIFIED',stageVerifiedDigest!);
    if(after.sequence>before.sequence)metrics.publication++;
  }
  // Detect modifications between proof construction and the first private batch.
  if (await digestRows(await read(personal,personalTables))!==privateDigest) throw Error('PERSONAL_CONTEXT_CHANGED');
  let afterPersonal=privateDigest;
  if(personalSteps.length) {
    const mutations=[...personalGuard(privateData),...personalSteps];
    // Capture the resulting context INSIDE the append transaction. A fresh read
    // after commit could silently adopt a competing writer's newer context.
    const result=await personal.batch<Row>([...prepared(personal,mutations),...personalTables.map(t=>personal.prepare('SELECT * FROM '+t))]);
    metrics.personal=result.reduce((n,r)=>n+(r.meta.rows_written??0),0);
    afterPersonal=await digestRows(Object.fromEntries(personalTables.map((t,i)=>[t,result[mutations.length+i]!.results])));
  }
  if (await digestRows(await read(personal,personalTables))!==afterPersonal) throw Error('PERSONAL_CONTEXT_CHANGED');
  if(m47){
    const before=await observeIngestJournal(catalog,run);
    const after=await advanceIngestJournal(catalog,run,'PERSONAL_PREPARED',personalPreparedDigest!);
    if(after.sequence>before.sequence)metrics.publication++;
    if(publication.length){
      // The publication journal entry is committed AFTER the head switch in
      // the same transactional D1 batch; a failure rolls back BOTH.
      const entry=await nextJournalStatement(catalog,run,'CATALOG_PUBLISHED',catalogPublishedDigest!);
      if(entry.status!=='READY'||!entry.statement)throw Error('JOURNAL_PUBLICATION_INVALID_STATE');
      publication.push({...entry.statement,phase:'checkpoint'});
      inspectCatalogPlan(publication,metrics);
    }else {
      const journal=await observeIngestJournal(catalog,run);
      if(!journal.events.some(x=>x.phase==='CATALOG_PUBLISHED'&&
        x.proofDigest===catalogPublishedDigest))
        throw Error('JOURNAL_PUBLISHED_HEAD_MISMATCH');
    }
  }
  const start=performance.now();
  if(publication.length) {
    const result=await catalog.batch(prepared(catalog,publication));
    for(const [i,r] of result.entries()) {
      const written=r.meta.rows_written??0;metrics.publication+=written;
      const phase=publication[i]!.phase??'checkpoint';
      if(phase!=='cleanup')metrics[phase]+=written;
    }
  }
  metrics.publicationMs=performance.now()-start;
  if (await digestRows(await read(personal,personalTables))!==afterPersonal) throw Error('PERSONAL_CONTEXT_CHANGED');
  if (pendingReconciliation) metrics.reconciliation=await reconcile(catalog,personal,receipt,selected,options.owner);
  if(m47){
    const inspected=await inspectPublishedModelCRecovery(catalog,personal,{ownerId:options.owner});
    if(inspected.status!=='PUBLISHED_RECEIPTS_RECONCILED'||
      inspected.catalogRunId!==run)throw Error('JOURNAL_PERSONAL_NOT_VERIFIED');
    const before=await observeIngestJournal(catalog,run);
    const reconciled=await advanceIngestJournal(catalog,run,'PERSONAL_RECONCILED',receipt.head_digest);
    const final=await advanceIngestJournal(catalog,run,'COMPLETED',
      await sha256(canonical({run,phase:'COMPLETED',head:receipt.head_digest})));
    metrics.reconciliation+=final.sequence-before.sequence;
  }
  metrics.cleanup=await execute(catalog,cleanup);
  metrics.total=metrics.reservation+metrics.personal+metrics.publication+metrics.reconciliation+metrics.cleanup;
  if (metrics.total>metrics.reservedBound) throw Error('WRITE_BOUND_EXCEEDED');
  return {status:same?'RECOVERED' as const:'PUBLISHED' as const,run,observation,syncRevision,metrics};
}

async function planCatalog(old:Awaited<ReturnType<typeof trustedCatalog>>, selected:Selected, rows:Awaited<ReturnType<typeof verifyGitProjection>>['bundle']['chunks'][number], run:string,
  proof:Awaited<ReturnType<typeof verifyProjectionProof>>, contentRevision:number, ledgerRevision:number, environmentDigest:string, referenceDigest:string, legacy?:Awaited<ReturnType<typeof v1Ledger>>) {
  const steps:Step[]=[statement('INSERT INTO catalog_cas_guard VALUES (?)',[Number(old.head?.sync_revision??0)],{catalog_cas_guard:2})];
  if (!old.head || contentRevision!==old.head.content_revision) steps.push(insert('catalog_content_revisions',{revision:contentRevision,content_digest:selected.catalogContentDigest,origin_commit:proof.observedGitCommit,origin_manifest_digest:proof.sourceManifestDigest}));
  if (!old.head || ledgerRevision!==old.head.ledger_revision) steps.push(insert('catalog_ledger_checkpoints',{revision:ledgerRevision,ledger_digest:selected.ledgerDigest,identity_count:selected.ledger.identities.length,mapping_count:selected.ledger.mappings.length}));
  const companies=rows.filter(r=>r.kind==='company'), sources=rows.filter(r=>r.kind==='source'), jobs=rows.filter(r=>r.kind==='job');
  steps.push(insert('catalog_runs',{id:run,observed_commit:proof.observedGitCommit,projection_digest:proof.projectionInputDigest,expected_revision:Number(old.head?.sync_revision??0),content_revision:contentRevision,ledger_revision:ledgerRevision,expected_chunks:1,expected_companies:companies.length,expected_sources:sources.length,expected_vacancies:selected.catalog.length}));
  steps.push(insert('catalog_run_proofs',{run_id:run,manifest_digest:proof.sourceManifestDigest,environment_digest:environmentDigest,reference_digest:referenceDigest}));
  const origins=new Map<string,string>(), originRows:Row[]=[];
  async function origin(path:string,hash:string) {
    const key=path+'\0'+hash;
    let id=origins.get(key);
    if (!id) { id='origin:'+await sha256(run+'\0'+key); origins.set(key,id); originRows.push({id,run_id:run,commit_sha:proof.observedGitCommit,source_path:path,source_sha256:hash}); }
    return id;
  }
  const fallback=proof.inputs.sourceFiles.find(f=>f.path==='companies_job_watch_v2.json')!;
  const stages:Record<string,Row[]>={catalog_stage_companies:[],catalog_stage_sources:[],catalog_stage_vacancies:[],catalog_stage_aliases:[]};
  const samePayload=(existing:Row|undefined,payload:Row) => existing!==undefined&&Object.entries(payload).every(([key,value])=>existing[key]===value);
  for (const c of companies) {
    const payload:Row={company_id:c.id,display_name:c.name,career_url:c.careerUrl,config_id:c.configId,tier:c.tier,priority:c.priority,membership:c.membership};
    if (!samePayload(old.data.catalog_company_current!.find(r=>r.company_id===c.id),payload)) stages.catalog_stage_companies!.push({...payload,run_id:run,origin_id:await origin(c.sourcePath,c.sourceSha256)});
  }
  for (const s of sources) {
    const identity=old.data.catalog_source_identity!.find(r=>r.id===s.id);
    if (identity&&(identity.company_id!==s.companyId||identity.source_key!==s.sourceKey)) throw Error('SOURCE_IDENTITY_CONFLICT');
    const payload:Row={source_id:s.id,company_id:s.companyId,ats_family:s.family,inventory_url:s.inventoryUrl,coverage:s.coverage,generated_at:s.generatedAt};
    if (!samePayload(old.data.catalog_source_current!.find(r=>r.source_id===s.id),payload)) stages.catalog_stage_sources!.push({...payload,run_id:run,source_key:s.sourceKey,origin_id:await origin(s.sourcePath,s.sourceSha256),coverage_origin_id:await origin(s.coveragePath,s.coverageSha256)});
  }
  const jobMap=new Map(selected.ledger.mappings.map(m=>[m.key,m.jobId]));
  for (const entry of selected.catalog) {
    const j=jobs.find(j=>jobMap.get(j.jobKey)===entry.jobId)!;
    const payload:Row={job_id:entry.jobId,company_id:j.companyId,source_id:j.sourceId,kind:entry.kind,lifecycle:j.lifecycle,title:j.title,location:j.location,canonical_url:j.canonicalUrl,apply_url:j.applyUrl,fingerprint:j.fingerprint,batch:j.batch,first_seen_at:j.firstSeenAt,last_seen_at:j.lastSeenAt,worker_eligible:bool(j.workerEligible),technical_status:j.technicalStatus,needs_analysis:bool(j.needsAnalysis)};
    if (!samePayload(old.data.catalog_vacancy_current!.find(r=>r.job_id===entry.jobId),payload)) stages.catalog_stage_vacancies!.push({...payload,run_id:run,operation:'UPSERT',origin_job_key:selected.ledger.identities.find(i=>i.jobId===entry.jobId)!.originJobKey,origin_id:await origin(j.sourcePath,j.sourceSha256)});
  }
  const newIdentities=selected.ledger.identities.filter(i=>!old.ledger.identities.some(p=>p.jobId===i.jobId));
  const newAliases=selected.ledger.mappings.filter(i=>!old.ledger.mappings.some(p=>p.key===i.key));
  const removed=old.data.catalog_vacancy_current!.filter(v=>!selected.catalog.some(c=>c.jobId===v.job_id));
  for (const id of new Set([...newIdentities.map(i=>i.jobId),...newAliases.map(a=>a.jobId),...removed.map(r=>String(r.job_id))])) {
    if (stages.catalog_stage_vacancies!.some(s=>s.job_id===id)) continue;
    const i=selected.ledger.identities.find(i=>i.jobId===id)!;
    stages.catalog_stage_vacancies!.push({run_id:run,job_id:id,company_id:i.companyId,origin_job_key:i.originJobKey,operation:removed.some(r=>r.job_id===id)?'REMOVE':'IDENTIFY_ONLY',origin_id:await origin(fallback.path,fallback.sha256)});
  }
  for (const a of newAliases) stages.catalog_stage_aliases!.push({run_id:run,alias_key:a.key,job_id:a.jobId,resolution:legacy?.aliasResolutions[a.key]??(selected.ledger.identities.some(i=>i.originJobKey===a.key)?'EXACT_KEY':'PYTHON_RESOLVED')});
  steps.push(...insertMany('catalog_origins',originRows,'staging'));
  for (const [table,records] of Object.entries(stages)) steps.push(...insertMany(table,records,'staging'));
  const stageCount=Object.values(stages).reduce((n,r)=>n+r.length,0);
  steps.push({...insert('catalog_chunks',{run_id:run,chunk_index:0,chunk_digest:await sha256(canonical(stages)),row_count:stageCount}),phase:'staging'});
  // These assertions are in the same transaction; zero-row UPDATE is never a CAS.
  steps.push(statement('INSERT INTO catalog_import_assert VALUES (('+Object.entries(stages).map(([t,r])=>'(SELECT count(*) FROM '+t+' WHERE run_id=?)='+r.length).join(' AND ')+'))',Object.keys(stages).map(()=>run),{catalog_import_assert:2}));
  steps.push(statement("UPDATE catalog_runs SET state='READY' WHERE id=?",[run],{catalog_runs:2}));
  const companyIds=[...new Set([...companies.map(c=>c.id),...(legacy?.companies.map(c=>String(c.id))??[]),...selected.ledger.identities.map(i=>i.companyId)])]
    .filter(id=>!old.data.catalog_company_identity!.some(r=>r.id===id));
  steps.push(...insertMany('catalog_company_identity',companyIds.map(id=>({id})),'promotion'));
  const newSourceCount=sources.filter(s=>!old.data.catalog_source_identity!.some(r=>r.id===s.id)).length;
  if(newSourceCount)steps.push({...statement('INSERT INTO catalog_source_identity(id,company_id,source_key) SELECT source_id,company_id,source_key FROM catalog_stage_sources s WHERE run_id=? AND NOT EXISTS(SELECT 1 FROM catalog_source_identity i WHERE i.id=s.source_id)',[run],{catalog_source_identity:newSourceCount}),phase:'promotion'});
  const historicalSources=(legacy?.sources??[]).filter(s=>!sources.some(r=>r.id===s.id)&&!old.data.catalog_source_identity!.some(r=>r.id===s.id));
  steps.push(...insertMany('catalog_source_identity',historicalSources.map(s=>({id:s.id!,company_id:s.company_id!,source_key:s.source_key!})),'promotion'));
  if(newIdentities.length)steps.push({...statement('INSERT INTO catalog_vacancy_identity(id,company_id,origin_job_key) SELECT job_id,company_id,origin_job_key FROM catalog_stage_vacancies s WHERE run_id=? AND NOT EXISTS(SELECT 1 FROM catalog_vacancy_identity i WHERE i.id=s.job_id)',[run],{catalog_vacancy_identity:newIdentities.length}),phase:'promotion'});
  if(newAliases.length)steps.push({...statement('INSERT INTO catalog_aliases(alias_key,job_id,resolution) SELECT alias_key,job_id,resolution FROM catalog_stage_aliases WHERE run_id=?',[run],{catalog_aliases:newAliases.length}),phase:'promotion'});
  const applyStage=(stage:string,current:string,exclude:string[]) => {
    const records=stages[stage]!.filter(r=>!r.operation||r.operation==='UPSERT');
    if(!records.length)return;
    const cols=Object.keys(records[0]!).filter(c=>c!=='run_id'&&!exclude.includes(c)), key=cols[0]!;
    // Stage contains only changed payloads; IDENTIFY_ONLY and REMOVE never UPSERT.
    steps.push({...statement('INSERT INTO '+current+' ('+cols.join(',')+') SELECT '+cols.join(',')+' FROM '+stage+" WHERE run_id=?"+(stage==='catalog_stage_vacancies'?" AND operation='UPSERT'":'')+' ON CONFLICT('+key+') DO UPDATE SET '+cols.slice(1).map(c=>c+'=excluded.'+c).join(','),[run],{[current]:records.length*2}),phase:'promotion'});
  };
  applyStage('catalog_stage_companies','catalog_company_current',[]);
  applyStage('catalog_stage_sources','catalog_source_current',['source_key']);
  applyStage('catalog_stage_vacancies','catalog_vacancy_current',['operation','origin_job_key']);
  if(removed.length)steps.push({...statement("DELETE FROM catalog_vacancy_current WHERE job_id IN (SELECT job_id FROM catalog_stage_vacancies WHERE run_id=? AND operation='REMOVE')",[run],{catalog_vacancy_current:removed.length}),phase:'promotion'});
  for (const [table,key,ids] of [['catalog_source_current','source_id',sources.map(s=>s.id)],['catalog_company_current','company_id',companies.map(c=>c.id)]] as const) {
    const deleted=old.data[table]!.filter(r=>!ids.includes(String(r[key])));
    for(let offset=0;offset<deleted.length;offset+=maxParameters) {
      const part=deleted.slice(offset,offset+maxParameters);
      steps.push({...statement('DELETE FROM '+table+' WHERE '+key+' IN ('+part.map(()=>'?').join(',')+')',part.map(r=>r[key]!),{[table]:part.length}),phase:'promotion'});
    }
  }
  if (old.head) steps.push(statement("UPDATE catalog_head SET sync_revision=?,run_id=?,content_revision=?,ledger_revision=? WHERE scope='catalog'",[Number(old.head.sync_revision)+1,run,contentRevision,ledgerRevision],{catalog_head:2,catalog_runs:2,catalog_audit:1}));
  else steps.push(statement("INSERT INTO catalog_head VALUES ('catalog',1,?,?,?)",[run,contentRevision,ledgerRevision],{catalog_head:1,catalog_runs:2,catalog_audit:1}));
  return steps;
}

async function planPersonal(data:Record<string,Row[]>, selected:Selected, rows:Awaited<ReturnType<typeof verifyGitProjection>>['bundle']['chunks'][number], owner:string, commit:string, legacy?:Awaited<ReturnType<typeof v1Ledger>>) {
  const steps:Step[]=[], refIds=new Set(data.personal_job_refs!.filter(r=>r.owner_id===owner).map(r=>String(r.job_id)));
  if (!data.personal_owners!.some(r=>r.owner_id===owner)) steps.push(insert('personal_owners',{owner_id:owner}));
  for (const capture of legacy?.captures??[]) if (!refIds.has(String(capture.job_id))) {
    steps.push(insert('personal_job_refs',{owner_id:owner,...capture}));refIds.add(String(capture.job_id));
  }
  for (const e of legacy?.events??[]) {
    const existing=data[e.table]!.find(r=>r.owner_id===owner&&r.id===e.row.id);
    if(existing) { if(Object.entries(e.row).filter(([k])=>!['source_commit','source_path','source_sha256'].includes(k)).some(([k,v])=>existing[k]!==v))throw Error('V1_PERSONAL_FACT_CONFLICT'); }
    else steps.push(insert(e.table,{owner_id:owner,...e.row}));
  }
  const jobs=rows.filter(r=>r.kind==='job'), keys=new Map(selected.ledger.mappings.map(m=>[m.key,m.jobId]));
  const needed=new Set([...selected.subjects.filter(s=>s.personal).map(s=>s.jobId),...selected.reviews.map(r=>r.jobId)]);
  for (const id of needed) if (!refIds.has(id)) {
    const job=jobs.find(j=>keys.get(j.jobKey)===id);
    // An absent personal subject must already have a durable capture; don't invent one.
    if (!job) throw Error('PERSONAL_CAPTURE_REQUIRED');
    steps.push(insert('personal_job_refs',{owner_id:owner,job_id:id,captured_title:job.title,official_url:job.canonicalUrl??job.applyUrl,last_known_lifecycle:job.lifecycle,captured_commit:commit,captured_path:job.sourcePath,captured_sha256:job.sourceSha256,revision:1}));
    refIds.add(id);
  }
  for (const [events,table] of [[selected.decisions,'personal_decision_events'],[selected.reviews,'personal_assessment_events']] as const) for (const event of events) {
    const row=event.observations[0]!;
    const facts:Row=row.kind==='user'?{decision:row.decision,rejection_reason:row.rejectionReason,fingerprint:row.fingerprint,decided_at:row.decidedAt,result_sha256:row.resultSha256}:
      {fingerprint:row.fingerprint,method:row.method,decision:row.decision,fit_score:row.fitScore,reportable:bool(row.reportable),evidence_state:row.evidenceState,analyzed_at:row.analyzedAt,result_sha256:row.resultSha256};
    const planned=steps.find(s=>s.sql.startsWith('INSERT INTO '+table+' ')&&s.values.includes(event.eventId));
    if(planned) { const legacyFact=legacy!.events.find(e=>e.table===table&&e.row.id===event.eventId)!.row; if(Object.entries(facts).some(([k,v])=>legacyFact[k]!==v))throw Error('IMMUTABLE_PERSONAL_EVENT_CONFLICT'); continue; }
    const existing=data[table]!.find(e=>e.owner_id===owner&&(e.id===event.eventId||(e.job_id===event.jobId&&e.result_sha256===row.resultSha256)));
    if (existing) {
      if (existing.id!==event.eventId||existing.job_id!==event.jobId||Object.entries(facts).some(([k,v])=>existing[k]!==v)) throw Error('IMMUTABLE_PERSONAL_EVENT_CONFLICT');
    } else steps.push(insert(table,{owner_id:owner,id:event.eventId,job_id:event.jobId,...facts,source_commit:commit,source_path:row.sourcePath,source_sha256:row.sourceSha256}));
  }
  if (steps.length) {
    const head=data.personal_heads!.find(h=>h.owner_id===owner), revision=Number(head?.revision??0)+1;
    // This records append context only. Current event pointers and user reference
    // states are never reordered, fabricated or overwritten by refresh.
    const contextDigest=await sha256(canonical({previous:head?.context_digest??null,append:steps}));
    steps.push(head?statement('UPDATE personal_heads SET revision=?,context_digest=?,source_commit=? WHERE owner_id=?',[revision,contextDigest,commit,owner],{personal_heads:2}):insert('personal_heads',{owner_id:owner,revision,context_digest:contextDigest,source_commit:commit}));
    steps.push(insert('personal_audit',{id:'append:'+await sha256(canonical({owner,revision,contextDigest})),owner_id:owner,event_code:'GIT_FACTS_APPENDED',content_digest:contextDigest}));
    // Mark every retained capture for this owner PENDING; never delete its data.
    for (const id of refIds) steps.push(statement("INSERT INTO personal_reconciliation VALUES (?,?,?,'PENDING',NULL,NULL) ON CONFLICT(owner_id,job_id) DO UPDATE SET personal_revision=excluded.personal_revision,state='PENDING',receipt_id=NULL,error_code=NULL",[owner,id,revision],{personal_reconciliation:2}));
  }
  return steps;
}
async function reconcile(catalog:D1Database, personal:D1Database, receipt:Row, selected:Selected, owner:string) {
  const current=await trustedCatalog(catalog);
  if (current.head?.run_id!==String(receipt.id).slice('receipt:'.length)||current.head.sync_revision!==receipt.catalog_sync_revision) throw Error('RECONCILIATION_HEAD_CHANGED');
  const data=await read(personal,personalTables), steps:Step[]=[];
  requireSingleOwner(data,owner);
  const existingReceipt=data.personal_catalog_receipts!.find(r=>r.id===receipt.id);
  if(existingReceipt && canonical(existingReceipt)!==canonical(receipt))
    throw Error('RECONCILIATION_RECEIPT_CONFLICT');
  if (!existingReceipt) steps.push(insert('personal_catalog_receipts',receipt));
  for (const ref of data.personal_job_refs!) {
    const head=data.personal_heads!.find(h=>h.owner_id===ref.owner_id);
    if (!head || !selected.ledger.identities.some(i=>i.jobId===ref.job_id)) throw Error('UNRESOLVED_PERSONAL_REFERENCE');
    const existing=data.personal_reconciliation!.find(r=>r.owner_id===ref.owner_id&&r.job_id===ref.job_id);
    if (existing?.state==='VERIFIED'&&existing.receipt_id===receipt.id&&existing.personal_revision===head.revision) continue;
    steps.push(statement("INSERT INTO personal_reconciliation VALUES (?,?,?,'VERIFIED',?,NULL) ON CONFLICT(owner_id,job_id) DO UPDATE SET personal_revision=excluded.personal_revision,state='VERIFIED',receipt_id=excluded.receipt_id,error_code=NULL",[ref.owner_id!,ref.job_id!,head.revision!,receipt.id!],{personal_reconciliation:2}));
  }
  return execute(personal,steps.length?[...personalGuard(data),...steps]:[]);
}
const cleanupTables=['catalog_stage_aliases','catalog_stage_vacancies','catalog_stage_sources','catalog_stage_companies','catalog_chunks'];
function cleanupFor(run:string,publication:Step[]) {
  return cleanupTables.map(t=>statement('DELETE FROM '+t+' WHERE run_id=?',[run],{[t]:publication.reduce((n,s)=>n+(s.sql.startsWith('INSERT INTO '+t+' ')?s.writes[t]??0:0),0)}));
}
async function cleanupPlan(db:D1Database, run?:string) {
  const steps:Step[]=[];
  for (const t of cleanupTables) {
    const rows=(await db.prepare('SELECT s.run_id,count(*) AS n FROM '+t+" s JOIN catalog_runs r ON s.run_id=r.id WHERE r.state IN ('PUBLISHED','ABORTED')"+(run?' AND s.run_id=?':'')+' GROUP BY s.run_id').bind(...(run?[run]:[])).all<{run_id:string;n:number}>()).results;
    for (const r of rows) steps.push(statement('DELETE FROM '+t+' WHERE run_id=?',[r.run_id],{[t]:r.n}));
  }
  return steps;
}
