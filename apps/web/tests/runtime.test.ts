import { readFile, readdir } from 'node:fs/promises';
import { build } from 'esbuild';
import { convertV4MiniflareOptions, Miniflare } from 'miniflare';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { healthSchema, schemaVersion } from '../shared/contracts';
import worker from '../worker/index';

// Synthetic identities only. No repository data files, network or credentials.
let runtime: Miniflare;
let db: Awaited<ReturnType<Miniflare['getD1Database']>>;
const sha = 'a'.repeat(40);
const hash = 'b'.repeat(64);

async function sql(statement: string, ...args: (string | number | null)[]) {
  return db
    .prepare(statement)
    .bind(...args)
    .run();
}
async function snapshot(id: string) {
  await sql(
    'INSERT INTO sync_snapshots (id, repository, commit_sha, manifest_sha256, contract_version, expected_chunks) VALUES (?, ?, ?, ?, 1, 1)',
    id,
    'giacodmr/job-watch-milano',
    sha,
    id.padEnd(64, '0'),
  );
}
async function confirm(id: string) {
  await sql(
    'INSERT INTO sync_chunks (snapshot_id, chunk_index, content_sha256, row_count) VALUES (?, 0, ?, 0)',
    id,
    hash,
  );
  await sql(
    "UPDATE sync_snapshots SET state='CONFIRMED', confirmed_at='2026-10-29T10:00:00Z' WHERE id=?",
    id,
  );
}
async function command(id: string) {
  await sql(
    `INSERT INTO commands (id, actor_ref, idempotency_key, payload_sha256, type, job_id,
    expected_commit_sha, expected_manifest_sha256, expected_fingerprint, decision)
    VALUES (?, 'synthetic-actor', ?, ?, 'user_decision', 'job-1', ?, ?, '1234567890abcdef', 'INTERESTED')`,
    id,
    id,
    hash,
    sha,
    hash,
  );
}

beforeAll(async () => {
  const bundle = await build({
    entryPoints: ['worker/index.ts'],
    bundle: true,
    write: false,
    format: 'esm',
    platform: 'browser',
    target: 'es2023',
  });
  const script = bundle.outputFiles[0]?.text;
  if (!script) throw new Error('Missing Worker bundle');
  runtime = new Miniflare(
    convertV4MiniflareOptions({
      modules: true,
      script,
      cf: false,
      compatibilityDate: '2026-10-29',
      bindings: { APP_ENV: 'local' },
      d1Databases: { DB: 'foundation-test' },
    }),
  );
  db = await runtime.getD1Database('DB');
  for (const name of (await readdir('migrations'))
    .filter((name) => name.endsWith('.sql'))
    .sort()) {
    const migration = await readFile(`migrations/${name}`, 'utf8');
    for (const statement of migration.split('-- statement-breakpoint')) {
      if (statement.trim()) await db.prepare(statement).run();
    }
  }
  await snapshot('confirmed');
  await confirm('confirmed');
  await snapshot('staging');
  await sql(
    "INSERT INTO companies(id, canonical_name) VALUES ('company-1','Synthetic Company')",
  );
  await sql(
    "INSERT INTO jobs(id, company_id, origin_job_key) VALUES ('job-1','company-1','Synthetic Company::1')",
  );
});
afterAll(async () => {
  await runtime?.dispose();
});

