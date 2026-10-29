import { z } from 'zod';
import { manifestSchema, rejectionReasons } from './contracts';
import { canonical, sha256 } from './canonical';

const text = z.string().max(1000);
const nullableText = text.nullable();
const hash = z.string().regex(/^[a-f0-9]{64}$/);
const nullableBool = z.boolean().nullable();
const nullableNumber = z.number().finite().nullable();
export const batchSchema = z.enum(['jw1', 'jw2', 'jw3', 'jw4']);
export const lifecycleSchema = z.enum([
  'NEW',
  'STILL_OPEN',
  'UPDATED',
  'CLOSED',
  'UNKNOWN',
]);
export const decisionSchema = z.enum([
  'TO_REVIEW',
  'INTERESTED',
  'APPLIED',
  'NOT_INTERESTED',
]);
const provenance = { sourcePath: z.string().max(240), sourceSha256: hash };
const url = z
  .url()
  .refine((value) => {
    const u = new URL(value);
    return u.protocol === 'https:' && !u.username && !u.password;
  })
  .nullable();
export const rowSchema = z.discriminatedUnion('kind', [
  z.strictObject({
    kind: z.literal('company'),
    id: text,
    name: text,
    configId: nullableText,
    tier: nullableText,
    priority: nullableText,
    careerUrl: url,
    membership: z.enum(['ACTIVE', 'CANDIDATE', 'HISTORICAL']),
    ...provenance,
  }),
  z.strictObject({
    kind: z.literal('source'),
    id: text,
    companyId: text,
    sourceKey: text,
    family: text,
    inventoryUrl: url,
    coverage: z
      .enum(['VERIFIED', 'PARTIAL', 'FAILED', 'NOT_CHECKED'])
      .nullable(),
    generatedAt: nullableText,
    coveragePath: text,
    coverageSha256: hash,
    ...provenance,
  }),
  z.strictObject({
    kind: z.literal('job'),
    jobKey: text,
    aliases: z.array(text).max(50),
    companyId: text,
    sourceId: nullableText,
    upstreamSourceId: text,
    batch: batchSchema.nullable(),
    title: nullableText,
    location: nullableText,
    canonicalUrl: url,
    applyUrl: url,
    fingerprint: nullableText,
    lifecycle: lifecycleSchema,
    firstSeenAt: nullableText,
    lastSeenAt: nullableText,
    analysisStatus: nullableText,
    analysisMethod: nullableText,
    needsAnalysis: nullableBool,
    workerEligible: nullableBool,
    hardExclusionReason: nullableText,
    fitScore: nullableNumber,
    reportable: nullableBool,
    effectiveDecision: decisionSchema.nullable(),
    technicalStatus: nullableText,
    sortKey: z.string().max(2200),
    ...provenance,
  }),
  z.strictObject({
    kind: z.literal('semantic'),
    jobKey: text,
    resultSha256: hash,
    fingerprint: text,
    method: z.enum([
      'chatgpt_semantic',
      'chatgpt_semantic_title_metadata',
      'chatgpt_semantic_full_jd',
      'chatgpt_semantic_triage',
    ]),
    decision: nullableText,
    fitScore: nullableNumber,
    reportable: nullableBool,
    evidenceState: z.enum(['FULL', 'HISTORICAL_SHORTENED']),
    analyzedAt: text,
    ...provenance,
  }),
  z.strictObject({
    kind: z.literal('user'),
    jobKey: text,
    resultSha256: hash,
    fingerprint: nullableText,
    decision: decisionSchema,
    rejectionReason: z.enum(rejectionReasons).nullable(),
    decidedAt: text,
    ...provenance,
  }),
  z.strictObject({
    kind: z.literal('pipeline'),
    runId: nullableText,
    healthStatus: nullableText,
    collectionStatus: nullableText,
    dailyComplete: nullableBool,
    fullSemanticComplete: nullableBool,
    generatedAt: nullableText,
    ...provenance,
  }),
]);
export type SnapshotRow = z.infer<typeof rowSchema>;
export const bundleSchema = z.strictObject({
  manifest: manifestSchema,
  chunks: z.array(z.array(rowSchema).min(1)).min(1),
});
export type SnapshotBundle = z.infer<typeof bundleSchema>;

export function statementsFor(row: SnapshotRow): number {
  return row.kind === 'job'
    ? 4 + 2 * row.aliases.length
    : row.kind === 'pipeline'
      ? 1
      : 2;
}

