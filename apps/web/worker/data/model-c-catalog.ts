// Inactive Model C read service. Deliberately NOT imported by worker/index.ts.
// CATALOG is public metadata only; PERSONAL decisions and references require a
// separate, owner-authenticated reader and verified cross-DB receipt.
import { z } from 'zod';
import { canonical } from '../../shared/canonical';

export class ModelCReadError extends Error {
  constructor(public readonly code: string, public readonly status: number) { super(code); }
}

export const modelCCatalogQuerySchema = z.strictObject({
  q: z.string().trim().max(120).default(''),
  companyId: z.string().min(1).max(200).optional(),
  kind: z.enum(['OPPORTUNITY', 'AI_QUEUE']).optional(),
  batch: z.enum(['jw1', 'jw2', 'jw3', 'jw4']).optional(),
  lifecycle: z.enum(['NEW', 'STILL_OPEN', 'UPDATED']).optional(),
  needsAnalysis: z.enum(['true','false']).optional(),
  limit: z.coerce.number().int().min(1).max(100).default(25),
  cursor: z.string().max(6000).optional(),
});
export type ModelCCatalogQuery = z.input<typeof modelCCatalogQuerySchema>;

const jobIdSchema = z.string().regex(/^job:[a-f0-9]{64}$/);
const cursorSchema = z.strictObject({
  revision: z.number().int().positive(),
  runId: z.string().min(1),
  lastId: jobIdSchema,
  filters: z.string(),
});
type Cursor = z.infer<typeof cursorSchema>;
const encodeCursor = (cursor: Cursor): string =>
  btoa(String.fromCharCode(...new TextEncoder().encode(JSON.stringify(cursor))))
    .replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
const decodeCursor = (encoded: string): Cursor => {
  try {
    const raw = atob(encoded.replace(/-/g, '+').replace(/_/g, '/'));
    return cursorSchema.parse(JSON.parse(new TextDecoder().decode(
      Uint8Array.from(raw, c => c.charCodeAt(0)),
    )));
  } catch {
    throw new ModelCReadError('INVALID_CURSOR', 400);
  }
};

type Head = {
  syncRevision: number; contentRevision: number; ledgerRevision: number;
  runId: string; observedCommit: string; contentDigest: string; ledgerDigest: string;
  contentOriginCommit: string; identityCount: number; mappingCount: number;
  state: string;
};
async function publishedHead(db: D1Database): Promise<Head | null> {
  const version = await db.prepare("SELECT version FROM model_c_schema WHERE scope='CATALOG'")
    .first<number>('version');
  if (version !== 4) throw new ModelCReadError('CATALOG_SCHEMA_MISMATCH', 503);
  const head = await db.prepare(`SELECT h.sync_revision AS syncRevision,
      h.content_revision AS contentRevision,h.ledger_revision AS ledgerRevision,
      h.run_id AS runId,r.observed_commit AS observedCommit,r.state,
      c.content_digest AS contentDigest,c.origin_commit AS contentOriginCommit,
      l.ledger_digest AS ledgerDigest,l.identity_count AS identityCount,
      l.mapping_count AS mappingCount
    FROM catalog_head h JOIN catalog_runs r ON r.id=h.run_id
    JOIN catalog_content_revisions c ON c.revision=h.content_revision
    JOIN catalog_ledger_checkpoints l ON l.revision=h.ledger_revision
    WHERE h.scope='catalog'`).first<Head>();
  if (head && head.state !== 'PUBLISHED')
    throw new ModelCReadError('CATALOG_UNTRUSTED_HEAD', 503);
  return head ?? null;
}
async function unchanged(db: D1Database, before: Head | null) {
  const after = await publishedHead(db);
  if (after?.syncRevision !== before?.syncRevision || after?.runId !== before?.runId)
    throw new ModelCReadError('CATALOG_CHANGED', 409);
}
function publicHead(head: Head | null) {
  if (!head) return null;
  const { state: _state, ...safe } = head;
  return safe;
}

export async function getModelCCatalogSnapshot(db: D1Database) {
  const head = await publishedHead(db);
  if (!head) return { snapshot: null, productionAccess: false as const };
  const companyRows = await db.prepare(`SELECT company_id AS id,display_name AS name,
    membership FROM catalog_visible_companies ORDER BY display_name,company_id LIMIT 501`)
    .all<{id:string;name:string;membership:string}>();
  const count = await db.prepare('SELECT count(*) AS total FROM catalog_visible_vacancies')
    .first<number>('total');
  await unchanged(db, head);
  return {
    snapshot: { ...publicHead(head), currentJobs: count ?? 0, companies: companyRows.results.slice(0, 500),
      companiesTruncated: companyRows.results.length > 500 },
    productionAccess: false as const,
  };
}
type JobRow = {
  id: string; jobKey: string; companyId: string; company: string;
  sourceId: string | null; kind: 'OPPORTUNITY' | 'AI_QUEUE';
  lifecycle: 'NEW' | 'STILL_OPEN' | 'UPDATED';
  title: string | null; location: string | null; canonicalUrl: string | null;
  applyUrl: string | null; fingerprint: string | null; batch: string | null;
  firstSeenAt: string | null; lastSeenAt: string | null;
  needsAnalysis: number | null; workerEligible: number | null; technicalStatus: string | null;
  originCommit: string; originPath: string; originSha256: string;
};
const fields = `v.job_id AS id,i.origin_job_key AS jobKey,v.company_id AS companyId,
    c.display_name AS company,v.source_id AS sourceId,v.kind,v.lifecycle,v.title,
    v.location,v.canonical_url AS canonicalUrl,v.apply_url AS applyUrl,
    v.fingerprint,v.batch,v.first_seen_at AS firstSeenAt,v.last_seen_at AS lastSeenAt,
    v.needs_analysis AS needsAnalysis,v.worker_eligible AS workerEligible,
    v.technical_status AS technicalStatus,o.commit_sha AS originCommit,
    o.source_path AS originPath,o.source_sha256 AS originSha256`;
