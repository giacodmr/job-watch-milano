// Explicit local, read-only export-contract verification. No D1 import or bundle output.
import { execFileSync, spawnSync } from 'node:child_process';
import { readFile, readdir, mkdtemp, rm, stat } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createHash } from 'node:crypto';
import { parseArgs } from 'node:util';
import { build } from 'esbuild';
const app = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const python = process.env.JOB_WATCH_PYTHON || 'python3';
const hash = bytes => createHash('sha256').update(bytes).digest('hex');
async function load(path) {
  const b = await build({entryPoints:[resolve(app,path)],bundle:true,write:false,platform:'node',format:'esm'});
  return import('data:text/javascript;base64,'+Buffer.from(b.outputFiles[0].text).toString('base64'));
}
const metadata = (path, bytes) => ({path,bytes:bytes.length,sha256:hash(bytes)});
try {
  const {values} = parseArgs({options:{file:{type:'string'},repo:{type:'string'},baseline:{type:'string'}}});
  if (!values.file) throw Error('PRIVATE_INPUT_REQUIRED');
  const repo = resolve(values.repo || resolve(app,'../..'));
  const git = (...args) => execFileSync('git',['-C',repo,...args],{maxBuffer:64*1024*1024,stdio:['ignore','pipe','pipe']});
  if (!/^(https:\/\/github\.com\/|git@github\.com:)giacodmr\/job-watch-milano(?:\.git)?$/.test(git('remote','get-url','origin').toString().trim())) throw Error('UNAUTHORIZED_REPOSITORY');
  if ((await stat(values.file)).size > 32*1024*1024) throw Error('BUNDLE_TOO_LARGE');
  const {validateBundle,prepareBundle} = await load('shared/snapshot.ts');
  const {canonical} = await load('shared/canonical.ts');
  const {selectModelC,selectionContract,selectionContextDigest} = await load('shared/model-c-selection.ts');
  const {createProjectionProof,verifyProjectionProof,catalogObservation} = await load('shared/projection-proof.ts');
  const bundle = await validateBundle(JSON.parse(await readFile(values.file,'utf8')));
  const sha = bundle.manifest.commitSha;
  git('merge-base','--is-ancestor',sha,'refs/remotes/origin/main');
  const tree = git('ls-tree','-r','-z',sha).toString().split('\0').filter(Boolean).map(s=>{
    const [info,path] = s.split('\t');return {mode:info.split(' ')[0],path};
  });
  // A conservative dependency closure covers new Python imports and JSON inputs.
  const sourceFiles = tree.filter(x=>/\.(py|json|jsonl)$/.test(x.path));
  const verifiedFiles = [];
  for (const f of sourceFiles) {
    if (!['100644','100755'].includes(f.mode)) throw Error('UNSUPPORTED_SOURCE_MODE');
    verifiedFiles.push(metadata(f.path,git('show',`${sha}:${f.path}`)));
  }
  verifiedFiles.sort((a,b)=>a.path<b.path?-1:a.path>b.path?1:0);
  for (const f of bundle.manifest.files) {
    if (!verifiedFiles.some(v=>canonical(v)===canonical(f))) throw Error('SOURCE_HASH_MISMATCH');
  }
  const implementationFiles = [];
  for (const scope of ['shared','tools']) {
    for (const name of await readdir(resolve(app,scope),{recursive:true})) if (/\.(ts|mjs|py)$/.test(name)) {
      const path = scope+'/'+name;
      implementationFiles.push(metadata(path,await readFile(resolve(app,path))));
    }
  }
  implementationFiles.sort((a,b)=>a.path<b.path?-1:a.path>b.path?1:0);
  const runtime = {node:process.version,python:execFileSync(python,['--version'],{stdio:['ignore','pipe','pipe']}).toString().trim()};
  // Legacy bundles have no code proof: re-export in an isolated Git archive,
  // compare the complete v1 envelope in memory, and only then seal a proof.
  const temp = await mkdtemp(resolve(tmpdir(),'model-c-replay-'));
  try {
    const unpack = spawnSync(python,['-c',"import io,sys,tarfile; tarfile.open(fileobj=io.BytesIO(sys.stdin.buffer.read())).extractall(sys.argv[1],filter='data')",temp],{input:git('archive','--format=tar',sha),maxBuffer:64*1024*1024});
    if (unpack.status!==0) throw Error('ARCHIVE_EXTRACTION_FAILED');
    const extracted = spawnSync(python,[resolve(app,'tools/export_snapshot.py'),'--root',temp,'--commit',sha,'--observed-at',bundle.manifest.observedAt],{maxBuffer:64*1024*1024,env:{...process.env,PYTHONDONTWRITEBYTECODE:'1'}});
    if (extracted.status!==0) throw Error('PROJECTION_REPLAY_FAILED');
    const replay = await prepareBundle(JSON.parse(extracted.stdout.toString()));
    if (canonical(replay)!==canonical(bundle)) throw Error('LEGACY_PROJECTION_MISMATCH');
  } finally { await rm(temp,{recursive:true,force:true}); }
  const context = {identities:{mode:'first-v1-bootstrap'},personalReferences:[]};
  const proof = await createProjectionProof(bundle,{contract:selectionContract,sourceFiles:verifiedFiles,implementationFiles,runtime,selectionContextDigest:await selectionContextDigest(context)},context);
  await verifyProjectionProof(bundle,proof,context);
  // This CLI validates FIRST-import audit datasets, not a migration of an existing
  // D1 ledger. selectModelC requires explicit confirmed-ledger mode for that case.
  const selected = await selectModelC(bundle,context);
  const counts = {identities:selected.ledger.identities.length,mappings:selected.ledger.mappings.length,decisions:selected.decisions.length,subjects:selected.subjects.length,catalog:selected.catalog.length,aiQueue:selected.aiQueue.length,reviews:selected.reviews.length};
  if (values.baseline) {
    const baseline = JSON.parse(await readFile(values.baseline,'utf8'));
    if (baseline.commit!==sha || canonical(baseline.counts)!==canonical(counts)) throw Error('AUDIT_BASELINE_MISMATCH');
  }
  console.log(JSON.stringify({status:'MODEL_C_CONTRACT_VERIFIED',commit:sha,counts,
    observation:catalogObservation(proof,selected.catalogContentDigest),
    replayVerified:true,proofFiles:verifiedFiles.length,implementationFiles:implementationFiles.length,
    d1Writes:0,productionAccess:false}));
} catch (e) {
  console.error(JSON.stringify({error:/^[A-Z][A-Z0-9_]+$/.test(e?.message||'')?e.message:'MODEL_C_CHECK_FAILED',productionAccess:false}));
  process.exitCode=1;
}