describe('Worker HTTP on real local D1', () => {
  it('checks the applied schema without claiming pipeline completion', async () => {
    const response = await runtime.dispatchFetch('http://localhost/api/health');
    expect(response.status).toBe(200);
    expect(response.headers.get('Cache-Control')).toBe('no-store');
    const body = healthSchema.parse(await response.json());
    expect(body).toMatchObject({
      database: 'ready',
      schemaVersion,
      synchronization: 'local-read-only',
      productionAccess: false,
    });
    expect(body).not.toHaveProperty('DAILY_COMPLETE');
  });
  it('returns degraded for an outdated schema', async () => {
    await sql('UPDATE schema_metadata SET version=1');
    try {
      const response = await runtime.dispatchFetch(
        'http://localhost/api/health',
      );
      expect(response.status).toBe(503);
      expect(await response.json()).toMatchObject({
        database: 'migration_required',
        schemaVersion: 1,
      });
    } finally {
      await sql('UPDATE schema_metadata SET version=?', schemaVersion);
    }
  });
  it('returns redacted errors for a missing database table', async () => {
    await sql(
      'ALTER TABLE schema_metadata RENAME TO schema_metadata_temporarily_missing',
    );
    try {
      const response = await runtime.dispatchFetch(
        'http://localhost/api/health',
      );
      expect(response.status).toBe(503);
      const body = await response.text();
      expect(JSON.parse(body)).toMatchObject({ database: 'unavailable' });
      expect(body).not.toContain('SELECT');
    } finally {
      await sql(
        'ALTER TABLE schema_metadata_temporarily_missing RENAME TO schema_metadata',
      );
    }
  });
  it('validates method/query and keeps unknown API routes out of SPA fallback', async () => {
    const query = await runtime.dispatchFetch(
      'http://localhost/api/health?unexpected=1',
    );
    expect(query.status).toBe(400);
    const post = await runtime.dispatchFetch('http://localhost/api/health', {
      method: 'POST',
    });
    expect(post.status).toBe(405);
    expect(post.headers.get('Allow')).toBe('GET');
    const unknown = await runtime.dispatchFetch('http://localhost/api/missing');
    expect(unknown.status).toBe(404);
    expect(unknown.headers.get('Content-Type')).toContain('application/json');
  });
  it('does not accept, persist or echo a command body', async () => {
    const response = await runtime.dispatchFetch(
      'http://localhost/api/commands',
      { method: 'POST', body: 'synthetic-private-body' },
    );
    expect(response.status).toBe(501);
    expect(await response.text()).not.toContain('synthetic-private-body');
    expect(
      await db.prepare('SELECT count(*) AS n FROM commands').first('n'),
    ).toBe(0);
  });
  it('fails closed on remote API and static paths even with spoofed Access headers', async () => {
    for (const path of ['/api/health', '/', '/assets/app.js']) {
      const response = await runtime.dispatchFetch(
        `https://untrusted.example${path}`,
        { headers: { 'Cf-Access-Jwt-Assertion': 'unverified' } },
      );
      expect(response.status).toBe(403);
      expect(await response.json()).toEqual({
        error: 'remote_runtime_disabled',
      });
    }
  });
  it('keeps a missing binding degraded and refuses a non-local environment', async () => {
    const missing = await worker.fetch(
      new Request('http://localhost/api/health'),
      { APP_ENV: 'local' },
    );
    expect(missing.status).toBe(503);
    expect(await missing.json()).toMatchObject({ database: 'unavailable' });
    const remote = await worker.fetch(new Request('http://localhost/'), {
      APP_ENV: 'production',
    });
    expect(remote.status).toBe(403);
  });
});

