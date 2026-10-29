import { readFile, readdir } from "node:fs/promises";
import { execFileSync } from "node:child_process";
import { build } from "esbuild";
import { convertV4MiniflareOptions, Miniflare } from "miniflare";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { canonical, sha256 } from "../shared/canonical";
import {
  prepareBundle,
  requiredFiles,
  validateBundle,
} from "../shared/snapshot";
import { jobsQuerySchema } from "../shared/queries";
import { importSnapshot } from "../worker/data/importer";
import { getJob, getSnapshot, listJobs } from "../worker/data/queries";

let runtime: Miniflare;
let db: D1Database;
const hash = "a".repeat(64),
  stamp = "2026-10-29T10:00:00Z";
const provenance = { sourcePath: "current_jobs_jw1.json", sourceSha256: hash };
const job = {
  kind: "job",
  jobKey: "Synthetic Company::1",
  aliases: [],
  companyId: "company:1",
  sourceId: "source:1",
  upstreamSourceId: "1",
  batch: "jw1",
  title: "Alpha Analyst",
  location: "Milan",
  canonicalUrl: "https://example.test/jobs/1",
  applyUrl: null,
  fingerprint: "b".repeat(16),
  lifecycle: "STILL_OPEN",
  firstSeenAt: stamp,
  lastSeenAt: stamp,
  analysisStatus: "ANALYZED",
  analysisMethod: "chatgpt_semantic_full_jd",
  needsAnalysis: false,
  workerEligible: false,
  hardExclusionReason: null,
  fitScore: 75,
  reportable: true,
  effectiveDecision: "APPLIED",
  technicalStatus: null,
  sortKey: "synthetic\0alpha",
  ...provenance,
};
async function bundle(
  commit = "a".repeat(40),
  override: Record<string, unknown> = {},
) {
  const first = { ...job, ...override };
  return prepareBundle({
    commitSha: commit,
    observedAt: stamp,
    files: requiredFiles.map((path) => ({ path, sha256: hash, bytes: 1 })),
    rows: [
      {
        kind: "company",
        id: "company:1",
        name: "Synthetic Company",
        configId: "1",
        tier: "1",
        priority: null,
        careerUrl: null,
        membership: "ACTIVE",
        sourcePath: "companies_job_watch_v2.json",
        sourceSha256: hash,
      },
      {
        kind: "source",
        id: "source:1",
        companyId: "company:1",
        sourceKey: "fixture",
        family: "fixture",
        inventoryUrl: "https://example.test/jobs",
        coverage: "PARTIAL",
        generatedAt: stamp,
        coveragePath: "current_jobs_jw1.json",
        coverageSha256: hash,
        sourcePath: "ats_mapping_jw1.json",
        sourceSha256: hash,
      },
      first,
      {
        ...job,
        jobKey: "Synthetic Company::2",
        upstreamSourceId: "2",
        title: "Beta Analyst",
        sortKey: "synthetic\0beta",
        lifecycle: "UNKNOWN",
        effectiveDecision: null,
        fitScore: null,
        analysisStatus: "PENDING",
        analysisMethod: null,
        needsAnalysis: true,
        workerEligible: false,
        technicalStatus: "JD_UNAVAILABLE",
      },
      {
        ...job,
        jobKey: "Synthetic Company::3",
        upstreamSourceId: "3",
        title: "Closed Analyst",
        sortKey: "synthetic\0closed",
        batch: null,
        lifecycle: "CLOSED",
        effectiveDecision: null,
        analysisStatus: null,
        analysisMethod: null,
        fitScore: null,
        reportable: null,
      },
      {
        kind: "semantic",
        jobKey: first.jobKey,
        fingerprint: "b".repeat(16),
        method: "chatgpt_semantic_full_jd",
        decision: null,
        fitScore: 75,
        reportable: true,
        evidenceState: "FULL",
        analyzedAt: stamp,
        hashInput: {
          score: 75,
          rationale: "Synthetic private review preimage",
        },
        sourcePath: "job_memory_jw1.json",
        sourceSha256: hash,
      },
      {
        kind: "user",
        jobKey: first.jobKey,
        fingerprint: "a".repeat(16),
        decision: "APPLIED",
        rejectionReason: null,
        decidedAt: stamp,
        hashInput: {
          decision: "APPLIED",
          reason: "Synthetic private choice preimage",
        },
        sourcePath: "job_memory_jw1.json",
        sourceSha256: hash,
      },
      {
        kind: "pipeline",
        runId: "fixture-run",
        healthStatus: "NEEDS_REVIEW",
        collectionStatus: "COMPLETE_WITH_WARNINGS",
        dailyComplete: false,
        fullSemanticComplete: false,
        generatedAt: stamp,
        sourcePath: "job_watch_healthcheck.json",
        sourceSha256: hash,
      },
    ],
  });
}
const options = (expectedRevision = 0) => ({
  expectedRevision,
  verifyAdvance: async () => true,
});
beforeEach(async () => {
  const built = await build({
    entryPoints: ["worker/index.ts"],
    bundle: true,
    write: false,
    format: "esm",
    platform: "browser",
  });
  runtime = new Miniflare(
    convertV4MiniflareOptions({
      modules: true,
      script: built.outputFiles[0]!.text,
      cf: false,
      compatibilityDate: "2026-10-29",
      bindings: { APP_ENV: "local" },
      d1Databases: { DB: "sync-test", UPGRADE: "upgrade-test" },
    }),
  );
  db = (await runtime.getD1Database("DB")) as unknown as D1Database;
  for (const file of (await readdir("migrations"))
    .filter((f) => f.endsWith(".sql"))
    .sort()) {
    for (const sql of (await readFile(`migrations/${file}`, "utf8")).split(
      "-- statement-breakpoint",
    ))
      if (sql.trim()) await db.prepare(sql).run();
  }
});
afterEach(async () => {
  await runtime?.dispose();
});

