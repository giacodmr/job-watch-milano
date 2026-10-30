import { execFileSync, spawnSync } from 'node:child_process';
import {
  mkdtemp,
  readFile,
  writeFile,
  mkdir,
  rm,
  chmod,
} from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseArgs } from 'node:util';
import { createHash } from 'node:crypto';
import { build } from 'esbuild';
import { getPlatformProxy } from 'wrangler';

const app = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const python = process.env.JOB_WATCH_PYTHON || 'python3';
const hash = (bytes) => createHash('sha256').update(bytes).digest('hex');
const sourcePattern =
  /^(companies_job_watch_v2\.json|company_candidates\.json|job_watch_batches\.json|job_watch_rules\.json|ats_mapping_jw[1-4]\.json|current_jobs_jw[1-4]\.json|job_memory_jw[1-4]\.json|archive\/vacancies_\d{4}_\d{2}\.jsonl|amazon_target_check\.json|daily_worklist\.json|job_watch_healthcheck\.json|pipeline_execution\.json|job_watch_run_state\.json|daily_activity\.json|\.job_watch_bridge\/receipts\/[A-Za-z0-9][A-Za-z0-9_-]{0,119}\.json)$/;

async function loadModule(path) {
  const result = await build({
    entryPoints: [resolve(app, path)],
    bundle: true,
    format: 'esm',
    platform: 'node',
    target: 'node24',
    write: false,
  });
  return import(
    'data:text/javascript;base64,' +
      Buffer.from(result.outputFiles[0].text).toString('base64')
  );
}

