import { z } from "zod";
import {
  jobsQuerySchema,
  jobViewSchema,
  snapshotViewSchema,
  detailResponseSchema,
} from "../../shared/queries";
import type { JobsQuery, JobView } from "../../shared/queries";
import { canonical } from "../../shared/canonical";

export class QueryError extends Error {
  constructor(
    public readonly code: string,
    public readonly status: number,
  ) {
    super(code);
  }
}
const toBool = (value: unknown): boolean | null =>
  value === null || value === undefined ? null : Boolean(value);
const columns = `v.job_id AS id,coalesce(v.job_key,j.origin_job_key) AS jobKey,v.company_id AS companyId,c.canonical_name AS company,
  v.title,v.location,v.batch,v.lifecycle,v.fingerprint,v.canonical_url AS canonicalUrl,v.apply_url AS applyUrl,
  v.first_seen_at AS firstSeenAt,v.last_seen_at AS lastSeenAt,v.analysis_status AS analysisStatus,v.analysis_method AS analysisMethod,
  v.needs_analysis AS needsAnalysis,v.worker_eligible AS workerEligible,v.hard_exclusion_reason AS hardExclusionReason,
  v.fit_score AS fitScore,v.reportable,v.effective_user_decision AS decision,v.technical_status AS technicalStatus,
  sv.coverage,v.source_path AS sourcePath,v.source_sha256 AS sourceSha256`;
const joins = `FROM job_versions v JOIN jobs j ON j.id=v.job_id JOIN companies c ON c.id=v.company_id
  LEFT JOIN source_versions sv ON sv.source_id=v.source_id AND sv.snapshot_id=v.snapshot_id`;
function job(row: Record<string, unknown>): JobView {
  return jobViewSchema.parse({
    ...row,
    needsAnalysis: toBool(row.needsAnalysis),
    workerEligible: toBool(row.workerEligible),
    reportable: toBool(row.reportable),
  });
}
const cursorSchema = z.strictObject({
  snapshotId: z.string(),
  sortKey: z.string().max(2200),
  id: z.string(),
  filters: z.string(),
});
function encodeCursor(value: z.infer<typeof cursorSchema>): string {
  return btoa(
    String.fromCharCode(...new TextEncoder().encode(JSON.stringify(value))),
  )
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
}
function decodeCursor(value: string) {
  try {
    return cursorSchema.parse(
      JSON.parse(
        new TextDecoder().decode(
          Uint8Array.from(
            atob(value.replace(/-/g, "+").replace(/_/g, "/")),
            (c) => c.charCodeAt(0),
          ),
        ),
      ),
    );
  } catch {
    throw new QueryError("INVALID_CURSOR", 400);
  }
}

// HTTP and future MCP adapters both call this service: no Request/Response, UI or provider SDK dependency.
export async function getSnapshot(db: D1Database) {
  const pending =
    (await db
      .prepare("SELECT count(*) AS n FROM sync_snapshots WHERE state='STAGING'")
      .first<number>("n")) ?? 0;
  const row = await db
    .prepare(
      `SELECT s.id,s.commit_sha AS commitSha,c.revision,s.manifest_json,s.confirmed_at AS confirmedAt,
    p.collection_status AS collectionStatus,p.health_status AS healthStatus,p.daily_complete AS dailyComplete,p.full_semantic_complete AS fullSemanticComplete
    FROM sync_checkpoints c JOIN sync_snapshots s ON s.id=c.snapshot_id AND s.state='CONFIRMED'
    LEFT JOIN pipeline_runs p ON p.snapshot_id=s.id WHERE c.scope='main'`,
    )
    .first<Record<string, unknown>>();
  if (!row)
    return {
      snapshot: null,
      pendingImports: pending,
      productionAccess: false as const,
    };
  const manifest = JSON.parse(String(row.manifest_json));
  const dates = await db
    .prepare(
      "SELECT min(generated_at) AS oldestSourceAt,max(generated_at) AS newestSourceAt FROM source_versions WHERE snapshot_id=?",
    )
    .bind(String(row.id))
    .first();
  const companies = await db
    .prepare(
      `SELECT DISTINCT c.id,c.canonical_name AS name FROM companies c
    JOIN job_versions v ON v.company_id=c.id WHERE v.snapshot_id=? ORDER BY c.canonical_name`,
    )
    .bind(String(row.id))
    .all<{ id: string; name: string }>();
  const count =
    (await db
      .prepare("SELECT count(*) AS n FROM job_versions WHERE snapshot_id=?")
      .bind(String(row.id))
      .first<number>("n")) ?? 0;
  const { manifest_json: _manifest, ...fields } = row;
  return {
    snapshot: snapshotViewSchema.parse({
      ...fields,
      ...dates,
      observedAt: manifest.observedAt,
      jobCount: count,
      pendingImports: pending,
      companies: companies.results,
      dailyComplete: toBool(row.dailyComplete),
      fullSemanticComplete: toBool(row.fullSemanticComplete),
    }),
    pendingImports: pending,
    productionAccess: false as const,
  };
}