describe("canonical and source boundary", () => {
  it("uses ECMAScript/RFC8785 numeric formatting and rejects invalid values", () => {
    expect(canonical({ z: 1e30, a: [-0, 4.5, 1e-7] })).toBe(
      '{"a":[0,4.5,1e-7],"z":1e+30}',
    );
    for (const value of [NaN, Infinity, undefined, "\ud800"])
      expect(() => canonical(value)).toThrow();
  });
  it("removes raw review/choice preimages from the persisted envelope", async () => {
    const value = await bundle();
    expect(JSON.stringify(value)).not.toContain("preimage");
    expect(JSON.stringify(value)).not.toContain("hashInput");
    await expect(validateBundle(value)).resolves.toBeTruthy();
  });
  it("validates hashes, provenance, complete manifest and unknown fields before any write", async () => {
    const value = await bundle();
    value.chunks[0]![0]!.sourceSha256 = "c".repeat(64);
    await expect(importSnapshot(db, value, options())).rejects.toThrow(
      "CHUNK_HASH_MISMATCH",
    );
    expect(
      await db.prepare("SELECT count(*) AS n FROM sync_snapshots").first("n"),
    ).toBe(0);
    const missing = await bundle();
    missing.manifest.files.pop();
    await expect(validateBundle(missing)).rejects.toThrow(
      "INCOMPLETE_MANIFEST",
    );
    const unknown = await bundle();
    Object.assign(unknown.chunks[0]![0]!, { jd: "Synthetic forbidden field" });
    await expect(validateBundle(unknown)).rejects.toThrow();
  });
  it("runs the isolated Python exporter contract tests", () => {
    expect(() =>
      execFileSync(
        process.env.JOB_WATCH_PYTHON || "python3",
        ["tools/test_exporter.py", "-q"],
        { stdio: "pipe" },
      ),
    ).not.toThrow();
  });
});

