// M47 Gate A: traverse the entire deployable Worker static import graph.
// Independent of Vite's TypeScript compiler shims. Fail closed for any
// non-literal dynamic import/require rather than silently skipping modules.
import {describe,expect,it} from 'vitest';
import {existsSync,readFileSync} from 'node:fs';
import {dirname,relative,resolve} from 'node:path';

const root=resolve(import.meta.dirname,'..');
const entrypoints=['worker/index.ts','worker/private-runtime.ts'];
const forbidden=[
 'worker/model-c-ingest-v2-lab.ts',
 'worker/model-c-ingest-lab.ts',
 'tools/model-c-importer.ts',
 'tools/model-c-git.ts',
 'tools/model-c-v2-trusted-stage.ts',
 'tools/model-c-v2-stage-attestation.ts',
 'tools/model-c-v2-ingest-retention.ts',
 'tools/model-c-publication-journal.ts',
];
function importSpecifiers(body:string,file:string){
 // Detect standard TS/JS static imports and re-exports, including multiline
 // named imports, namespace imports, side-effect imports and type-only imports.
 // This is a deliberately restricted syntax scanner, not a general JS parser:
 // deny syntax that cannot be resolved to a literal path.
 const found:string[]=[];
 const staticRe=/\b(?:import|export)\s+(?:type\s+)?(?:[^;'"`]{0,4096}?\s+from\s+)?(['"])([^'"]+)\1/g;
 for(const match of body.matchAll(staticRe))found.push(match[2]!);
 // The explicit dynamic check prevents replacing a literal import with a
 // computed one to evade import-graph isolation.
 for(const match of body.matchAll(/\b(?:import|require)\s*\(([^)]*)\)/g)){
  const arg=match[1]!.trim();
  const literal=/^(['"])([^'"]+)\1$/.exec(arg);
  if(!literal)throw Error('NONSTATIC_WORKER_IMPORT:'+relative(root,file));
  found.push(literal[2]!);
 }
 // TS `import equals require` is denied until explicitly reviewed.
 if(/\bimport\s+\w+\s*=\s*require\s*\(/.test(body))
  throw Error('UNSUPPORTED_WORKER_IMPORT_SYNTAX:'+relative(root,file));
 return found.filter(spec=>spec.startsWith('.'));
}
function dependencies(file:string):string[]{
 const imports=importSpecifiers(readFileSync(file,'utf8'),file);
 return imports.map(spec=>{
  const stem=resolve(dirname(file),spec);
  const targets=[stem,stem+'.ts',stem+'.tsx',stem+'.js',
   resolve(stem,'index.ts'),resolve(stem,'index.tsx')];
  const target=targets.find(existsSync);
  if(!target)throw Error('UNRESOLVED_WORKER_IMPORT:'+relative(root,file)+':'+spec);
  if(!target.startsWith(root+'/'))throw Error('WORKER_IMPORT_OUTSIDE_ROOT:'+spec);
  return target;
 });
}
function reachable(entry:string){
 const visited=new Set<string>(),pending=[resolve(root,entry)];
 while(pending.length){
  const file=pending.pop()!;
  if(visited.has(file))continue;
  visited.add(file);
  pending.push(...dependencies(file));
 }
 return [...visited].map(file=>relative(root,file)).sort();
}
describe('M47 transitive deployable-worker isolation',()=>{
 it.each(entrypoints)('%s never imports Node-only v2 ingest or trusted promotion code',entry=>{
  const graph=reachable(entry);
  expect(graph.length).toBeGreaterThan(5);
  for(const module of forbidden)expect(graph,entry+' reached '+module).not.toContain(module);
  for(const file of graph){
   // M49 deployable service staging is the sole reviewed sync route exception.
   // Detached Node Git/trusted promotion/lab modules remain unreachable.
   if(file==='worker/model-c-ingest-v2-production.ts')continue;
   const body=readFileSync(resolve(root,file),'utf8');
   expect(body,file).not.toContain('/api/model-c/sync/v2/runs');
  }
 });
 it('actually traverses shared modules, reexports and indirect dependencies',()=>{
  const graph=reachable('worker/index.ts');
  expect(graph).toContain('worker/private-runtime.ts');
  expect(graph).toContain('worker/model-c-ingest-v2-production.ts');
  expect(graph).toContain('worker/data/model-c-catalog.ts');
  expect(graph).toContain('shared/canonical.ts');
 });
 it('detects literal dynamic modules and denies computed dynamic modules',()=>{
  const path=resolve(root,'worker/index.ts');
  expect(importSpecifiers("import('./lib'); export {x} from './other';",path))
   .toEqual(['./other','./lib']);
  expect(()=>importSpecifiers("import(dynamicPath)",path)).toThrow('NONSTATIC_WORKER_IMPORT');
 });
});