export async function listJobs(db: D1Database, input: JobsQuery) {
  const query = jobsQuerySchema.parse(input);
  const start = performance.now();
  let rowsRead = 0;
  const checkpoint = await db
    .prepare("SELECT snapshot_id FROM sync_checkpoints WHERE scope='main'")
    .first<{ snapshot_id: string }>();
  if (!checkpoint)
    return {
      snapshotId: null,
      items: [],
      total: 0,
      nextCursor: null,
      metrics: { rowsRead, durationMs: 0 },
    };
  const { cursor, ...filters } = query;
  const signature = canonical(filters);
  const after = cursor ? decodeCursor(cursor) : null;
  if (after && after.snapshotId !== checkpoint.snapshot_id)
    throw new QueryError("SNAPSHOT_CHANGED", 409);
  if (after && after.filters !== signature)
    throw new QueryError("CURSOR_FILTER_MISMATCH", 400);
  const where = ["v.snapshot_id=?"];
  const values: (string | number)[] = [checkpoint.snapshot_id];
  if (query.q) {
    where.push(
      "(v.title LIKE ? ESCAPE '\\' OR c.canonical_name LIKE ? ESCAPE '\\' OR v.location LIKE ? ESCAPE '\\')",
    );
    const value = "%" + query.q.replace(/[\\%_]/g, "\\$&") + "%";
    values.push(value, value, value);
  }
  if (query.company) {
    where.push("v.company_id=?");
    values.push(query.company);
  }
  if (query.batch) {
    where.push("v.batch=?");
    values.push(query.batch);
  }
  if (query.lifecycle === "OPEN")
    where.push("v.lifecycle IN ('NEW','STILL_OPEN','UPDATED')");
  else if (query.lifecycle && query.lifecycle !== "ALL") {
    where.push("v.lifecycle=?");
    values.push(query.lifecycle);
  }
  if (query.decision === "NONE")
    where.push("v.effective_user_decision IS NULL");
  else if (query.decision) {
    where.push("v.effective_user_decision=?");
    values.push(query.decision);
  }
  const assessments = {
    pending: "v.needs_analysis=1",
    hard_rule: "v.hard_exclusion_reason IS NOT NULL",
    semantic_not_reportable:
      "v.analysis_method LIKE 'chatgpt_semantic%' AND v.reportable=0",
    reportable: "v.reportable=1",
    unprojected: "v.analysis_status IS NULL",
  };
  if (query.assessment) where.push(assessments[query.assessment]);
  const counts = await db
    .prepare(`SELECT count(*) AS n ${joins} WHERE ${where.join(" AND ")}`)
    .bind(...values)
    .all<{ n: number }>();
  rowsRead += counts.meta.rows_read ?? 0;
  if (after) {
    where.push("(v.sort_key,v.job_id)>(?,?)");
    values.push(after.sortKey, after.id);
  }
  const page = await db
    .prepare(
      `SELECT ${columns},v.sort_key AS sortKey ${joins}
    WHERE ${where.join(" AND ")} ORDER BY v.sort_key,v.job_id LIMIT ?`,
    )
    .bind(...values, query.limit + 1)
    .all<Record<string, unknown>>();
  rowsRead += page.meta.rows_read ?? 0;
  const visible = page.results.slice(0, query.limit);
  const last = visible.at(-1);
  return {
    snapshotId: checkpoint.snapshot_id,
    total: counts.results[0]?.n ?? 0,
    items: visible.map(({ sortKey: _sort, ...row }) => job(row)),
    nextCursor:
      page.results.length > query.limit && last
        ? encodeCursor({
            snapshotId: checkpoint.snapshot_id,
            sortKey: String(last.sortKey),
            id: String(last.id),
            filters: signature,
          })
        : null,
    metrics: { rowsRead, durationMs: Math.round(performance.now() - start) },
  };
}

