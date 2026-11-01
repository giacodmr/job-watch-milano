// M50 Stage 0. Detached Node/operator orchestration, not a Worker route.
// The authority is possession of the separately provisioned D1 handles plus
// independently verified pinned Git bytes, NEVER the service staging JWT.
// Local D1 only: remote binding/semantics and Gate B are not authorized here.
import {canonical} from '../shared/canonical';
import {importModelC,ModelCImportError} from './model-c-importer';
import type {ImportOptions} from './model-c-importer';
import {observeIngestJournal} from './model-c-publication-journal';
import {inspectPublishedModelCRecovery} from './model-c-import-recovery';
import {isM50AuthorizedRemotePair} from './model-c-m50-d1-rest';

type Stage=NonNullable<ImportOptions['stagedPublication']>;
export type M50LocalPublication={
 source:ImportOptions['source'];
 owner:string;
 stagedPublication:Stage;
 budget:ImportOptions['budget'];
 bootstrap?:ImportOptions['bootstrap'];
 v1?:ImportOptions['v1'];
 oneTimeFreeBootstrap?:boolean;
};
type Readback={
 journalPhase:string;
 personalStatus:string;
 pendingReferences:number|null;
 receiptMatchesPublishedHead:boolean;
};
const denied=(reason:string):never=>{throw Error(reason);};
const matchStage=async(catalog:D1Database,options:M50LocalPublication,
 preflight:Awaited<ReturnType<typeof importModelC>>)=>{
 const plan=options.stagedPublication.trustedPlan;
 if(preflight.status!=='PREFLIGHT')return;
 const published=await catalog.prepare("SELECT run_id FROM catalog_head WHERE scope='catalog'")
   .first<string>('run_id')===options.stagedPublication.runId;
 // Recovery after PERSONAL append may change the selection-context projection
 // digest. M47 replay checks the original immutable plan against published
 // CATALOG bytes; do not demand a freshly recomputed projection digest then.
 if(preflight.run!==options.stagedPublication.runId||
    plan.syncRevision!==preflight.syncRevision||
    plan.origin.observedCommit!==preflight.provenance.observedCommit||
    plan.origin.manifestDigest!==preflight.provenance.manifestDigest||
    (!published&&canonical(plan.origin)!==canonical(preflight.provenance)))
   denied('M50_TRUSTED_PREFLIGHT_MISMATCH');
};
async function readback(catalog:D1Database,personal:D1Database,runId:string,owner:string):
 Promise<Readback>{
 const journal=await observeIngestJournal(catalog,runId);
 const state=await inspectPublishedModelCRecovery(catalog,personal,{ownerId:owner});
 return {journalPhase:journal.phase,personalStatus:state.status,
   pendingReferences:'pendingReferences' in state?state.pendingReferences:null,
   receiptMatchesPublishedHead:'receiptMatchesPublishedHead' in state?
      state.receiptMatchesPublishedHead:false};
}
/** Prove one independent Git/Python -> verified staging -> PERSONAL -> atomic
 * CATALOG journal/CAS -> PERSONAL receipt chain on local D1. No HTTP service
 * principal is passed to this function; no generic SQL proxy is exposed.
 * Unknown post-write outcomes are read-only inspected and never retried here.
 */
export async function publishM50Locally(catalog:D1Database,personal:D1Database,
 options:M50LocalPublication){
 return publishWithOperator(catalog,personal,options,'local-ephemeral');
}
/** Explicit operator-only remote path: cannot be reached with a service JWT.
 * No implicit authorization, no live account discovery or provisioning.
 */
