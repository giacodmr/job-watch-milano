// A closed, synthetic-only laboratory. No database, config or input path options.
import { mkdtemp,writeFile,readFile,stat,rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { resolve,dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { build } from 'esbuild';
import { Miniflare,convertV4MiniflareOptions } from 'miniflare';
const app=resolve(dirname(fileURLToPath(import.meta.url)),'..');
async function load(path){const b=await build({entryPoints:[resolve(app,path)],bundle:true,write:false,platform:'node',format:'esm',define:{'import.meta.dirname':JSON.stringify(resolve(app,'tools'))}});return import('data:text/javascript;base64,'+Buffer.from(b.outputFiles[0].text).toString('base64'));}
let runtime,temp;
try {
  if(process.argv.length!==2)throw Error('SYNTHETIC_LAB_TAKES_NO_INPUTS');
  const {applySchema,captureSynthetic,restoreSynthetic}=await load('tools/model-c-schema.ts');
  const {stageCatalog,publicationFixture,seedPersonal,seedV1}=await load('tests/helpers/model-c-fixtures.ts');
  runtime=new Miniflare(convertV4MiniflareOptions({modules:true,script:'export default {fetch(){return new Response("synthetic-only")}}',cf:false,compatibilityDate:'2026-10-29',
    d1Databases:Object.fromEntries(['catalog','personal','v1'].flatMap(s=>[[s,'lab-'+s],['restore_'+s,'lab-restore-'+s]]))}));
  temp=await mkdtemp(resolve(tmpdir(),'model-c-synthetic-backup-'));
  if(((await stat(temp)).mode&0o777)!==0o700)throw Error('BACKUP_DIRECTORY_PERMISSIONS_INVALID');
  const scopes=[];
  for(const scope of ['catalog','personal','v1']) {
    const db=await runtime.getD1Database(scope), schema=await applySchema(db,scope), replay=await applySchema(db,scope);
    if(scope==='catalog'){await stageCatalog(db);await db.batch(publicationFixture(db,'run-one'));}
    else if(scope==='personal')await seedPersonal(db);else await seedV1(db);
    const backup=await captureSynthetic(db,scope), file=resolve(temp,scope+'.json');
    await writeFile(file,JSON.stringify(backup),{mode:0o600});
    if(((await stat(file)).mode&0o777)!==0o600)throw Error('BACKUP_PERMISSIONS_INVALID');
    const target=await runtime.getD1Database('restore_'+scope);
    const restored=await restoreSynthetic(target,scope,JSON.parse(await readFile(file,'utf8')));
    scopes.push({scope,schema,replay,backupDigest:backup.sha256,backupRows:backup.data.tables.reduce((n,t)=>n+t.rows.length,0),restored,fileMode:'0600'});
  }
  await runtime.dispose();runtime=undefined;await rm(temp,{recursive:true,force:true});temp=undefined;
  console.log(JSON.stringify({status:'SYNTHETIC_SCHEMA_RESTORE_VERIFIED',ephemeralOnly:true,persistentDatabaseTouched:false,productionAccess:false,backupDirectoryMode:'0700',backupsRemoved:true,scopes,
    measurement:'D1 meta.rows_written for empty-schema setup and synthetic restore only; excludes fixture seed and reads; no Model C bootstrap/daily cost claim'}));
} catch(e){console.error(JSON.stringify({error:/^[A-Z][A-Z0-9_]+$/.test(e?.message||'')?e.message:'MODEL_C_LAB_FAILED',productionAccess:false}));process.exitCode=1;}
finally {await runtime?.dispose();if(temp)await rm(temp,{recursive:true,force:true});}
