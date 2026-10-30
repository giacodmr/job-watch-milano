// Node-only trusted Git adapter; no transport, cloud binding or runtime route.
import { createHash } from 'node:crypto';
import { execFileSync, spawnSync } from 'node:child_process';
import { mkdtemp, readFile, readdir, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { resolve } from 'node:path';
import { canonical } from '../shared/canonical';
import { prepareBundle, validateBundle } from '../shared/snapshot';
import { selectionContextDigest, selectionContract } from '../shared/model-c-selection';
import type { SelectionContext } from '../shared/model-c-selection';
import { createProjectionProof } from '../shared/projection-proof';

const app = resolve(import.meta.dirname, '..');
const sourcePattern = /^(companies_job_watch_v2\.json|company_candidates\.json|job_watch_batches\.json|job_watch_rules\.json|ats_mapping_jw[1-4]\.json|current_jobs_jw[1-4]\.json|job_memory_jw[1-4]\.json|archive\/vacancies_\d{4}_\d{2}\.jsonl|amazon_target_check\.json|daily_worklist\.json|job_watch_healthcheck\.json|pipeline_execution\.json|job_watch_run_state\.json|daily_activity\.json|\.job_watch_bridge\/receipts\/[A-Za-z0-9][A-Za-z0-9_-]{0,119}\.json)$/;
export interface GitSource { repo: string; commit: string; bundle?: unknown; proof?: unknown }
/** Always replays the existing Python exporter in a private disposable Git archive.
 * Proof supplied by a caller is compared with verified bytes, never trusted.
 * origin/main is read once; refreshing the remote remains an explicit caller action.
 */
export async function verifyGitProjection(source: GitSource, context: SelectionContext, previousCommit?: string) {
  if (!/^[a-f0-9]{40}$/.test(source.commit)) throw Error('EXPLICIT_COMMIT_SHA_REQUIRED');
  const git = (...args: string[]) => {
    try { return execFileSync('git', ['-C', resolve(source.repo), ...args], { maxBuffer: 128 * 1024 * 1024, stdio: ['ignore', 'pipe', 'pipe'] }); }
    catch { throw Error('GIT_VERIFICATION_FAILED'); }
  };
  if (!/^(https:\/\/github\.com\/|git@github\.com:)giacodmr\/job-watch-milano(?:\.git)?$/.test(git('remote','get-url','origin').toString().trim())) throw Error('UNAUTHORIZED_REPOSITORY');
  const authorizedHead = git('rev-parse','refs/remotes/origin/main^{commit}').toString().trim();
  git('merge-base','--is-ancestor',source.commit,authorizedHead);
  if (previousCommit) git('merge-base','--is-ancestor',previousCommit,source.commit);
  const tree = git('ls-tree','-r','-z',source.commit).toString().split('\0').filter(Boolean).map(line => {
    const tab = line.indexOf('\t'); const [mode,type] = line.slice(0,tab).split(' ');
    return { mode, type, path: line.slice(tab+1) };
  });
  // Refuse symlinks and submodules before archive extraction, including code imports.
  if (tree.some(f => f.type !== 'blob' || !['100644','100755'].includes(f.mode!))) throw Error('UNSUPPORTED_SOURCE_MODE');
  const sourceFiles = [];
  for (const f of tree.filter(f => /\.(py|json|jsonl)$/.test(f.path)).sort((a,b)=>a.path < b.path ? -1 : 1)) {
    const bytes = git('show',`${source.commit}:${f.path}`);
    sourceFiles.push({ path:f.path, bytes:bytes.length, sha256:createHash('sha256').update(bytes).digest('hex') });
  }
  const supplied = source.bundle === undefined ? undefined : await validateBundle(source.bundle);
  if (supplied && supplied.manifest.commitSha !== source.commit) throw Error('COMMIT_MISMATCH');
  const observedAt = supplied?.manifest.observedAt ?? new Date(git('show','-s','--format=%cI',source.commit).toString().trim()).toISOString().replace(/\.\d{3}Z$/,'Z');
  const python = process.env.JOB_WATCH_PYTHON || 'python3';
  const temp = await mkdtemp(resolve(tmpdir(),'model-c-import-'));
  let bundle;
  try {
    const unpack = spawnSync(python,['-c',"import io,sys,tarfile; tarfile.open(fileobj=io.BytesIO(sys.stdin.buffer.read())).extractall(sys.argv[1],filter='data')",temp],{input:git('archive','--format=tar',source.commit),maxBuffer:128*1024*1024});
    if (unpack.status !== 0) throw Error('ARCHIVE_EXTRACTION_FAILED');
    const extraction = spawnSync(python,[resolve(app,'tools/export_snapshot.py'),'--root',temp,'--commit',source.commit,'--observed-at',observedAt],{maxBuffer:64*1024*1024,env:{...process.env,PYTHONDONTWRITEBYTECODE:'1'}});
    if (extraction.status !== 0) throw Error('PROJECTION_REPLAY_FAILED');
    bundle = await prepareBundle(JSON.parse(extraction.stdout.toString()));
  } finally { await rm(temp,{recursive:true,force:true}); }
  const expectedFiles = sourceFiles.filter(f=>sourcePattern.test(f.path));
  if (canonical(bundle.manifest.files) !== canonical(expectedFiles)) throw Error('SOURCE_HASH_MISMATCH');
  if (supplied && canonical(supplied) !== canonical(bundle)) throw Error('PROJECTION_REPLAY_MISMATCH');
  const implementationFiles = [];
  for (const scope of ['shared','tools']) for (const name of await readdir(resolve(app,scope),{recursive:true})) if (/\.(ts|mjs|py)$/.test(name)) {
    const path = scope+'/'+name, bytes = await readFile(resolve(app,path));
    implementationFiles.push({path,bytes:bytes.length,sha256:createHash('sha256').update(bytes).digest('hex')});
  }
  implementationFiles.sort((a,b)=>a.path < b.path ? -1 : 1);
  const runtime = { node:process.version, python:execFileSync(python,['--version'],{stdio:['ignore','pipe','pipe']}).toString().trim() };
  const proof = await createProjectionProof(bundle,{contract:selectionContract,selectionContextDigest:await selectionContextDigest(context),sourceFiles,implementationFiles,runtime},context);
  if (source.proof !== undefined && canonical(source.proof) !== canonical(proof)) throw Error('PROJECTION_PROOF_MISMATCH');
  return {bundle,proof};
}
