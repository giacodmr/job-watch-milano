import { canonical, sha256 } from "../../shared/canonical";
import { validateBundle } from "../../shared/snapshot";
import type { SnapshotRow } from "../../shared/snapshot";

export class SyncError extends Error {
  constructor(
    public readonly code: string,
    public readonly metrics: ImportMetrics | null = null,
  ) {
    super(code);
  }
}
interface ImportOptions {
  expectedRevision: number;
  verifyAdvance: (
    previousCommit: string,
    nextCommit: string,
  ) => Promise<boolean>;
  maxRowsWritten?: number;
  stopAfterChunks?: number; // For controlled interruption/recovery tests and local budgeted runs.
}
export interface ImportMetrics {
  rowsRead: number;
  rowsWritten: number;
  durationMs: number;
  databaseBytes: number;
  chunksApplied: number;
  chunksReplayed: number;
}
type Checkpoint = { snapshot_id: string; revision: number; commit_sha: string };
const bool = (value: boolean | null) => (value === null ? null : Number(value));

export async function importSnapshot(
  db: D1Database,
  input: unknown,
  options: ImportOptions,
) {
  // Entire envelope is verified before the first write; no HTTP mutation endpoint exposes this service.
  const bundle = await validateBundle(input);
  const manifest = canonical(bundle.manifest),
    manifestHash = await sha256(manifest);
  const snapshotId =
    "snapshot:" +
    (await sha256(
      bundle.manifest.repository +
        "\0" +
        bundle.manifest.commitSha +
        "\0" +
        manifestHash,
    ));
  const stats: ImportMetrics = {
    rowsRead: 0,
    rowsWritten: 0,
    durationMs: 0,
    databaseBytes: 0,
    chunksApplied: 0,
    chunksReplayed: 0,
  };
  const start = performance.now();
  const track = <T>(result: D1Result<T>) => {
    stats.rowsRead += result.meta.rows_read ?? 0;
    stats.rowsWritten += result.meta.rows_written ?? 0;
    stats.databaseBytes = Math.max(
      stats.databaseBytes,
      result.meta.size_after ?? 0,
    );
    if (!result.success) throw new SyncError("DATABASE_WRITE_FAILED");
  };
  const readOne = async <T>(statement: D1PreparedStatement) => {
    const result = await statement.all<T>();
    track(result);
    return result.results[0] ?? null;
  };
  if (
    !Number.isSafeInteger(options.expectedRevision) ||
    options.expectedRevision < 0
  )
    throw new SyncError("INVALID_REVISION");
  const checkpoint = await readOne<Checkpoint>(
    db.prepare(`SELECT c.snapshot_id,c.revision,s.commit_sha FROM sync_checkpoints c
    JOIN sync_snapshots s ON s.id=c.snapshot_id WHERE c.scope='main'`),
  );
  if (checkpoint?.snapshot_id === snapshotId)
    return {
      snapshotId,
      revision: checkpoint.revision,
      replayed: true,
      ...stats,
    };
  if ((checkpoint?.revision ?? 0) !== options.expectedRevision)
    throw new SyncError("CHECKPOINT_CONFLICT");
  if (
    checkpoint &&
    (!(await options.verifyAdvance(
      checkpoint.commit_sha,
      bundle.manifest.commitSha,
    )) ||
      checkpoint.commit_sha === bundle.manifest.commitSha)
  ) {
    throw new SyncError("NON_FORWARD_SNAPSHOT");
  }
  const prepare = (sql: string, ...values: (string | number | null)[]) =>
    db.prepare(sql).bind(...values);
  const assert = (condition: string, ...values: (string | number | null)[]) =>
    prepare(
      `INSERT INTO sync_assertions(value) SELECT CASE WHEN ${condition} THEN 1 ELSE 0 END`,
      ...values,
    );
  const clear = () => db.prepare("DELETE FROM sync_assertions");
  const revCondition = `(SELECT coalesce((SELECT revision FROM sync_checkpoints WHERE scope='main'),0))=?`;
  track(
    await prepare(
      `INSERT INTO sync_snapshots(id,repository,commit_sha,manifest_sha256,contract_version,expected_chunks,expected_revision,manifest_json)
    VALUES (?,?,?,?,1,?,?,?) ON CONFLICT(id) DO NOTHING`,
      snapshotId,
      bundle.manifest.repository,
      bundle.manifest.commitSha,
      manifestHash,
      bundle.chunks.length,
      options.expectedRevision,
      manifest,
    ).run(),
  );
  const stored = await readOne<{
    state: string;
    expected_revision: number;
    manifest_json: string;
  }>(
    prepare(
      "SELECT state,expected_revision,manifest_json FROM sync_snapshots WHERE id=?",
      snapshotId,
    ),
  );
  if (
    stored?.state !== "STAGING" ||
    stored.expected_revision !== options.expectedRevision ||
    stored.manifest_json !== manifest
  )
    throw new SyncError("SNAPSHOT_CONFLICT");
  function checkBudget() {
    if (stats.rowsWritten + 1000 >= (options.maxRowsWritten ?? 70_000) || stats.databaseBytes >= 350_000_000) {
      stats.durationMs = Math.round(performance.now() - start);
      throw new SyncError("LOCAL_WRITE_BUDGET_REACHED", stats);
    }
  }
  const identities = new Map<string, string>();
  for (const [index, rows] of bundle.chunks.entries()) {
    const metadata = bundle.manifest.chunks[index];
    if (!metadata) throw new SyncError("CHUNK_MISSING");
    const previous = await readOne<{
      content_sha256: string;
      row_count: number;
    }>(
      prepare(
        "SELECT content_sha256,row_count FROM sync_chunks WHERE snapshot_id=? AND chunk_index=?",
        snapshotId,
        index,
      ),
    );
    if (
      previous &&
      (previous.content_sha256 !== metadata.sha256 ||
        previous.row_count !== rows.length)
    )
      throw new SyncError("CHUNK_REPLAY_CONFLICT");
    // Re-resolve identifiers even for replayed chunks, so later event chunks can resume independently.
    const statements: D1PreparedStatement[] = [];
    for (const row of rows) {
      // Schema-4 chunks can already be marked complete when migration 0005 runs.
      // Fill only their missing versioned name from this validated bundle; never
      // mutate the global identity or a confirmed observation during replay.
      if (previous && row.kind === "company") {
        const legacy = await readOne<{ canonical_name: string | null }>(prepare(
          "SELECT canonical_name FROM company_versions WHERE company_id=? AND snapshot_id=?", row.id, snapshotId,
        ));
        if (legacy?.canonical_name === null) {
          checkBudget();
          const repaired = await db.batch([
            assert(`${revCondition} AND EXISTS(SELECT 1 FROM sync_snapshots WHERE id=? AND state='STAGING')`, options.expectedRevision, snapshotId),
            clear(),
            prepare("UPDATE company_versions SET canonical_name=? WHERE company_id=? AND snapshot_id=? AND canonical_name IS NULL", row.name, row.id, snapshotId),
          ]);
          repaired.forEach(track);
        }
      }
      if (row.kind === "job") {
        const keys = [row.jobKey, ...row.aliases];
        const existing = await prepare(
          `SELECT DISTINCT a.job_id,j.company_id FROM job_aliases a JOIN jobs j ON j.id=a.job_id
          WHERE a.alias_key IN (${keys.map(() => "?").join(",")})`,
          ...keys,
        ).all<{ job_id: string; company_id: string }>();
        stats.rowsRead += existing.meta.rows_read ?? 0;
        if (
          existing.results.length > 1 ||
          existing.results.some((value) => value.company_id !== row.companyId)
        )
          throw new SyncError("AMBIGUOUS_IDENTITY");
        const id =
          existing.results[0]?.job_id ??
          "job:" + (await sha256(row.companyId + "\0" + row.jobKey));
        for (const key of keys) identities.set(key, id);
      }
      if (!previous) statements.push(...(await rowStatements(row)));
    }
    if (previous) {
      stats.chunksReplayed++;
      continue;
    }
    checkBudget();
    const results = await db.batch([
      assert(
        `${revCondition} AND EXISTS(SELECT 1 FROM sync_snapshots WHERE id=? AND state='STAGING')`,
        options.expectedRevision,
        snapshotId,
      ),
      clear(),
      ...statements,
      prepare(
        "INSERT INTO sync_chunks(snapshot_id,chunk_index,content_sha256,row_count) VALUES (?,?,?,?)",
        snapshotId,
        index,
        metadata.sha256,
        rows.length,
      ),
    ]);
    results.forEach(track);
    stats.chunksApplied++;
    if (
      options.stopAfterChunks !== undefined &&
      stats.chunksApplied >= options.stopAfterChunks
    )
      throw new SyncError("IMPORT_INTERRUPTED");
  }
  const now = new Date().toISOString().replace(/\.\d{3}Z$/, "Z");
  // A CHECK assertion aborts the entire D1 batch on a failed CAS, including the publication and audit.
  const final = await db.batch([
    assert(revCondition, options.expectedRevision),
    clear(),
    prepare(
      "UPDATE sync_snapshots SET state='CONFIRMED',confirmed_at=?,published_revision=? WHERE id=? AND state='STAGING'",
      now,
      options.expectedRevision + 1,
      snapshotId,
    ),
    prepare(
      `INSERT INTO sync_checkpoints(scope,snapshot_id,revision,updated_at) VALUES ('main',?,?,?)
      ON CONFLICT(scope) DO UPDATE SET snapshot_id=excluded.snapshot_id,revision=excluded.revision,updated_at=excluded.updated_at`,
      snapshotId,
      options.expectedRevision + 1,
      now,
    ),
    prepare(
      `INSERT INTO audit_log(id,event_code,actor_ref,entity_type,entity_id,snapshot_id,content_sha256)
      VALUES (?,'SNAPSHOT_CONFIRMED','local-cli','snapshot',?,?,?)`,
      "audit:" + snapshotId,
      snapshotId,
      snapshotId,
      manifestHash,
    ),
    prepare(
      "UPDATE sync_snapshots SET state='FAILED' WHERE state='STAGING' AND id<>? AND expected_revision<=?",
      snapshotId,
      options.expectedRevision,
    ),
  ]);
  final.forEach(track);
  stats.durationMs = Math.round(performance.now() - start);
  return {
    snapshotId,
    revision: options.expectedRevision + 1,
    replayed: false,
    ...stats,
  };

  async function rowStatements(
    row: SnapshotRow,
  ): Promise<D1PreparedStatement[]> {
    const p = [
      row.sourcePath,
      row.sourceSha256,
      bundle.manifest.observedAt,
    ] as const;
    if (row.kind === "company")
      return [
        prepare(
          "INSERT INTO companies(id,config_id,canonical_name) VALUES (?,?,?) ON CONFLICT(id) DO NOTHING",
          row.id,
          row.configId,
          row.name,
        ),
        prepare(
          "INSERT INTO company_versions(company_id,snapshot_id,canonical_name,tier,monitoring_priority,career_url,membership,source_path,source_sha256,observed_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
          row.id,
          snapshotId,
          row.name,
          row.tier,
          row.priority,
          row.careerUrl,
          row.membership,
          ...p,
        ),
      ];
    if (row.kind === "source")
      return [
        prepare(
          "INSERT INTO sources(id,company_id,source_key) VALUES (?,?,?) ON CONFLICT(id) DO NOTHING",
          row.id,
          row.companyId,
          row.sourceKey,
        ),
        prepare(
          `INSERT INTO source_versions(source_id,snapshot_id,ats_family,inventory_url,coverage,source_path,source_sha256,observed_at,generated_at,coverage_source_path,coverage_source_sha256)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)`,
          row.id,
          snapshotId,
          row.family,
          row.inventoryUrl,
          row.coverage,
          ...p,
          row.generatedAt,
          row.coveragePath,
          row.coverageSha256,
        ),
      ];
    const jobId = identities.get("jobKey" in row ? row.jobKey : "");
    if (
      (row.kind === "job" || row.kind === "semantic" || row.kind === "user") &&
      !jobId
    )
      throw new SyncError("MISSING_JOB_IDENTITY");
    if (row.kind === "job" && jobId)
      return [
        prepare(
          "INSERT INTO jobs(id,company_id,origin_job_key) VALUES (?,?,?) ON CONFLICT(id) DO NOTHING",
          jobId,
          row.companyId,
          row.jobKey,
        ),
        ...[row.jobKey, ...row.aliases].map((key) =>
          prepare(
            `INSERT INTO job_aliases(alias_key,job_id,snapshot_id,resolution) VALUES (?,?,?,?) ON CONFLICT(alias_key) DO NOTHING`,
            key,
            jobId,
            snapshotId,
            key === row.jobKey ? "EXACT_KEY" : "PYTHON_RESOLVED",
          ),
        ),
        ...[row.jobKey, ...row.aliases].map((key) =>
          prepare(
            "INSERT INTO snapshot_job_aliases(snapshot_id,alias_key,job_id) VALUES (?,?,?)",
            snapshotId,
            key,
            jobId,
          ),
        ),
        prepare(
          `INSERT INTO job_versions(job_id,company_id,snapshot_id,source_id,batch,upstream_source_id,title,location,canonical_url,apply_url,fingerprint,lifecycle,first_seen_at,last_seen_at,source_path,source_sha256,observed_at,job_key,sort_key,analysis_status,analysis_method,needs_analysis,worker_eligible,hard_exclusion_reason,fit_score,reportable,effective_user_decision,technical_status)
        VALUES (${Array(28).fill("?").join(",")})`,
          jobId,
          row.companyId,
          snapshotId,
          row.sourceId,
          row.batch,
          row.upstreamSourceId,
          row.title,
          row.location,
          row.canonicalUrl,
          row.applyUrl,
          row.fingerprint,
          row.lifecycle,
          row.firstSeenAt,
          row.lastSeenAt,
          ...p,
          row.jobKey,
          row.sortKey,
          row.analysisStatus,
          row.analysisMethod,
          bool(row.needsAnalysis),
          bool(row.workerEligible),
          row.hardExclusionReason,
          row.fitScore,
          bool(row.reportable),
          row.effectiveDecision,
          row.technicalStatus,
        ),
      ];
    if (row.kind === "semantic" && jobId) {
      const id = "review:" + (await sha256(jobId + "\0" + row.resultSha256));
      return [
        prepare(
          `INSERT INTO semantic_reviews(id,job_id,snapshot_id,fingerprint,analysis_method,decision,fit_score,reportable,evidence_state,analyzed_at,source_path,source_sha256,result_sha256)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(job_id,result_sha256) DO NOTHING`,
          id,
          jobId,
          snapshotId,
          row.fingerprint,
          row.method,
          row.decision,
          row.fitScore,
          bool(row.reportable),
          row.evidenceState,
          row.analyzedAt,
          row.sourcePath,
          row.sourceSha256,
          row.resultSha256,
        ),
        prepare(
          "INSERT INTO snapshot_semantic_reviews(snapshot_id,review_id) VALUES (?,?) ON CONFLICT DO NOTHING",
          snapshotId,
          id,
        ),
      ];
    }
    if (row.kind === "user" && jobId) {
      const id = "decision:" + (await sha256(jobId + "\0" + row.resultSha256));
      return [
        prepare(
          `INSERT INTO user_decisions(id,job_id,snapshot_id,decision,fingerprint,rejection_reason,decided_at,source_path,source_sha256,result_sha256)
        VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(job_id,result_sha256) DO NOTHING`,
          id,
          jobId,
          snapshotId,
          row.decision,
          row.fingerprint,
          row.rejectionReason,
          row.decidedAt,
          row.sourcePath,
          row.sourceSha256,
          row.resultSha256,
        ),
        prepare(
          "INSERT INTO snapshot_user_decisions(snapshot_id,decision_id) VALUES (?,?) ON CONFLICT DO NOTHING",
          snapshotId,
          id,
        ),
      ];
    }
    if (row.kind === "pipeline")
      return [
        prepare(
          `INSERT INTO pipeline_runs(id,snapshot_id,pipeline_run_id,health_status,collection_status,daily_complete,full_semantic_complete,completed_at,source_path,source_sha256)
      VALUES (?,?,?,?,?,?,?,?,?,?)`,
          "pipeline:" + snapshotId,
          snapshotId,
          row.runId,
          row.healthStatus,
          row.collectionStatus,
          bool(row.dailyComplete),
          bool(row.fullSemanticComplete),
          row.generatedAt,
          row.sourcePath,
          row.sourceSha256,
        ),
      ];
    throw new SyncError("UNSUPPORTED_ROW");
  }
}
