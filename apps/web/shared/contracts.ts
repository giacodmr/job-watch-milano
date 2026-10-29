import { z } from 'zod';

export const schemaVersion = 4;
const hash = z.string().regex(/^[a-f0-9]{64}$/);
const utc = z.iso.datetime({ precision: 0 });
const identifier = z
  .string()
  .min(1)
  .max(200)
  .regex(/^[^\u0000-\u001f\u007f]+::[^\u0000-\u001f\u007f]+$/);

const sourcePath = z
  .string()
  .regex(
    /^(companies_job_watch_v2\.json|company_candidates\.json|job_watch_batches\.json|job_watch_rules\.json|ats_mapping_jw[1-4]\.json|current_jobs_jw[1-4]\.json|job_memory_jw[1-4]\.json|archive\/vacancies_\d{4}_\d{2}\.jsonl|amazon_target_check\.json|daily_worklist\.json|job_watch_healthcheck\.json|pipeline_execution\.json|job_watch_run_state\.json|daily_activity\.json|\.job_watch_bridge\/receipts\/[A-Za-z0-9][A-Za-z0-9_-]{0,119}\.json)$/,
  );
export const manifestSchema = z
  .strictObject({
    version: z.literal(1),
    repository: z.literal('giacodmr/job-watch-milano'),
    commitSha: z.string().regex(/^[a-f0-9]{40}$/),
    observedAt: utc,
    files: z
      .array(
        z.strictObject({
          path: sourcePath,
          sha256: hash,
          bytes: z.number().int().nonnegative(),
        }),
      )
      .min(1),
    chunks: z
      .array(
        z.strictObject({
          index: z.number().int().nonnegative(),
          sha256: hash,
          rows: z.number().int().nonnegative(),
        }),
      )
      .min(1),
  })
  .superRefine((value, ctx) => {
    if (
      new Set(value.files.map((file) => file.path)).size !==
        value.files.length ||
      value.chunks.some((chunk, index) => chunk.index !== index)
    ) {
      ctx.addIssue({
        code: 'custom',
        message: 'Unique source paths and contiguous ordered chunks required',
      });
    }
  });

export const healthSchema = z.strictObject({
  service: z.literal('job-watch-web'),
  environment: z.literal('local'),
  status: z.enum(['ok', 'degraded']),
  database: z.enum(['ready', 'unavailable', 'migration_required']),
  schemaVersion: z.number().int().nonnegative().nullable(),
  expectedSchemaVersion: z.literal(schemaVersion),
  productionAccess: z.literal(false),
  synchronization: z.literal('local-read-only'),
  checkedAt: utc,
});
export type Health = z.infer<typeof healthSchema>;

const commandBase = {
  version: z.literal(1),
  commandId: z.string().uuid(),
  idempotencyKey: z.string().regex(/^[A-Za-z0-9_-]{16,120}$/),
  expectedCommitSha: z.string().regex(/^[a-f0-9]{40}$/),
  expectedManifestSha256: hash,
  batch: z.enum(['jw1', 'jw2', 'jw3', 'jw4']),
  jobKey: identifier,
  // Opaque Python fingerprint: metadata and priority fingerprints differ.
  expectedFingerprint: z.string().regex(/^[a-f0-9]{16,64}$/),
};
export const rejectionReasons = [
  'TOO_SENIOR',
  'SALARY_TOO_LOW',
  'WRONG_FUNCTION',
  'WRONG_LOCATION',
  'FIXED_TERM',
  'PURE_SALES',
  'TOO_TECHNICAL',
  'DOMAIN_GAP',
  'OTHER',
] as const;

const userDecision = z
  .strictObject({
    ...commandBase,
    type: z.literal('user_decision'),
    decision: z.enum(['TO_REVIEW', 'INTERESTED', 'APPLIED', 'NOT_INTERESTED']),
    reason: z.string().trim().min(1).max(360).optional(),
    rejectionReason: z.enum(rejectionReasons).optional(),
  })
  .superRefine((value, ctx) => {
    if (
      value.decision === 'NOT_INTERESTED' &&
      (!value.reason ||
        !value.rejectionReason ||
        /^(scarta|no|togli|non mi interessa|not interested|reject|discard)[.!\s]*$/i.test(
          value.reason,
        ))
    ) {
      ctx.addIssue({
        code: 'custom',
        message: 'Explicit rejection reason required',
      });
    }
    if (
      value.decision !== 'NOT_INTERESTED' &&
      value.rejectionReason !== undefined
    ) {
      ctx.addIssue({
        code: 'custom',
        message: 'Rejection category only applies to NOT_INTERESTED',
      });
    }
  });
export const commandSchema = z.discriminatedUnion('type', [
  userDecision,
  z.strictObject({
    ...commandBase,
    type: z.literal('request_semantic_review'),
  }),
]);
export type CommandRequest = z.infer<typeof commandSchema>;
// Contract only. Phase 0 has no command writer or dispatcher.
