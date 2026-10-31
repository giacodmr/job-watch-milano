// Repository-only Gate A preflight. No Cloudflare client, no credentials,
// network, Wrangler deploy, D1 operations or account attestation.
import {readFile,readdir} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {dirname,resolve} from 'node:path';
import {fileURLToPath} from 'node:url';

const root=resolve(dirname(fileURLToPath(import.meta.url)),'..');
const read=path=>readFile(resolve(root,path),'utf8');
const sha256=value=>createHash('sha256').update(value).digest('hex');
function parseJsonc(raw){
  // These repository-owned Wrangler files contain comments/trailing commas,
  // not remotely supplied text. Never parse an arbitrary external input.
  return JSON.parse(raw.replace(/^\s*\/\/.*$/gm,'').replace(/\s+\/\/.*$/gm,'').replace(/,\s*([}\]])/g,'$1'));
}
function ensure(value,reason,errors){if(!value)errors.push(reason);}
export async function inspectPrivateRepositoryGate(){
  const errors=[];
  const privateConfig=parseJsonc(await read('wrangler.private.template.jsonc'));
  const localConfig=parseJsonc(await read('wrangler.jsonc'));
  ensure(privateConfig.vars?.APP_ENV==='private','PRIVATE_ENV_NOT_ENFORCED',errors);
  ensure(privateConfig.workers_dev===false,'WORKERS_DEV_NOT_DISABLED',errors);
  ensure(privateConfig.preview_urls===false,'PREVIEWS_NOT_DISABLED',errors);
  ensure(privateConfig.assets?.run_worker_first===true,'STATIC_ASSETS_BYPASS',errors);
  ensure(privateConfig.assets?.binding==='ASSETS','ASSET_BINDING_MISSING',errors);
  ensure(privateConfig.assets?.not_found_handling==='single-page-application','SPA_ROUTING_UNVERIFIED',errors);
  ensure(privateConfig.send_metrics===false,'METRICS_NOT_DISABLED',errors);
  ensure(privateConfig.observability?.enabled===false,'LOGGING_NOT_DISABLED',errors);
  ensure(privateConfig.d1_databases===undefined && privateConfig.kv_namespaces===undefined,
    'TEMPLATE_CONTAINS_REMOTE_BINDINGS',errors);
  ensure(privateConfig.routes===undefined && privateConfig.route===undefined,
    'TEMPLATE_EXPOSES_UNPROTECTED_HOST',errors);
  ensure(privateConfig.account_id===undefined,'TEMPLATE_CONTAINS_ACCOUNT_ID',errors);
  ensure(Object.keys(privateConfig.vars??{}).length===1,'TEMPLATE_CONTAINS_IDENTITY_OR_SECRETS',errors);
  ensure(localConfig.vars?.APP_ENV==='local' && localConfig.workers_dev===false,
    'LOCAL_CONFIG_CHANGED',errors);
  ensure((localConfig.d1_databases??[]).every(db=>db.remote===false),
    'LOCAL_CONFIG_HAS_REMOTE_D1',errors);
  const migrations=[];
  for(const [scope,expected] of [['catalog',4],['personal',3]]){
    const dir='model-c/'+scope+'/migrations';
    const names=(await readdir(resolve(root,dir))).filter(n=>n.endsWith('.sql')).sort();
    ensure(names.length===expected,'UNEXPECTED_'+scope.toUpperCase()+'_SCHEMA_VERSION',errors);
    names.forEach((name,index)=>ensure(name.startsWith(String(index+1).padStart(4,'0')+'_'),
      'INVALID_'+scope.toUpperCase()+'_MIGRATION_ORDER',errors));
    for(const name of names){
      const sql=await read(dir+'/'+name);
      ensure(sql.trim().length>0,'EMPTY_'+scope.toUpperCase()+'_MIGRATION',errors);
      migrations.push({scope,name,sha256:sha256(sql)});
    }
  }
  return {
    gate:'A',repositoryPreflight:errors.length?'FAILED':'PASSED',
    activation:'BLOCKED_FOR_ACTIVATION',
    cloudAccountVerified:false,cloudMutationsAuthorized:false,
    remoteImporterAuthorized:false,
    expectedSchemaVersions:{catalog:4,personal:3},
    migrations,errors,
    externalBlockers:[
      'CLOUDFLARE_ACCOUNT_AND_PLAN_UNVERIFIED',
      'DOMAIN_AND_ACCESS_NOT_APPROVED',
      'D1_AND_ACCOUNT_WIDE_QUOTA_UNVERIFIED',
      'REAL_OWNER_AND_PROVENANCE_UNVERIFIED',
      'REMOTE_BOOTSTRAP_TRANSPORT_NOT_AUTHORIZED',
      'RECOVERY_AND_LIVE_SMOKE_UNVERIFIED',
      'GATE_B_APPROVAL_NOT_GRANTED'
    ]
  };
}
if(process.argv[1] && resolve(process.argv[1])===fileURLToPath(import.meta.url)){
  try {
    const result=await inspectPrivateRepositoryGate();
    process.stdout.write(JSON.stringify(result,null,2)+'\n');
    if(result.errors.length)process.exitCode=1;
  }catch{
    // Avoid dumping any sensitive file content or shell environment.
    process.stderr.write('PRIVATE_REPOSITORY_PREFLIGHT_FAILED\n');
    process.exitCode=1;
  }
}