export async function getJob(
  db: D1Database,
  id: string,
  expectedSnapshot: string,
) {
  const checkpoint = await db
    .prepare(
      "SELECT snapshot_id,revision FROM sync_checkpoints WHERE scope='main'",
    )
    .first<{ snapshot_id: string; revision: number }>();
  if (!checkpoint) throw new QueryError("NO_CONFIRMED_SNAPSHOT", 404);
  if (checkpoint.snapshot_id !== expectedSnapshot)
    throw new QueryError("SNAPSHOT_CHANGED", 409);
  const row = await db
    .prepare(`SELECT ${columns} ${joins} WHERE v.snapshot_id=? AND v.job_id=?`)
    .bind(checkpoint.snapshot_id, id)
    .first<Record<string, unknown>>();
  if (!row) throw new QueryError("JOB_NOT_FOUND", 404);
  const aliases = await db
    .prepare(
      `SELECT alias_key FROM snapshot_job_aliases WHERE job_id=? AND snapshot_id=? ORDER BY alias_key`,
    )
    .bind(id, checkpoint.snapshot_id)
    .all<{ alias_key: string }>();
  const reviews = await db
    .prepare(
      `SELECT r.id,r.analysis_method AS method,r.decision,r.fit_score AS fitScore,r.reportable,
    r.evidence_state AS evidenceState,r.analyzed_at AS analyzedAt,r.fingerprint,r.source_path AS sourcePath,r.source_sha256 AS sourceSha256,origin.commit_sha AS commitSha
    FROM semantic_reviews r JOIN sync_snapshots origin ON origin.id=r.snapshot_id
    WHERE r.job_id=? AND EXISTS(SELECT 1 FROM snapshot_semantic_reviews l JOIN sync_snapshots s ON s.id=l.snapshot_id
      WHERE l.review_id=r.id AND s.state='CONFIRMED' AND s.published_revision<=?) ORDER BY r.analyzed_at DESC,r.id LIMIT 50`,
    )
    .bind(id, checkpoint.revision)
    .all<Record<string, unknown>>();
  const decisions = await db
    .prepare(
      `SELECT r.id,r.decision,r.rejection_reason AS rejectionReason,r.decided_at AS decidedAt,
    r.source_path AS sourcePath,r.source_sha256 AS sourceSha256,origin.commit_sha AS commitSha
    FROM user_decisions r JOIN sync_snapshots origin ON origin.id=r.snapshot_id
    WHERE r.job_id=? AND EXISTS(SELECT 1 FROM snapshot_user_decisions l JOIN sync_snapshots s ON s.id=l.snapshot_id
      WHERE l.decision_id=r.id AND s.state='CONFIRMED' AND s.published_revision<=?) ORDER BY r.decided_at DESC,r.id LIMIT 50`,
    )
    .bind(id, checkpoint.revision)
    .all();
  return detailResponseSchema.parse({
    snapshotId: checkpoint.snapshot_id,
    job: job(row),
    aliases: aliases.results.map((v) => v.alias_key),
    reviews: reviews.results.map((value) => ({
      ...value,
      reportable: toBool(value.reportable),
    })),
    decisions: decisions.results,
  });
}
