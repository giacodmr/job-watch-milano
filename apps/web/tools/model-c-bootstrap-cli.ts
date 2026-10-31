// Local-only pinned Git preflight. Invoked via the temporary esbuild runner.
// D1 is always an isolated ephemeral Miniflare database; never touches Cloudflare.
import {resolve} from 'node:path';
import {Miniflare,convertV4MiniflareOptions} from 'miniflare';
import {applySchema} from './model-c-schema';
import {importModelC} from './model-c-importer';

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
      publicationStatements:report.metrics.publicationStatements,
      publicationBytes:report.metrics.publicationBytes,
      maxStatementSqlBytes:report.metrics.maxStatementSqlBytes,
      maxStatementParameters:report.metrics.maxStatementParameters,
      remoteExecutionAuthorized:false,blockers:blocked,
    })+'\n');
  }finally{await runtime.dispose();}
}
main().catch(error=>{
  const m=error instanceof Error?error.message:'';
  const code=/^[A-Z][A-Z0-9_]+$/.test(m)?m:'PINNED_BOOTSTRAP_PREFLIGHT_FAILED';
  process.stderr.write(JSON.stringify({error:code,remoteExecutionAuthorized:false})+'\n');
  process.exitCode=1;
});