export async function publishM50WithRemoteOperator(catalog:D1Database,
 personal:D1Database,options:M50LocalPublication,capability:object){
 if(!isM50AuthorizedRemotePair(capability,catalog,personal,options.budget))
   denied('M50_REMOTE_OPERATOR_CAPABILITY_INVALID');
 if(options.oneTimeFreeBootstrap)
   denied('M50_REMOTE_INITIAL_BOOTSTRAP_NOT_AUTHORIZED');
 return publishWithOperator(catalog,personal,options,'remote',capability);
}
async function publishWithOperator(catalog:D1Database,personal:D1Database,
 options:M50LocalPublication,target:'local-ephemeral'|'remote',
 capability?:object){
 if(catalog===personal)denied('M50_DISTINCT_DATABASES_REQUIRED');
 if(!options.stagedPublication?.runId.startsWith('ingest-v2:'))
   denied('M50_V2_STAGED_RUN_REQUIRED');
 if(!/^[0-9a-f]{40}$/.test(options.source.commit))
   denied('M50_PINNED_COMMIT_REQUIRED');
 if(options.budget.availableRows>30000||options.budget.availableRows<0||
    !Number.isSafeInteger(options.budget.availableRows))
   denied('M50_INTERNAL_BUDGET_EXCEEDED');
 const args:ImportOptions={source:options.source,owner:options.owner,
   budget:options.budget,stagedPublication:options.stagedPublication,
   executionTarget:target,
   ...(capability?{remoteOperatorCapability:capability}:{}),
   ...(options.bootstrap?{bootstrap:options.bootstrap}:{}),
   ...(options.v1?{v1:options.v1}:{}),
   ...(options.oneTimeFreeBootstrap===undefined?{}:
    {oneTimeFreeBootstrap:options.oneTimeFreeBootstrap})};
 // Read-only importer preflight independently verifies origin/main ancestry,
 // Python exporter, manifest, identity ledger and projected stage packets.
 const preflight=await importModelC(catalog,personal,{...args,preflightOnly:true});
 await matchStage(catalog,options,preflight);
 if(preflight.status==='PREFLIGHT'&&
    preflight.metrics.requiredBound>options.budget.availableRows)
   denied('M50_WRITE_BUDGET_INSUFFICIENT');
 if(preflight.status!=='PREFLIGHT'&&preflight.status!=='REPLAY')
   denied('M50_PREFLIGHT_NOT_READY');
 if(preflight.status==='REPLAY'){
   const receipt=await readback(catalog,personal,options.stagedPublication.runId,options.owner);
   if(receipt.journalPhase!=='COMPLETED'||
      !receipt.receiptMatchesPublishedHead||receipt.pendingReferences!==0)
     denied('M50_REPLAY_RECEIPT_MISMATCH');
   return {status:'REPLAY' as const,runId:options.stagedPublication.runId,
     receipt,remoteExecutionAuthorized:target==='remote'};
 }
 try{
   const published=await importModelC(catalog,personal,args);
   const receipt=await readback(catalog,personal,options.stagedPublication.runId,options.owner);
   if((published.status!=='PUBLISHED'&&published.status!=='RECOVERED'&&
       published.status!=='REPLAY')||receipt.journalPhase!=='COMPLETED'||
      !receipt.receiptMatchesPublishedHead||receipt.pendingReferences!==0)
     denied('M50_LOCAL_PUBLICATION_UNVERIFIED');
   return {...published,runId:options.stagedPublication.runId,
     receipt,remoteExecutionAuthorized:target==='remote'};
 }catch(error){
   // Even if the CATALOG commit succeeded, an exception/ACK loss is not PASS.
   // Human/operator must first inspect immutable receipts and then explicitly
   // reinvoke a pinned-source controller; never blind-retry a write.
   let receipt:Readback|null=null;
   try{receipt=await readback(catalog,personal,options.stagedPublication.runId,options.owner);}
   catch{/* cannot establish outcome */}
   const failureCode=error instanceof ModelCImportError?error.message:
     error instanceof Error&&/^[A-Z][A-Z0-9_]+$/.test(error.message)?error.message:
       'M50_UNCERTAIN_OPERATOR_OUTCOME';
   return {status:'REQUIRES_OPERATOR_RECOVERY' as const,failureCode,
     runId:options.stagedPublication.runId,receipt,
     remoteExecutionAuthorized:target==='remote'};
 }
}