describe("local D1 synchronization and read services", () => {
  it("preserves existing observations while upgrading schema 2 to 4", async () => {
    const legacy = await runtime.getD1Database("UPGRADE");
    for (const file of (await readdir("migrations"))
      .filter((f) => f.endsWith(".sql"))
      .sort()) {
      for (const sql of (await readFile(`migrations/${file}`, "utf8")).split(
        "-- statement-breakpoint",
      ))
        if (sql.trim()) await legacy.prepare(sql).run();
      if (file.startsWith("0002")) {
        await legacy
          .prepare(
            "INSERT INTO sync_snapshots(id,repository,commit_sha,manifest_sha256,contract_version,expected_chunks) VALUES ('legacy','giacodmr/job-watch-milano',?,?,1,1)",
          )
          .bind("a".repeat(40), hash)
          .run();
        await legacy
          .prepare(
            "INSERT INTO companies(id,canonical_name) VALUES ('c','Synthetic Legacy')",
          )
          .run();
        await legacy
          .prepare(
            "INSERT INTO jobs(id,company_id,origin_job_key) VALUES ('j','c','Synthetic Legacy::1')",
          )
          .run();
        await legacy
          .prepare(
            "INSERT INTO job_versions(job_id,company_id,snapshot_id,batch,upstream_source_id,title,lifecycle,source_path,source_sha256,observed_at) VALUES ('j','c','legacy','jw1','1','Preserved role','UNKNOWN','job_memory_jw1.json',?,?)",
          )
          .bind(hash, stamp)
          .run();
      }
    }
    expect(
      await legacy.prepare("SELECT title FROM job_versions").first("title"),
    ).toBe("Preserved role");
    expect(
      await legacy
        .prepare("SELECT version FROM schema_metadata")
        .first("version"),
    ).toBe(4);
    expect(
      (await legacy.prepare("PRAGMA foreign_key_check").all()).results,
    ).toHaveLength(0);
  });
  it("keeps an empty DB distinct from an empty filtered result", async () => {
    expect((await getSnapshot(db)).snapshot).toBeNull();
    const page = await listJobs(db, jobsQuerySchema.parse({}));
    expect(page.snapshotId).toBeNull();
  });
  it("imports, measures and replays without duplicate rows or audit", async () => {
    const value = await bundle();
    const first = await importSnapshot(db, value, options());
    expect(first.revision).toBe(1);
    expect(first.rowsWritten).toBeGreaterThan(0);
    expect(first.databaseBytes).toBeGreaterThan(0);
    const second = await importSnapshot(db, value, options(1));
    expect(second.replayed).toBe(true);
    expect(second.rowsWritten).toBe(0);
    expect(
      await db.prepare("SELECT count(*) AS n FROM audit_log").first("n"),
    ).toBe(1);
    expect((await getSnapshot(db)).snapshot?.jobCount).toBe(3);
  });
  it("resumes interrupted chunks while preserving the previous confirmed view", async () => {
    const first = await importSnapshot(db, await bundle(), options());
    const next = await bundle("b".repeat(40), { title: "Changed Analyst" });
    await expect(
      importSnapshot(db, next, { ...options(1), stopAfterChunks: 1 }),
    ).rejects.toThrow("IMPORT_INTERRUPTED");
    expect((await getSnapshot(db)).snapshot?.id).toBe(first.snapshotId);
    expect(
      (await listJobs(db, jobsQuerySchema.parse({ q: "Changed" }))).total,
    ).toBe(0);
    const resumed = await importSnapshot(db, next, options(1));
    expect(resumed.chunksReplayed).toBeGreaterThan(0);
    expect(
      (await listJobs(db, jobsQuerySchema.parse({ q: "Changed" }))).total,
    ).toBe(1);
    expect(
      await db.prepare("SELECT count(*) AS n FROM semantic_reviews").first("n"),
    ).toBe(1);
  });
  it("preserves stable identity across a Python-confirmed alias and fingerprint change", async () => {
    await importSnapshot(db, await bundle(), options());
    const previous = await listJobs(
      db,
      jobsQuerySchema.parse({ decision: "APPLIED" }),
    );
    await importSnapshot(
      db,
      await bundle("c".repeat(40), {
        jobKey: "Synthetic Company::new",
        aliases: ["Synthetic Company::1"],
        fingerprint: "c".repeat(16),
      }),
      options(1),
    );
    const next = await listJobs(
      db,
      jobsQuerySchema.parse({ decision: "APPLIED" }),
    );
    expect(next.items[0]?.id).toBe(previous.items[0]?.id);
    expect(next.items[0]?.decision).toBe("APPLIED");
    const detail = await getJob(db, next.items[0]!.id, next.snapshotId!);
    expect(detail.aliases).toContain("Synthetic Company::1");
    expect(detail.decisions).toHaveLength(1);
    expect(detail.reviews).toHaveLength(1);
  });
  it("hides aliases from an interrupted future snapshot", async () => {
    await importSnapshot(db, await bundle(), options());
    const current = await listJobs(
      db,
      jobsQuerySchema.parse({ decision: "APPLIED" }),
    );
    const future = await bundle("f".repeat(40), {
      aliases: ["Synthetic Company::future"],
    });
    await expect(
      importSnapshot(db, future, { ...options(1), stopAfterChunks: 2 }),
    ).rejects.toThrow("IMPORT_INTERRUPTED");
    expect(
      await db
        .prepare(
          "SELECT count(*) AS n FROM job_aliases WHERE alias_key='Synthetic Company::future'",
        )
        .first("n"),
    ).toBe(1);
    expect(
      (await getJob(db, current.items[0]!.id, current.snapshotId!)).aliases,
    ).not.toContain("Synthetic Company::future");
    await importSnapshot(db, future, options(1));
    const next = await listJobs(
      db,
      jobsQuerySchema.parse({ decision: "APPLIED" }),
    );
    expect(
      (await getJob(db, next.items[0]!.id, next.snapshotId!)).aliases,
    ).toContain("Synthetic Company::future");
  });
  it("stops at the local write budget without publishing an incomplete snapshot", async () => {
    await importSnapshot(db, await bundle(), options());
    const next = await bundle("b".repeat(40));
    await expect(
      importSnapshot(db, next, { ...options(1), maxRowsWritten: 100 }),
    ).rejects.toThrow("LOCAL_WRITE_BUDGET_REACHED");
    expect((await getSnapshot(db)).snapshot?.revision).toBe(1);
    await importSnapshot(db, next, options(1));
    expect((await getSnapshot(db)).snapshot?.revision).toBe(2);
    expect(
      (await listJobs(db, jobsQuerySchema.parse({ lifecycle: "ALL" }))).total,
    ).toBe(3);
  });
  it("keeps unknown/closed lifecycle and semantic outcomes separate from user choices", async () => {
    await importSnapshot(db, await bundle(), options());
    const all = await listJobs(db, jobsQuerySchema.parse({}));
    expect(all.total).toBe(3);
    expect(
      all.items.find((row) => row.lifecycle === "CLOSED")?.batch,
    ).toBeNull();
    expect(
      (await listJobs(db, jobsQuerySchema.parse({ lifecycle: "UNKNOWN" })))
        .items[0]?.technicalStatus,
    ).toBe("JD_UNAVAILABLE");
    expect(
      (await listJobs(db, jobsQuerySchema.parse({ assessment: "pending" })))
        .total,
    ).toBe(1);
    expect(
      (await listJobs(db, jobsQuerySchema.parse({ decision: "APPLIED" })))
        .total,
    ).toBe(1);
  });
  it("paginates deterministically and rejects stale or mismatched cursors", async () => {
    await importSnapshot(db, await bundle(), options());
    const first = await listJobs(db, jobsQuerySchema.parse({ limit: 1 }));
    const second = await listJobs(
      db,
      jobsQuerySchema.parse({ limit: 1, cursor: first.nextCursor }),
    );
    expect(first.items[0]?.id).not.toBe(second.items[0]?.id);
    await expect(
      listJobs(
        db,
        jobsQuerySchema.parse({
          limit: 1,
          q: "other",
          cursor: first.nextCursor,
        }),
      ),
    ).rejects.toThrow("CURSOR_FILTER_MISMATCH");
    await importSnapshot(db, await bundle("d".repeat(40)), options(1));
    await expect(
      listJobs(
        db,
        jobsQuerySchema.parse({ limit: 1, cursor: first.nextCursor }),
      ),
    ).rejects.toThrow("SNAPSHOT_CHANGED");
  });
  it("rejects stale revision and divergent/older snapshots without changing the checkpoint", async () => {
    const first = await importSnapshot(db, await bundle(), options());
    await expect(
      importSnapshot(db, await bundle("b".repeat(40)), options(0)),
    ).rejects.toThrow("CHECKPOINT_CONFLICT");
    await expect(
      importSnapshot(db, await bundle("b".repeat(40)), {
        expectedRevision: 1,
        verifyAdvance: async () => false,
      }),
    ).rejects.toThrow("NON_FORWARD_SNAPSHOT");
    expect((await getSnapshot(db)).snapshot?.id).toBe(first.snapshotId);
  });
  it("rolls back publication and audit if the final CAS loses a concurrent race", async () => {
    const first = await importSnapshot(db, await bundle(), options());
    const value = await bundle("e".repeat(40));
    let calls = 0;
    const racing = new Proxy(db, {
      get(target, key) {
        if (key === "batch")
          return async (statements: D1PreparedStatement[]) => {
            if (++calls === value.chunks.length + 1)
              await target
                .prepare(
                  "UPDATE sync_checkpoints SET revision=revision+1 WHERE scope='main'",
                )
                .run();
            return target.batch(statements);
          };
        const v = Reflect.get(target, key);
        return typeof v === "function" ? v.bind(target) : v;
      },
    });
    await expect(importSnapshot(racing, value, options(1))).rejects.toThrow();
    expect((await getSnapshot(db)).snapshot?.id).toBe(first.snapshotId);
    expect(
      await db.prepare("SELECT count(*) AS n FROM audit_log").first("n"),
    ).toBe(1);
    expect(
      await db
        .prepare(
          "SELECT count(*) AS n FROM sync_snapshots WHERE state='CONFIRMED'",
        )
        .first("n"),
    ).toBe(1);
  });
  it("rejects a reused marker with conflicting hash", async () => {
    const value = await bundle();
    await expect(
      importSnapshot(db, value, { ...options(), stopAfterChunks: 1 }),
    ).rejects.toThrow("IMPORT_INTERRUPTED");
    await db
      .prepare("UPDATE sync_chunks SET content_sha256=?")
      .bind("f".repeat(64))
      .run();
    await expect(importSnapshot(db, value, options())).rejects.toThrow(
      "CHUNK_REPLAY_CONFLICT",
    );
  });
  it("serves validated read-only API responses and never echoes invalid input", async () => {
    await importSnapshot(db, await bundle(), options());
    const good = await runtime.dispatchFetch(
      "http://localhost/api/jobs?lifecycle=OPEN",
    );
    expect(good.status).toBe(200);
    for (const path of [
      "/api/jobs?limit=101",
      "/api/jobs?limit=1&limit=2",
      "/api/snapshot?jd=secret",
      "/api/jobs?unknown=secret",
    ]) {
      const response = await runtime.dispatchFetch("http://localhost" + path);
      expect(response.status).toBe(400);
      expect(await response.text()).not.toContain("secret");
    }
    expect(
      (
        await runtime.dispatchFetch("http://localhost/api/jobs", {
          method: "POST",
        })
      ).status,
    ).toBe(405);
    expect(
      (await runtime.dispatchFetch("https://remote.example/api/jobs")).status,
    ).toBe(403);
    const blank = await runtime.dispatchFetch(
      "http://localhost/api/jobs?q=does-not-exist",
    );
    expect(((await blank.json()) as { total: number }).total).toBe(0);
  });
  it("binds the manifest and chunk hashes to canonical content", async () => {
    const value = await bundle();
    expect(value.manifest.chunks[0]?.sha256).toBe(
      await sha256(canonical(value.chunks[0])),
    );
  });
});
