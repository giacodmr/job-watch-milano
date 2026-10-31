// A single local offline invocation. esbuild transiently transpiles the TS
// planner to the tools directory so the existing Git adapter resolves app root.
// The temporary file is unlinked in finally; no database/token/network client.
import {build} from 'esbuild';
import {randomUUID} from 'node:crypto';
import {rm} from 'node:fs/promises';
import {dirname,resolve} from 'node:path';
import {pathToFileURL,fileURLToPath} from 'node:url';

const toolsDir=dirname(fileURLToPath(import.meta.url));
const output=resolve(toolsDir,'.m45-local-'+randomUUID()+'.mjs');
try{
  await build({entryPoints:[resolve(toolsDir,'model-c-bootstrap-cli.ts')],
    outfile:output,bundle:true,platform:'node',format:'esm',target:'node24',
    external:['miniflare'],logLevel:'silent'});
  await import(pathToFileURL(output).href);
}catch{
  process.stderr.write(JSON.stringify({error:'LOCAL_BOOTSTRAP_RUNNER_FAILED',
    remoteExecutionAuthorized:false})+'\n');
  process.exitCode=1;
}finally{await rm(output,{force:true});}