export async function prepareBundle(
  extracted: unknown,
): Promise<SnapshotBundle> {
  const raw = z
    .strictObject({
      commitSha: text,
      observedAt: text,
      files: manifestSchema.shape.files,
      rows: z.array(z.record(z.string(), z.unknown())),
    })
    .parse(extracted);
  const rows: SnapshotRow[] = [];
  for (const original of raw.rows) {
    const { hashInput, ...row } = original;
    if (row.kind === 'semantic' || row.kind === 'user')
      row.resultSha256 = await sha256(canonical(hashInput));
    rows.push(rowSchema.parse(row));
  }
  const chunks: SnapshotRow[][] = [];
  let chunk: SnapshotRow[] = [],
    weight = 0;
  for (const row of rows) {
    const w = statementsFor(row);
    if (w > 16) throw new Error('ALIAS_GROUP_EXCEEDS_CHUNK_LIMIT');
    if (
      weight + w > 16 ||
      new TextEncoder().encode(canonical([...chunk, row])).byteLength > 120_000
    ) {
      if (chunk.length) chunks.push(chunk);
      chunk = [];
      weight = 0;
    }
    chunk.push(row);
    weight += w;
  }
  if (chunk.length) chunks.push(chunk);
  return bundleSchema.parse({
    manifest: {
      version: 1,
      repository: 'giacodmr/job-watch-milano',
      commitSha: raw.commitSha,
      observedAt: raw.observedAt,
      files: raw.files,
      chunks: await Promise.all(
        chunks.map(async (rows, index) => ({
          index,
          rows: rows.length,
          sha256: await sha256(canonical(rows)),
        })),
      ),
    },
    chunks,
  });
}

export const requiredFiles = [
  'companies_job_watch_v2.json',
  'company_candidates.json',
  'job_watch_batches.json',
  'job_watch_rules.json',
  'amazon_target_check.json',
  'daily_worklist.json',
  'job_watch_healthcheck.json',
  'job_watch_run_state.json',
  'pipeline_execution.json',
  'daily_activity.json',
  ...['jw1', 'jw2', 'jw3', 'jw4'].flatMap((batch) =>
    ['ats_mapping', 'current_jobs', 'job_memory'].map(
      (stem) => `${stem}_${batch}.json`,
    ),
  ),
];

export async function validateBundle(input: unknown): Promise<SnapshotBundle> {
  const bundle = bundleSchema.parse(input);
  const files = new Map(
    bundle.manifest.files.map((file) => [file.path, file.sha256]),
  );
  if (
    requiredFiles.some((path) => !files.has(path)) ||
    bundle.chunks.length !== bundle.manifest.chunks.length
  )
    throw new Error('INCOMPLETE_MANIFEST');
  for (const [index, rows] of bundle.chunks.entries()) {
    const metadata = bundle.manifest.chunks[index];
    if (
      !metadata ||
      metadata.rows !== rows.length ||
      metadata.sha256 !== (await sha256(canonical(rows)))
    )
      throw new Error('CHUNK_HASH_MISMATCH');
    if (
      rows.reduce((n, row) => n + statementsFor(row), 0) > 16 ||
      new TextEncoder().encode(canonical(rows)).byteLength > 128 * 1024
    )
      throw new Error('CHUNK_LIMIT');
    for (const row of rows) {
      if (files.get(row.sourcePath) !== row.sourceSha256)
        throw new Error('UNBOUND_PROVENANCE');
      if (
        row.kind === 'source' &&
        files.get(row.coveragePath) !== row.coverageSha256
      )
        throw new Error('UNBOUND_COVERAGE');
    }
  }
  const rows = bundle.chunks.flat();
  const companies = new Map<string,string>();
  const sources = new Map<string,string>();
  const keys = new Set<string>();
  for (const row of rows) {
    if (row.kind === 'company') {
      if (companies.has(row.id)) throw new Error('DUPLICATE_COMPANY');
      companies.set(row.id,row.name);
    }
    if (row.kind === 'source') {
      if (sources.has(row.id)) throw new Error('DUPLICATE_SOURCE');
      sources.set(row.id,row.companyId);
    }
  }
  for (const row of rows) {
    if (row.kind === 'source' && !companies.has(row.companyId)) throw new Error('UNKNOWN_COMPANY');
    if (row.kind === 'job') {
      const name = companies.get(row.companyId);
      if (!name || (row.sourceId !== null && sources.get(row.sourceId) !== row.companyId)) throw new Error('UNKNOWN_JOB_SOURCE');
      for (const key of [row.jobKey,...row.aliases]) {
        if (keys.has(key) || !key.startsWith(name + '::')) throw new Error('AMBIGUOUS_JOB_KEY');
        keys.add(key);
      }
    }
  }
  if (rows.filter(row => row.kind === 'pipeline').length !== 1) throw new Error('PIPELINE_REQUIRED');
  for (const row of rows) if ((row.kind === 'semantic' || row.kind === 'user') && !keys.has(row.jobKey)) throw new Error('UNKNOWN_EVENT_JOB');
  return bundle;
}