const joins = `FROM catalog_visible_vacancies v
  JOIN catalog_vacancy_identity i ON i.id=v.job_id
  JOIN catalog_visible_companies c ON c.company_id=v.company_id
  JOIN catalog_origins o ON o.id=v.origin_id`;
const mapJob = (r: JobRow) => ({
  ...r, needsAnalysis: r.needsAnalysis === null ? null : r.needsAnalysis === 1,
  workerEligible: r.workerEligible === null ? null : r.workerEligible === 1,
});

export async function listModelCCatalogJobs(db: D1Database, input: ModelCCatalogQuery = {}) {
  const query = modelCCatalogQuerySchema.parse(input);
  const head = await publishedHead(db);
  if (!head) return { snapshot: null, items: [], total: 0, nextCursor: null, productionAccess: false as const };
  const { cursor, limit, ...filters } = query;
  const signature = canonical(filters);
  const after = cursor ? decodeCursor(cursor) : null;
  if (after && (after.revision !== head.syncRevision || after.runId !== head.runId))
    throw new ModelCReadError('CATALOG_CHANGED', 409);
  if (after && after.filters !== signature)
    throw new ModelCReadError('CURSOR_FILTER_MISMATCH', 400);
  const conditions: string[] = [], args: (string | number)[] = [];
  if (query.q) {
    conditions.push('(instr(lower(v.title),lower(?))>0 OR instr(lower(c.display_name),lower(?))>0 OR instr(lower(v.location),lower(?))>0)');
    args.push(query.q, query.q, query.q);
  }
  if (query.companyId) { conditions.push('v.company_id=?'); args.push(query.companyId); }
  if (query.kind) { conditions.push('v.kind=?'); args.push(query.kind); }
  if (query.batch) { conditions.push('v.batch=?'); args.push(query.batch); }
  if (query.lifecycle) { conditions.push('v.lifecycle=?'); args.push(query.lifecycle); }
  if (query.needsAnalysis) { conditions.push('v.needs_analysis=?'); args.push(query.needsAnalysis==='true'?1:0); }
  const where = conditions.length ? ' WHERE ' + conditions.join(' AND ') : '';
  const total = await db.prepare(`SELECT count(*) AS n ${joins}${where}`)
    .bind(...args).first<number>('n');
  const pagination = after ? (conditions.length ? ' AND ' : ' WHERE ') + 'v.job_id>?' : '';
  const values = after ? [...args, after.lastId, limit + 1] : [...args, limit + 1];
  const page = await db.prepare(`SELECT ${fields} ${joins}${where}${pagination}
    ORDER BY v.job_id LIMIT ?`).bind(...values).all<JobRow>();
  await unchanged(db, head);
  const selected = page.results.slice(0, limit);
  const last = selected.at(-1);
  return {
    snapshot: publicHead(head),
    items: selected.map(mapJob),
    total: total ?? 0,
    nextCursor: page.results.length > limit && last
      ? encodeCursor({revision: head.syncRevision,runId:head.runId,lastId:last.id,filters:signature})
      : null,
    productionAccess: false as const,
  };
}

export async function getModelCCatalogJob(db: D1Database, id: string, expectedRevision: number) {
  const jobId = jobIdSchema.parse(id);
  if (!Number.isSafeInteger(expectedRevision) || expectedRevision < 1)
    throw new ModelCReadError('INVALID_REVISION', 400);
  const head = await publishedHead(db);
  if (!head) throw new ModelCReadError('NO_PUBLISHED_CATALOG', 404);
  if (head.syncRevision !== expectedRevision) throw new ModelCReadError('CATALOG_CHANGED', 409);
  const row = await db.prepare(`SELECT ${fields} ${joins} WHERE v.job_id=?`)
    .bind(jobId).first<JobRow>();
  if (!row) {
    await unchanged(db, head);
    throw new ModelCReadError('JOB_NOT_CURRENT', 404);
  }
  const aliases = await db.prepare('SELECT alias_key FROM catalog_aliases WHERE job_id=? ORDER BY alias_key LIMIT 51')
    .bind(jobId).all<{alias_key:string}>();
  await unchanged(db, head);
  return {
    snapshot: publicHead(head), job: mapJob(row),
    aliases: aliases.results.slice(0, 50).map(x => x.alias_key),
    aliasesTruncated: aliases.results.length > 50,
    productionAccess: false as const,
  };
}
