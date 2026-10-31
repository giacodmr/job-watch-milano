// M47 Gate A: resolve the complete *runtime* import/export graph, not only entrypoint text.
import {describe,expect,it} from 'vitest';
import {existsSync,readFileSync} from 'node:fs';
import {dirname,relative,resolve} from 'node:path';
import * as tsModule from 'typescript';
// Vite's CJS interop exposes the compiler API as the default namespace.
const ts=(tsModule as typeof tsModule & {default?:typeof tsModule}).default??tsModule;

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
function dependencies(file:string):string[]{
 const body=readFileSync(file,'utf8');
 const tree=ts.createSourceFile(file,body,ts.ScriptTarget.Latest,true,ts.ScriptKind.TS);
 const imports:string[]=[];
 function record(value:tsModule.Expression|undefined){
  if(value && ts.isStringLiteral(value))imports.push(value.text);
  else throw Error('NONSTATIC_WORKER_IMPORT:'+relative(root,file));
 }
 function walk(node:tsModule.Node){
  if(ts.isImportDeclaration(node)&&!node.importClause?.isTypeOnly)
   record(node.moduleSpecifier as tsModule.Expression);
  if(ts.isExportDeclaration(node)&&!node.isTypeOnly&&node.moduleSpecifier)
   record(node.moduleSpecifier as ts.Expression);
  if(ts.isCallExpression(node)&&node.expression.kind===ts.SyntaxKind.ImportKeyword)
   record(node.arguments[0]);
  ts.forEachChild(node,walk);
 }
 walk(tree);
 return imports.filter(s=>s.startsWith('.')).map(spec=>{
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
   const body=readFileSync(resolve(root,file),'utf8');
   expect(body,file).not.toContain('/api/model-c/sync/v2/runs');
  }
 });
 it('actually traverses shared modules, reexports and indirect dependencies',()=>{
  const graph=reachable('worker/index.ts');
  expect(graph).toContain('worker/private-runtime.ts');
  expect(graph).toContain('worker/data/model-c-catalog.ts');
  expect(graph).toContain('shared/canonical.ts');
 });
});
