// Private Mac-side operator command for a pinned, multi-day initial import.
// This is NEVER a Worker route and does not print credentials, owner or records.
// Requires a separately provisioned D1 write token and explicit account-wide
// Free quota attestation in environment variables, refreshed for every run.
import {readFile,writeFile} from 'node:fs/promises';
import {resolve,sep} from 'node:path';
import {canonical,sha256} from '../shared/canonical';
import {verifyGitProjection} from './model-c-git';
import {selectModelC} from '../shared/model-c-selection';
import type {SelectionContext} from '../shared/model-c-selection';
import {prepareCatalogV2Packets} from '../shared/model-c-ingestion-v2';
import {importModelC,prepareModelCInitialChunk,cleanupModelCInitial} from './model-c-importer';
import type {ImportOptions} from './model-c-importer';
import {prepareSafeRemoteBootstrapPlan} from './model-c-remote-plan';
import {createM50RemoteOperatorPair} from './model-c-m50-d1-rest';
import {stageM50InitialV2WithOperator} from './model-c-m50-operator-stage';
import {publishM50WithRemoteOperator} from './model-c-m50-trusted-controller';

type Plan=Awaited<ReturnType<typeof prepareSafeRemoteBootstrapPlan>>;
const deny=(s:string):never=>{throw Error(s);};
const phase=process.argv[2];
const sha=process.argv[3];
const day=new Date().toISOString().slice(0,10);
const repo=resolve(import.meta.dirname,'../../..');
const owner=process.env.JOB_WATCH_PRIVATE_OWNER_ID;
const file=process.env.JOB_WATCH_INITIAL_PLAN_FILE;
const safe=async()=>{
 if(!['plan','stage','prepare','publish','cleanup'].includes(phase??'')||
   !/^[a-f0-9]{40}$/.test(sha??'')||!owner||owner.length>200||
   !file||!file.startsWith('/')||
   resolve(file).startsWith(repo+sep))
   deny('M50_OPERATOR_COMMAND_INVALID');
 if(process.env.JOB_WATCH_IMPORT_REMOTE_GATE_B!=='approved'||
   process.env.JOB_WATCH_FREE_PLAN_CONFIRMED!=='true'||
   process.env.JOB_WATCH_ACCOUNT_QUOTA_VERIFIED!=='true'||
   process.env.JOB_WATCH_REST_ATOMICITY_VERIFIED!=='true')
   deny('M50_OPERATOR_ACTIVATION_GATE_CLOSED');
 const available=Number(process.env.JOB_WATCH_TODAY_WRITE_BUDGET);
 if(!Number.isSafeInteger(available)||available<1||available>30000)
   deny('M50_OPERATOR_DAILY_BUDGET_INVALID');
 const token=process.env.CLOUDFLARE_API_TOKEN;
 const accountId=process.env.CLOUDFLARE_ACCOUNT_ID;
 const catalogDatabaseId=process.env.JOB_WATCH_CATALOG_D1_ID;
 const personalDatabaseId=process.env.JOB_WATCH_PERSONAL_D1_ID;
 if(!token||!accountId||!catalogDatabaseId||!personalDatabaseId)
   deny('M50_OPERATOR_CREDENTIALS_MISSING');
 const {catalog,personal,capability}=createM50RemoteOperatorPair({
   accountId,catalogDatabaseId,personalDatabaseId,apiToken:token,
   gateBApproved:true,accountFreePlanVerified:true,operatorQuotaVerified:true,
   remainingWriteUnits:available,quotaDay:day,
   validUntil:new Date(Date.now()+240000).toISOString(),
   initialBootstrapApproved:true,remoteBatchSemanticsVerified:true,
 });
 const source={repo,commit:sha!},budget={day,availableRows:available};
 const print=(v:unknown)=>process.stdout.write(JSON.stringify(v)+'\n');
 if(phase==='cleanup'){
   const runId=process.env.JOB_WATCH_BOOTSTRAP_RUN_ID;
   if(!runId||!/^ingest-v2:[a-f0-9]{64}$/.test(runId))
     deny('M50_OPERATOR_RUN_ID_REQUIRED');
   const result=await cleanupModelCInitial(catalog,{
     run:runId,budget,executionTarget:'remote',personal,
     remoteOperatorCapability:capability,
   });
   print({phase,runId,status:result.status,charged:result.charged??0,day});
   return;
 }
 const owners=(await personal.prepare('SELECT owner_id FROM personal_owners').all<{owner_id:string}>()).results;
 if(owners.some(x=>x.owner_id!==owner))deny('M50_OPERATOR_FOREIGN_OWNER');
 const refs=(await personal.prepare(
   'SELECT job_id,kind FROM personal_reference_state WHERE active=1 ORDER BY job_id,kind'
 ).all<{job_id:string;kind:string}>()).results;
 const decisions=(await personal.prepare(
   'SELECT DISTINCT job_id FROM personal_decision_events ORDER BY job_id'
 ).all<{job_id:string}>()).results;
 if(refs.some(x=>!['SAVED','APPLICATION','DISMISSED'].includes(x.kind)))
   deny('M50_OPERATOR_PERSONAL_REFERENCE_INVALID');
 const context:SelectionContext={identities:{mode:'first-v1-bootstrap'},
   personalReferences:refs.map(x=>({jobId:x.job_id,kind:x.kind as 'SAVED'|'APPLICATION'|'DISMISSED'})),
   personalDecisionJobIds:decisions.map(x=>x.job_id)};
 const {bundle,proof}=await verifyGitProjection(source,context);
 const selected=await selectModelC(bundle,context);
 let plan:Plan;
 if(phase==='plan'){
   // One-time legacy large preflight computes the same full projection, but
   // never admits the one-shot write. Store the immutable v2 plan privately.
   const preflight=await importModelC(catalog,personal,{
     source,owner,bootstrap:'empty-target',oneTimeFreeBootstrap:true,
     executionTarget:'remote',preflightOnly:true,
     budget:{day,availableRows:95000},
   });
   if(preflight.status!=='PREFLIGHT')deny('M50_OPERATOR_PREFLIGHT_NOT_READY');
   plan=await prepareSafeRemoteBootstrapPlan({
     status:preflight.status,provenance:preflight.provenance,
     budgetDay:preflight.budgetDay,priorLocalReservations:preflight.priorLocalReservations,
     remoteExecutionAuthorized:false,syncRevision:preflight.syncRevision,
     metrics:preflight.metrics,
   },{catalog:{migrationFiles:8,localRowsWritten:0,remoteUpperBound:0},
      personal:{migrationFiles:3,localRowsWritten:0,remoteUpperBound:0}});
   if(preflight.syncRevision!==1||
      plan.origin.projectionDigest!==proof.projectionInputDigest)
     deny('M50_OPERATOR_INITIAL_PLAN_CONFLICT');
   await writeFile(file!,JSON.stringify(plan),{flag:'wx',mode:0o600});
   print({phase,status:'PINNED_PLAN_SAVED',commit:sha,planDigest:plan.digest,
     selectedVacancies:selected.catalog.length,identityCount:selected.ledger.identities.length,
     aliasCount:selected.ledger.mappings.length,
     oneShotBound:preflight.metrics.requiredBound,remoteImportStarted:false});
   return;
 }
 const data=await readFile(file!,'utf8').catch(()=>deny('M50_OPERATOR_PLAN_MISSING'));
 plan=JSON.parse(data) as Plan;
 const {digest,...body}=plan;
 if(digest!==await sha256(canonical(body))||
    plan.target!=='OFFLINE_REVIEW_ONLY'||
    plan.mode!=='BOOTSTRAP_INITIAL'||
    plan.syncRevision!==1||
    plan.origin.observedCommit!==sha||
    plan.origin.manifestDigest!==proof.sourceManifestDigest||
    plan.origin.projectionDigest!==proof.projectionInputDigest)
   deny('M50_OPERATOR_PINNED_PLAN_MISMATCH');
 const packets=await prepareCatalogV2Packets(bundle,selected,proof,plan.digest,0);
 const opts:ImportOptions={source,owner,bootstrap:'empty-target',preparedInitial:true,
   executionTarget:'remote',remoteOperatorCapability:capability,budget,
   stagedPublication:{runId:packets.run.runId,trustedPlan:plan}};
 if(phase==='stage'){
   const maxChunks=Number(process.env.JOB_WATCH_STAGE_CHUNKS_PER_CALL??20);
   const result=await stageM50InitialV2WithOperator(
     catalog,personal,packets,capability,budget,maxChunks);
   print({phase,...result,day,planDigest:plan.digest});
   return;
 }
 if(phase==='prepare'){
   const result=await prepareModelCInitialChunk(catalog,personal,opts);
   print({phase,...result,planDigest:plan.digest});
   return;
 }
 if(phase==='publish'){
   const result=await publishM50WithRemoteOperator(catalog,personal,{
     source,owner,bootstrap:'empty-target',preparedInitial:true,
     stagedPublication:opts.stagedPublication!,budget,
   },capability);
   print({phase,status:result.status,runId:packets.run.runId,day,
     ...(result.status==='REQUIRES_OPERATOR_RECOVERY'
       ?{failureCode:result.failureCode,journalPhase:result.receipt?.journalPhase}
       :{journalPhase:'receipt' in result?result.receipt?.journalPhase:undefined})});
   return;
 }
 deny('M50_OPERATOR_UNKNOWN_PHASE');
};
await safe().catch(error=>{
 // No tokens, paths, payloads or SQL are ever returned in terminal diagnostics.
 const code=error instanceof Error&&/^[A-Z][A-Z0-9_]+$/.test(error.message)
  ?error.message:'M50_OPERATOR_EXECUTION_UNVERIFIED';
 process.stderr.write(JSON.stringify({phase,status:'FAILED',code})+'\n');
 process.exitCode=1;
});
