// Closed synthetic-only importer measurements. No input/database/config options.
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { spawnSync } from 'node:child_process';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { tmpdir } from 'node:os';
const app=resolve(dirname(fileURLToPath(import.meta.url)),'..');
let temp;
try {
  if(process.argv.length!==2)throw Error('SYNTHETIC_LAB_TAKES_NO_INPUTS');
  temp=await mkdtemp(resolve(tmpdir(),'model-c-import-metrics-'));
  const file=resolve(temp,'metrics.json'), runtimeFile=resolve(temp,'runtime.json');
  const result=spawnSync(process.execPath,[resolve(app,'node_modules/vitest/vitest.mjs'),'run','tests/model-c-importer.test.ts','tests/model-c-capacity.test.ts'],{cwd:app,encoding:'utf8',maxBuffer:4*1024*1024,env:{...process.env,MODEL_C_METRICS_FILE:file,MODEL_C_RUNTIME_METRICS_FILE:runtimeFile}});
  if(result.status!==0)throw Error('SYNTHETIC_IMPORT_TESTS_FAILED');
  const metrics=JSON.parse(await readFile(file,'utf8'));
  console.log(JSON.stringify({status:'SYNTHETIC_INCREMENTAL_IMPORT_VERIFIED',ephemeralOnly:true,productionAccess:false,...metrics,runtimeLimits:JSON.parse(await readFile(runtimeFile,'utf8'))}));
} catch(error) {
  console.error(JSON.stringify({error:/^[A-Z][A-Z0-9_]+$/.test(error?.message||'')?error.message:'MODEL_C_IMPORT_LAB_FAILED',productionAccess:false}));process.exitCode=1;
} finally {if(temp)await rm(temp,{recursive:true,force:true});}