describe('D1 migration invariants', () => {
  it('creates all required domain tables without job-description columns', async () => {
    const { results } = await db
      .prepare("SELECT name FROM sqlite_master WHERE type='table'")
      .all<{ name: string }>();
    const names = results.map((row) => row.name);
    for (const name of [
      'companies',
      'sources',
      'jobs',
      'semantic_reviews',
      'user_decisions',
      'pipeline_runs',
      'commands',
      'sync_checkpoints',
      'audit_log',
    ])
      expect(names).toContain(name);
    for (const name of names.filter((name) => !name.startsWith('_'))) {
      const { results: columns } = await db
        .prepare(`PRAGMA table_info('${name}')`)
        .all<{ name: string }>();
      expect(columns.map((column) => column.name)).not.toEqual(
        expect.arrayContaining(['jd']),
      );
      expect(
        columns.some((column) =>
          ['description', 'body', 'text', 'job_description'].includes(
            column.name,
          ),
        ),
      ).toBe(false);
    }
  });
  it('requires complete chunks before publication and a confirmed checkpoint', async () => {
    await expect(
      sql(
        "UPDATE sync_snapshots SET state='CONFIRMED', confirmed_at='2026-10-29T10:00:00Z' WHERE id='staging'",
      ),
    ).rejects.toThrow('snapshot_chunks_incomplete');
    await expect(
      sql(
        "INSERT INTO sync_checkpoints VALUES ('main','staging',1,'2026-10-29T10:00:00Z')",
      ),
    ).rejects.toThrow('snapshot_not_confirmed');
    await sql(
      "INSERT INTO sync_checkpoints VALUES ('main','confirmed',1,'2026-10-29T10:00:00Z')",
    );
    await expect(
      sql(
        "UPDATE sync_checkpoints SET snapshot_id='staging', revision=2 WHERE scope='main'",
      ),
    ).rejects.toThrow('snapshot_not_confirmed');
    expect(
      await db
        .prepare("SELECT snapshot_id FROM sync_checkpoints WHERE scope='main'")
        .first('snapshot_id'),
    ).toBe('confirmed');
  });
  it('prevents sparse chunks from passing the snapshot count check', async () => {
    await snapshot('sparse');
    await sql(
      "INSERT INTO sync_chunks VALUES ('sparse',7,?,0,'2026-10-29T10:00:00Z')",
      hash,
    );
    await expect(
      sql(
        "UPDATE sync_snapshots SET state='CONFIRMED', confirmed_at='2026-10-29T10:00:00Z' WHERE id='sparse'",
      ),
    ).rejects.toThrow('snapshot_chunks_incomplete');
  });
  it('enforces foreign keys and retains jobs when a company deletion is attempted', async () => {
    await expect(
      sql("DELETE FROM companies WHERE id='company-1'"),
    ).rejects.toThrow();
    await expect(
      sql(
        "INSERT INTO jobs VALUES ('orphan','missing','missing::1','2026-10-29T10:00:00Z')",
      ),
    ).rejects.toThrow();
    expect(
      await db.prepare("SELECT id FROM jobs WHERE id='job-1'").first('id'),
    ).toBe('job-1');
  });
  it('retains closed identities and hides a partially imported newer version', async () => {
    for (const [snapshotId, lifecycle] of [
      ['confirmed', 'CLOSED'],
      ['staging', 'NEW'],
    ]) {
      await sql(
        `INSERT INTO job_versions (job_id,company_id,snapshot_id,batch,upstream_source_id,lifecycle,source_path,source_sha256,observed_at)
        VALUES ('job-1','company-1',?,'jw1','1',?,'current_jobs_jw1.json',?,'2026-10-29T10:00:00Z')`,
        snapshotId ?? '',
        lifecycle ?? '',
        hash,
      );
    }
    const row = await db
      .prepare(
        `SELECT j.id, v.lifecycle FROM sync_checkpoints c
      JOIN job_versions v ON v.snapshot_id=c.snapshot_id JOIN jobs j ON j.id=v.job_id
      WHERE c.scope='main' AND j.id='job-1'`,
      )
      .first();
    expect(row).toEqual({ id: 'job-1', lifecycle: 'CLOSED' });
  });
  it('does not conflate semantic rejection and an explicit user decision', async () => {
    await sql(
      `INSERT INTO semantic_reviews (id,job_id,snapshot_id,fingerprint,analysis_method,decision,
      reportable,evidence_state,analyzed_at,source_path,source_sha256,result_sha256)
      VALUES ('review-1','job-1','confirmed','1234567890abcdef','chatgpt_semantic_triage','REJECT',0,'FULL',
      '2026-10-29T10:00:00Z','job_memory_jw1.json',?,?)`,
      hash,
      hash,
    );
    expect(
      await db.prepare('SELECT count(*) AS n FROM user_decisions').first('n'),
    ).toBe(0);
    await sql(
      `INSERT INTO user_decisions (id,job_id,snapshot_id,decision,decided_at,source_path,source_sha256,result_sha256)
      VALUES ('decision-1','job-1','confirmed','INTERESTED','2026-10-29T10:01:00Z','job_memory_jw1.json',?,?)`,
      hash,
      hash,
    );
    expect(
      await db.prepare('SELECT count(*) AS n FROM semantic_reviews').first('n'),
    ).toBe(1);
    await expect(
      sql(
        `INSERT INTO user_decisions (id,job_id,snapshot_id,decision,decided_at,source_path,source_sha256,result_sha256)
      VALUES ('decision-duplicate','job-1','confirmed','INTERESTED','2026-10-29T10:01:00Z','job_memory_jw1.json',?,?)`,
        hash,
        hash,
      ),
    ).rejects.toThrow();
  });
  it('requires acknowledged application before command confirmation', async () => {
    await command('command-confirmation');
    await expect(
      sql(
        "UPDATE commands SET status='CONFIRMED',applied_commit_sha=?,receipt_sha256=?,confirmation_snapshot_id='confirmed' WHERE id='command-confirmation'",
        sha,
        hash,
      ),
    ).rejects.toThrow('invalid_command_transition');
    await sql(
      "UPDATE commands SET status='VALIDATED' WHERE id='command-confirmation'",
    );
    await sql(
      "UPDATE commands SET status='DISPATCHED' WHERE id='command-confirmation'",
    );
    await expect(
      sql(
        "UPDATE commands SET status='APPLIED' WHERE id='command-confirmation'",
      ),
    ).rejects.toThrow();
    await sql(
      "UPDATE commands SET status='APPLIED',applied_commit_sha=?,receipt_sha256=? WHERE id='command-confirmation'",
      sha,
      hash,
    );
    await expect(
      sql(
        "UPDATE commands SET status='CONFIRMED',confirmation_snapshot_id='staging' WHERE id='command-confirmation'",
      ),
    ).rejects.toThrow('command_snapshot_not_confirmed');
    await sql(
      "UPDATE commands SET status='CONFIRMED',confirmation_snapshot_id='confirmed' WHERE id='command-confirmation'",
    );
  });
  it('deduplicates command keys, keeps payload immutable and audit append-only', async () => {
    await command('command-idempotency');
    await expect(command('command-idempotency')).rejects.toThrow();
    await expect(
      sql(
        "UPDATE commands SET decision='APPLIED' WHERE id='command-idempotency'",
      ),
    ).rejects.toThrow('command_payload_immutable');
    await sql(
      "INSERT INTO audit_log (id,event_code,actor_ref,entity_type,entity_id) VALUES ('audit-1','COMMAND_QUEUED','synthetic-actor','command','command-idempotency')",
    );
    await expect(
      sql("UPDATE audit_log SET event_code='CHANGED' WHERE id='audit-1'"),
    ).rejects.toThrow('audit_append_only');
    await expect(
      sql("DELETE FROM audit_log WHERE id='audit-1'"),
    ).rejects.toThrow('audit_append_only');
  });
});
