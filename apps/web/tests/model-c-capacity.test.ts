import { afterAll, beforeAll, expect, it } from 'vitest';
import { writeFile } from 'node:fs/promises';
import { getHeapStatistics } from 'node:v8';
import { Miniflare, convertV4MiniflareOptions } from 'miniflare';

let runtime:Miniflare, db:D1Database;
const report:Record<string,unknown>={syntheticOnly:true,scope:'Pinned local Miniflare/workerd D1 probes; not remote limits or Worker memory certification'};
beforeAll(async()=>{
  runtime=new Miniflare(convertV4MiniflareOptions({modules:true,script:'export default {fetch(){return new Response("synthetic")}}',cf:false,compatibilityDate:'2026-10-29',d1Databases:{DB:'capacity-limits'}}));
  db=await runtime.getD1Database('DB');
});
afterAll(async()=>{
  await runtime?.dispose();
  if(process.env.MODEL_C_RUNTIME_METRICS_FILE)await writeFile(process.env.MODEL_C_RUNTIME_METRICS_FILE,JSON.stringify(report,null,2)+'\n');
});
async function accepted(operation:()=>Promise<unknown>) {try{await operation();return true;}catch{return false;}}

it('probes actual parameter and single-statement byte boundaries without weakening importer limits',async()=>{
  const parameters:Record<string,boolean>={}, sqlBytes:Record<string,boolean>={};
  for(const n of [80,100,101])parameters[n]=await accepted(()=>db.prepare('SELECT ?1 + ?'+n+' AS n').bind(...Array(n).fill(1)).all());
  for(const n of [65536,100000,100001]) {
    const prefix='SELECT 1 AS n /*', suffix='*/', sql=prefix+'x'.repeat(n-prefix.length-suffix.length)+suffix;
    expect(Buffer.byteLength(sql)).toBe(n);sqlBytes[n]=await accepted(()=>db.prepare(sql).all());
  }
  report.parametersAccepted=parameters;report.sqlBytesAccepted=sqlBytes;
  expect(parameters).toEqual({'80':true,'100':true,'101':false});
  expect(sqlBytes).toEqual({'65536':true,'100000':true,'100001':false});
  report.sqliteVersion='Not exposed: local D1 authorizer rejects sqlite_version()';
  report.importerCaps={parameters:80,sqlBytes:65536,batchStatements:8000,serializedPlanBytes:8388608};
});

it('executes an 8000-statement read batch and records local process memory separately',async()=>{
  const before=process.memoryUsage(), start=performance.now();
  const results=await db.batch<{n:number}>(Array.from({length:8000},()=>db.prepare('SELECT 1 AS n')));
  expect(results).toHaveLength(8000);expect(results.every(r=>r.results[0]?.n===1)).toBe(true);
  expect(results.reduce((n,r)=>n+(r.meta.rows_written??0),0)).toBe(0);
  const after=process.memoryUsage();
  report.readBatch={statements:8000,accepted:true,rowsWritten:0,elapsedMs:performance.now()-start};
  report.nodeProcessMemory={before,after,heapLimitBytes:getHeapStatistics().heap_size_limit,scope:'Node snapshots include shared test/runtime overhead; workerd child memory and remote Worker peak are not measured'};
},60000);
