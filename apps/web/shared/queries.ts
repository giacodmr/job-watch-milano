import { z } from "zod";
import { batchSchema, lifecycleSchema, decisionSchema } from "./snapshot";

const nullableText = z.string().nullable();
export const jobsQuerySchema = z.strictObject({
  q: z.string().trim().max(120).default(""),
  company: z.string().max(200).optional(),
  batch: batchSchema.optional(),
  lifecycle: z
    .enum(["ALL", "OPEN", "NEW", "STILL_OPEN", "UPDATED", "CLOSED", "UNKNOWN"])
    .optional(),
  assessment: z
    .enum([
      "pending",
      "hard_rule",
      "semantic_not_reportable",
      "reportable",
      "unprojected",
    ])
    .optional(),
  decision: z
    .enum(["TO_REVIEW", "INTERESTED", "APPLIED", "NOT_INTERESTED", "NONE"])
    .optional(),
  cursor: z.string().max(8000).optional(),
  limit: z.coerce.number().int().min(1).max(100).default(25),
});
export type JobsQuery = z.infer<typeof jobsQuerySchema>;
export const jobViewSchema = z.strictObject({
  id: z.string(),
  jobKey: z.string(),
  companyId: z.string(),
  company: z.string(),
  title: nullableText,
  location: nullableText,
  batch: batchSchema.nullable(),
  lifecycle: lifecycleSchema,
  fingerprint: nullableText,
  canonicalUrl: nullableText,
  applyUrl: nullableText,
  firstSeenAt: nullableText,
  lastSeenAt: nullableText,
  analysisStatus: nullableText,
  analysisMethod: nullableText,
  needsAnalysis: z.boolean().nullable(),
  workerEligible: z.boolean().nullable(),
  hardExclusionReason: nullableText,
  fitScore: z.number().nullable(),
  reportable: z.boolean().nullable(),
  decision: decisionSchema.nullable(),
  technicalStatus: nullableText,
  coverage: nullableText,
  sourcePath: z.string(),
  sourceSha256: z.string(),
});
export type JobView = z.infer<typeof jobViewSchema>;
export const snapshotViewSchema = z.strictObject({
  id: z.string(),
  commitSha: z.string(),
  revision: z.number(),
  observedAt: z.string(),
  confirmedAt: z.string(),
  oldestSourceAt: nullableText,
  newestSourceAt: nullableText,
  collectionStatus: nullableText,
  healthStatus: nullableText,
  dailyComplete: z.boolean().nullable(),
  fullSemanticComplete: z.boolean().nullable(),
  jobCount: z.number(),
  pendingImports: z.number(),
  companies: z.array(z.strictObject({ id: z.string(), name: z.string() })),
});
export type SnapshotView = z.infer<typeof snapshotViewSchema>;
export const snapshotResponseSchema = z.strictObject({
  snapshot: snapshotViewSchema.nullable(),
  pendingImports: z.number(),
  productionAccess: z.literal(false),
});
export const jobsResponseSchema = z.strictObject({
  snapshotId: nullableText,
  items: z.array(jobViewSchema),
  total: z.number(),
  nextCursor: nullableText,
  metrics: z.strictObject({ rowsRead: z.number(), durationMs: z.number() }),
});
export type JobsResponse = z.infer<typeof jobsResponseSchema>;
export const detailResponseSchema = z.strictObject({
  snapshotId: z.string(),
  job: jobViewSchema,
  aliases: z.array(z.string()),
  reviews: z.array(
    z.strictObject({
      id: z.string(),
      method: z.string(),
      decision: nullableText,
      fitScore: z.number().nullable(),
      reportable: z.boolean().nullable(),
      evidenceState: z.string(),
      analyzedAt: z.string(),
      fingerprint: z.string(),
      sourcePath: z.string(),
      sourceSha256: z.string(),
      commitSha: z.string(),
    }),
  ),
  decisions: z.array(
    z.strictObject({
      id: z.string(),
      decision: decisionSchema,
      rejectionReason: nullableText,
      decidedAt: z.string(),
      sourcePath: z.string(),
      sourceSha256: z.string(),
      commitSha: z.string(),
    }),
  ),
});
export type JobDetail = z.infer<typeof detailResponseSchema>;

export const dashboardResponseSchema = z.strictObject({
  snapshotId: nullableText,
  metrics: z.strictObject({
    openJobs: z.number().int().nonnegative(),
    pendingAnalysis: z.number().int().nonnegative(),
    appliedDecisions: z.number().int().nonnegative(),
    sources: z.number().int().nonnegative(),
  }).nullable(),
  highlights: z.array(jobViewSchema),
});
export type DashboardResponse = z.infer<typeof dashboardResponseSchema>;
