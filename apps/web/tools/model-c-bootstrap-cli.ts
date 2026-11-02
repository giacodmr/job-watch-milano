// Local-only pinned Git preflight. Invoked via the temporary esbuild runner.
// D1 is always an isolated ephemeral Miniflare database; never touches Cloudflare.
import {resolve} from 'node:path';
import {Miniflare,convertV4MiniflareOptions} from 'miniflare';
import {applySchema} from './model-c-schema';
import {importModelC,previewModelCInitialSchedule} from './model-c-importer';

const blocked=['REMOTE_SEMANTICS_UNVERIFIED','REMOTE_QUOTA_UNVERIFIED',
  'REMOTE_EXECUTION_NOT_AUTHORIZED'] as const;
async function main(){
  if(process.argv.length!==4||process.argv[2]!=='--commit'||!/^[a-f0-9]{40}$/.test(process.argv[3]??'')){
    throw Error('EXPLICIT_COMMIT_SHA_REQUIRED');
  }
  const owner=process.env.JOB_WATCH_PRIVATE_OWNER_ID;
  if(!owner) {
    process.stdout.write(JSON.stringify({status:'REAL_DATA_PREFLIGHT_NOT_EXECUTED',
      reason:'OWNER_CONTEXT_NOT_AVAILABLE',remoteExecutionAuthorized:false,blockers:blocked})+'\n');
    return;
  }
  // Derive repository location from this generated runner living under tools/.
  const repo=resolve(import.meta.dirname,'../../..');
  const runtime=new Miniflare(convertV4MiniflareOptions({
    modules:true,script:'export default {fetch(){return new Response("offline")}}',
    compatibilityDate:'2026-10-29',cf:false,
    d1Databases:{CATALOG:'m45-bootstrap-catalog-ephemeral',PERSONAL:'m45-bootstrap-personal-ephemeral'},
  }));
  try{
    const catalog=await runtime.getD1Database('CATALOG');
    const personal=await runtime.getD1Database('PERSONAL');
    const setup={catalog:await applySchema(catalog,'catalog'),personal:await applySchema(personal,'personal')};
    const report=await importModelC(catalog,personal,{
      source:{repo,commit:process.argv[3]!},bootstrap:'empty-target',owner,
      oneTimeFreeBootstrap:true,preflightOnly:true,executionTarget:'remote',
      budget:{day:new Date().toISOString().slice(0,10),availableRows:95000},
    });
    if(report.status!=='PREFLIGHT')throw Error('UNEXPECTED_PREFLIGHT_STATE');
    const phased=await previewModelCInitialSchedule(catalog,personal,{
      source:{repo,commit:process.argv[3]!},bootstrap:'empty-target',owner,
      executionTarget:'local-ephemeral',
      budget:{day:new Date().toISOString().slice(0,10),availableRows:30000},
    });
    if(!phased.boundPerDayVerified)throw Error('PHASED_INITIAL_DAILY_BUDGET_EXCEEDED');
    // Numbers only: deterministic aggregate diagnostics, with no owner ID,
    // source contents, application decisions or SQL parameter values.
    const phaseBounds=report.metrics.writeBounds;
    const tableBounds=report.metrics.writeUnits;
    const phaseSum=Object.values(phaseBounds).reduce((total,bound)=>total+bound,0);
    const catalogTableSum=Object.values(tableBounds).reduce((total,entry)=>total+entry.bound,0);
    const catalogPhaseSum=['staging','promotion','checkpoint','cleanup']
      .reduce((total,phase)=>total+(phaseBounds[phase]??0),0);
    if(phaseSum!==report.metrics.requiredBound||catalogTableSum!==catalogPhaseSum)
      throw Error('MODEL_C_WRITE_BOUND_BREAKDOWN_INCONSISTENT');
    // The existing importer executes ALL catalog publication steps, including
    // its own staging, in one D1 batch. Charging v2 service ingestion separately
    // does not make these steps disappear from the final importer batch.
    const singleCatalogBatchBound=['staging','promotion','checkpoint']
      .reduce((total,phase)=>total+(phaseBounds[phase]??0),0);
    const ordinaryDailyWriteLimit=30000;
    const multiDayBootstrapAssessment=singleCatalogBatchBound>ordinaryDailyWriteLimit
      ? 'BLOCKED_CATALOG_ATOMIC_BATCH_OVER_ORDINARY_BUDGET'
      : 'ADDITIONAL_REMOTE_PATH_VERIFICATION_REQUIRED';
    process.stdout.write(JSON.stringify({
      status:'LOCAL_PLAN_VALID',source:'PINNED_GIT_OFFLINE_PROJECTION',
      observedCommit:report.provenance.observedCommit,
      manifestDigest:report.provenance.manifestDigest,
      projectionDigest:report.provenance.projectionDigest,
      schemaSetupLocalRowsWritten:{catalog:setup.catalog.rowsWritten,personal:setup.personal.rowsWritten},
      migrationFiles:{catalog:setup.catalog.applied,personal:setup.personal.applied},
      // Local D1 setup writes are NOT a trustworthy remote upper bound.
      remoteMigrationUpperBound:null,
      importWriteUpperBound:report.metrics.requiredBound,
      writeBoundsByPhase:phaseBounds,
      catalogWriteBoundsByTable:tableBounds,
      catalogSingleBatchBound:singleCatalogBatchBound,
      catalogAtomicBatchBudgetLimit:ordinaryDailyWriteLimit,
      multiDayBootstrapAssessment,
      phasedInitialSchedule:phased,
      publicationStatements:report.metrics.publicationStatements,
      publicationBytes:report.metrics.publicationBytes,
      maxStatementSqlBytes:report.metrics.maxStatementSqlBytes,
      maxStatementParameters:report.metrics.maxStatementParameters,
      remoteExecutionAuthorized:false,blockers:blocked,
    })+'\n');
  }finally{await runtime.dispose();}
}
await main().catch(error=>{
  const m=error instanceof Error?error.message:'';
  const code=/^[A-Z][A-Z0-9_]+$/.test(m)?m:'PINNED_BOOTSTRAP_PREFLIGHT_FAILED';
  process.stderr.write(JSON.stringify({error:code,remoteExecutionAuthorized:false})+'\n');
  process.exitCode=1;
});
