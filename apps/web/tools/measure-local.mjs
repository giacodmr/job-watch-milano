// Local-only benchmark. Fresh ephemeral D1; stdout contains aggregates, no records.
import { readFile, readdir, stat } from 'node:fs/promises';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseArgs } from 'node:util';
import { execFileSync } from 'node:child_process';
import { performance } from 'node:perf_hooks';
import { build } from 'esbuild';
import { convertV4MiniflareOptions, Miniflare } from 'miniflare';
const app = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const repo = resolve(app, '../..');
const versionKinds = { company_versions:'company', source_versions:'source', job_versions:'job' };
let runtime;

async function load(path) {
  const built = await build({ entryPoints:[resolve(app,path)],bundle:true,write:false,format:'esm',platform:'node' });
  return import('data:text/javascript;base64,'+Buffer.from(built.outputFiles[0].text).toString('base64'));
}
function instrument(raw,classifications = new Map()) {
  const statements = new WeakMap(), byTarget = {};
  function track(info,result) {
    const target = info.sql.match(/^\s*(?:INSERT(?: OR \w+)? INTO|UPDATE|DELETE FROM)\s+(\w+)/i)?.[1] || 'reads';
    const totals = byTarget[target] ||= { statements:0,rowsRead:0,rowsWritten:0,exactUnchangedVersionWrites:0,provenanceOnlyVersionWrites:0 };
    totals.statements++;totals.rowsRead+=result.meta.rows_read??0;totals.rowsWritten+=result.meta.rows_written??0;
    const kind=versionKinds[target];
    if (kind) {
      const columns=info.sql.match(/INSERT INTO \w+\(([^)]+)\)/i)?.[1].split(',').map(name=>name.trim());
      const index=columns?.indexOf({company:'company_id',source:'source_id',job:'job_key'}[kind])??-1;
      const group=index<0 ? null : classifications.get(kind+'\0'+info.values[index]);
      if (group==='exact') totals.exactUnchangedVersionWrites+=result.meta.rows_written??0;
      if (group==='provenance-only') totals.provenanceOnlyVersionWrites+=result.meta.rows_written??0;
    }
  }
  function wrap(inner,sql,bound=[]) {
    const info={inner,sql,values:bound};
    const statement={
      bind:(...args)=>wrap(inner.bind(...args),sql,args),
      all:async()=>{const result=await inner.all();track(info,result);return result;},
      run:async()=>{const result=await inner.run();track(info,result);return result;},
    };
    statements.set(statement,info);return statement;
  }
  return {byTarget,db:{
    prepare:sql=>wrap(raw.prepare(sql),sql),
    batch:async prepared=>{
      const info=prepared.map(statement=>statements.get(statement));
      const results=await raw.batch(info.map(statement=>statement.inner));
      results.forEach((result,index)=>track(info[index],result));return results;
    },
  }};
}
try {
  const {values}=parseArgs({options:{file:{type:'string'},next:{type:'string'},'same-files':{type:'string'}}});
  if (values['same-files']&&!values.next) throw new Error('NEXT_REQUIRED');
  const {validateBundle}=await load('shared/snapshot.ts');
  const {canonical}=await load('shared/canonical.ts');
  const {compareRows}=await load('tools/measure-rows.ts');
  const files=[values.file||resolve(app,'.local-sync/snapshot.json'),values.next,values['same-files']].filter(Boolean);
  const bundles=[];
  for (const file of files) {
    if ((await stat(file)).size>32*1024*1024) throw new Error('BUNDLE_TOO_LARGE');
    const bundle=await validateBundle(JSON.parse(await readFile(file,'utf8')));
    execFileSync('git',['-C',repo,'merge-base','--is-ancestor',bundle.manifest.commitSha,'origin/main'],{stdio:'pipe'});
    bundles.push(bundle);
  }
  const {importSnapshot}=await load('worker/data/importer.ts');
  runtime=new Miniflare(convertV4MiniflareOptions({modules:true,
    script:'export default {fetch(){return new Response("local")}}',cf:false,
    compatibilityDate:'2026-10-29',d1Databases:{DB:'measurement'},
  }));
  const db=await runtime.getD1Database('DB');
  for (const migration of (await readdir(resolve(app,'migrations'))).filter(file=>file.endsWith('.sql')).sort()) {
    for (const sql of (await readFile(resolve(app,'migrations',migration),'utf8')).split('-- statement-breakpoint'))
      if (sql.trim()) await db.prepare(sql).run();
  }
  const verifyAdvance=async(before,after)=>{
    try {execFileSync('git',['-C',repo,'merge-base','--is-ancestor',before,after],{stdio:'pipe'});return true;}
    catch {return false;}
  };
  let revision=0;
  async function measure(label,input,diff=null) {
    const observed=instrument(db,diff?.classifications);
    const cpu=process.cpuUsage(),wall=performance.now();
    const result=await importSnapshot(observed.db,input,{expectedRevision:revision,verifyAdvance,maxRowsWritten:500000});
    revision=result.revision;
    const used=process.cpuUsage(cpu);
    if (Object.values(observed.byTarget).reduce((sum,value)=>sum+value.rowsWritten,0)!==result.rowsWritten)
      throw new Error('MEASUREMENT_METRICS_MISMATCH');
    console.log(JSON.stringify({phase:label,commit:input.manifest.commitSha,...result,
      elapsedIncludingValidationMs:Math.round(performance.now()-wall),processCpuMs:(used.user+used.system)/1000,
      statementsByTarget:observed.byTarget,...(diff?{rowComparison:diff.counts}:{}),
    }));
  }
  await measure('initial',bundles[0]);
  await measure('replay-initial',bundles[0]);
  for (let index=1;index<bundles.length;index++) {
    const before=bundles[index-1],next=bundles[index];
    const sameFiles=canonical(before.manifest.files)===canonical(next.manifest.files);
    if (index===2&&!sameFiles) throw new Error('SOURCE_FILES_NOT_IDENTICAL');
    await measure(index===1?'new-commit':'new-commit-same-files',next,compareRows(before,next,canonical));
    console.log(JSON.stringify({phase:'source-comparison',sameFiles,beforeCommit:before.manifest.commitSha,afterCommit:next.manifest.commitSha}));
    await measure(index===1?'replay-new-commit':'replay-same-files-commit',next);
  }
  console.log(JSON.stringify({status:'MEASURED',persistentDatabase:false,productionAccess:false,migrationsIncluded:false,
    cpuScope:'Node process only; excludes workerd child CPU; not remote Worker CPU',
    rewriteDefinition:'Version INSERT meta.rows_written including indexes; exact or same payload excluding provenance; timestamps retained',
  }));
} catch(error) {
  console.error(JSON.stringify({error:/^[A-Z][A-Z0-9_]+$/.test(error?.message||'')?error.message:'LOCAL_MEASUREMENT_FAILED',productionAccess:false}));
  process.exitCode=1;
} finally {await runtime?.dispose();}