try {
  const { values, positionals } = parseArgs({
    allowPositionals: true,
    options: {
      commit: { type: 'string' },
      repo: { type: 'string' },
      file: { type: 'string' },
      'max-writes': { type: 'string' },
    },
  });
  const command = positionals[0];
  if (
    !['export', 'import', 'sync'].includes(command) ||
    positionals.length !== 1
  )
    throw new Error('USAGE_EXPORT_IMPORT_SYNC');
  const repo = resolve(values.repo || resolve(app, '../..'));
  const git = (...args) =>
    execFileSync('git', ['-C', repo, ...args], {
      maxBuffer: 64 * 1024 * 1024,
      stdio: ['ignore', 'pipe', 'pipe'],
    });
  const remote = git('remote', 'get-url', 'origin').toString().trim();
  if (
    !/^(https:\/\/github\.com\/|git@github\.com:)giacodmr\/job-watch-milano(?:\.git)?$/.test(
      remote,
    )
  )
    throw new Error('UNAUTHORIZED_REPOSITORY');
  const file = resolve(
    values.file || resolve(app, '.local-sync/snapshot.json'),
  );
  let bundle;
  if (command === 'export' || command === 'sync') {
    const commit = values.commit;
    if (!commit || !/^[a-f0-9]{40}$/.test(commit))
      throw new Error('EXPLICIT_COMMIT_SHA_REQUIRED');
    git('merge-base', '--is-ancestor', commit, 'refs/remotes/origin/main');
    const observedAt = new Date(
      git('show', '-s', '--format=%cI', commit).toString().trim(),
    )
      .toISOString()
      .replace(/\.\d{3}Z$/, 'Z');
    const temp = await mkdtemp(resolve(tmpdir(), 'job-watch-export-'));
    try {
      const archive = git('archive', '--format=tar', commit);
      const unpack = spawnSync(
        python,
        [
          '-c',
          "import io,sys,tarfile; tarfile.open(fileobj=io.BytesIO(sys.stdin.buffer.read())).extractall(sys.argv[1],filter='data')",
          temp,
        ],
        { input: archive, maxBuffer: 64 * 1024 * 1024 },
      );
      if (unpack.status !== 0) throw new Error('ARCHIVE_EXTRACTION_FAILED');
      const extraction = spawnSync(
        python,
        [
          resolve(app, 'tools/export_snapshot.py'),
          '--root',
          temp,
          '--commit',
          commit,
          '--observed-at',
          observedAt,
        ],
        {
          maxBuffer: 64 * 1024 * 1024,
          env: { ...process.env, PYTHONDONTWRITEBYTECODE: '1' },
        },
      );
      if (extraction.status !== 0) throw new Error('EXPORT_INVALID_SOURCE');
      const { prepareBundle } = await loadModule('shared/snapshot.ts');
      bundle = await prepareBundle(JSON.parse(extraction.stdout.toString()));
      // Only the strict, sanitized envelope is persisted. Raw hash preimages remain in process memory.
      await mkdir(dirname(file), { recursive: true, mode: 0o700 });
      await writeFile(file, JSON.stringify(bundle), { mode: 0o600 });
      await chmod(file, 0o600);
    } finally {
      await rm(temp, { recursive: true, force: true });
    }
  } else {
    const stat = await import('node:fs/promises').then((fs) => fs.stat(file));
    if (stat.size > 32 * 1024 * 1024) throw new Error('BUNDLE_TOO_LARGE');
    bundle = JSON.parse(await readFile(file, 'utf8'));
  }
  const { validateBundle } = await loadModule('shared/snapshot.ts');
  bundle = await validateBundle(bundle);
  const commit = bundle.manifest.commitSha;
  git('merge-base', '--is-ancestor', commit, 'refs/remotes/origin/main');
  const expected = git('ls-tree', '-r', '--name-only', commit)
    .toString()
    .trim()
    .split('\n')
    .filter((path) => sourcePattern.test(path))
    .sort();
  if (
    JSON.stringify(expected) !==
    JSON.stringify(bundle.manifest.files.map((f) => f.path))
  )
    throw new Error('MANIFEST_FILE_SET_MISMATCH');
  for (const item of bundle.manifest.files) {
    const bytes = git('show', `${commit}:${item.path}`);
    if (bytes.byteLength !== item.bytes || hash(bytes) !== item.sha256)
      throw new Error('SOURCE_HASH_MISMATCH');
  }
  if (command === 'export') {
    console.log(
      JSON.stringify({
        status: 'EXPORTED',
        commit,
        chunks: bundle.chunks.length,
        records: bundle.chunks.flat().length,
        bytes: Buffer.byteLength(JSON.stringify(bundle)),
      }),
    );
  } else {
    const maxWrites = Number(values['max-writes'] ?? '70000');
    if (
      !Number.isSafeInteger(maxWrites) ||
      maxWrites < 100 ||
      maxWrites > 500000
    )
      throw new Error('INVALID_LOCAL_WRITE_BUDGET');
    const proxy = await getPlatformProxy({
      configPath: resolve(app, 'wrangler.jsonc'),
      envFiles: [],
      remoteBindings: false,
      persist: { path: resolve(app, '.wrangler/state/v3') },
    });
    try {
      if (proxy.env.APP_ENV !== 'local')
        throw new Error('LOCAL_ENVIRONMENT_REQUIRED');
      const db = proxy.env.DB;
      const { schemaVersion } = await loadModule("shared/contracts.ts");
      if (
        (await db
          .prepare('SELECT version FROM schema_metadata WHERE id=1')
          .first('version')) !== schemaVersion
      )
        throw new Error('LOCAL_MIGRATIONS_REQUIRED');
      const checkpoint = await db
        .prepare("SELECT revision FROM sync_checkpoints WHERE scope='main'")
        .first();
      const { importSnapshot } = await loadModule('worker/data/importer.ts');
      const result = await importSnapshot(db, bundle, {
        expectedRevision: checkpoint?.revision ?? 0,
        maxRowsWritten: maxWrites,
        verifyAdvance: async (before, after) => {
          try {
            git('merge-base', '--is-ancestor', before, after);
            return true;
          } catch {
            return false;
          }
        },
      });
      console.log(JSON.stringify({ status: 'CONFIRMED', ...result }));
    } finally {
      await proxy.dispose();
    }
  }
} catch (error) {
  // Git, Python, Zod and SQL errors may include data or paths: log codes only.
  const code =
    error instanceof Error && /^[A-Z][A-Z0-9_]+$/.test(error.message)
      ? error.message
      : 'LOCAL_SYNC_FAILED';
  const metrics = error?.metrics;
  console.error(
    JSON.stringify({
      error: code,
      productionAccess: false,
      ...(metrics ? { metrics } : {}),
    }),
  );
  process.exitCode = 1;
}
