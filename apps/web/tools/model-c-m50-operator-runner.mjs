// Local Mac operator CLI only. Bundles the pinned TypeScript in node_modules/
// so the trusted Git adapter's implementation-file hash remains stable.
import {build} from 'esbuild';
import {randomUUID} from 'node:crypto';
import {rm} from 'node:fs/promises';
import {dirname,resolve} from 'node:path';
import {pathToFileURL,fileURLToPath} from 'node:url';

const dir=dirname(fileURLToPath(import.meta.url));
const output=resolve(dir,'../node_modules','.m50-operator-'+randomUUID()+'.mjs');
try{
 await build({entryPoints:[resolve(dir,'model-c-m50-operator-cli.ts')],
   outfile:output,bundle:true,platform:'node',format:'esm',target:'node24',
   external:['miniflare'],logLevel:'silent'});
 await import(pathToFileURL(output).href);
}catch{
 process.stderr.write(JSON.stringify({error:'M50_OPERATOR_RUNNER_FAILED'})+'\n');
 process.exitCode=1;
}finally{await rm(output,{force:true});}
