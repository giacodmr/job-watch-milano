// Read-only readiness assessment. No Cloudflare client, credentials, transport or
// execution token: even a positive assessment requires manual activation review.
import { z } from 'zod';
const rows=z.number().int().nonnegative().max(Number.MAX_SAFE_INTEGER);
const hash=z.string().regex(/^[a-f0-9]{64}$/), stamp=z.iso.datetime();
const inputSchema=z.strictObject({
  preflight:z.object({
    status:z.literal('PREFLIGHT'),budgetDay:z.string(),priorLocalReservations:rows,
    remoteExecutionAuthorized:z.literal(false),
    provenance:z.strictObject({observedCommit:z.string().regex(/^[a-f0-9]{40}$/),manifestDigest:hash,projectionDigest:hash}),
    metrics:z.object({requiredBound:rows,publicationStatements:rows,publicationBytes:rows,maxStatementParameters:rows,maxStatementSqlBytes:rows}),
  }),
  account:z.strictObject({
    plan:z.literal('WORKERS_FREE'),source:z.literal('cloudflare-account-analytics'),
    scope:z.literal('ALL_ACCOUNT_D1_DATABASES'),complete:z.literal(true),reliable:z.literal(true),
    day:z.string(),since:stamp,through:stamp,observedAt:stamp,
    rowsWritten:rows,unobservedWritesUpperBound:rows,
  }),
  setupWritesUpperBound:rows,otherWorkloadWritesUpperBound:rows,safetyMarginRows:rows,
  remoteLimitsVerified:z.boolean(),recoveryPlanVerified:z.boolean(),writersQuiesced:z.boolean(),
});
export function assessFreeBootstrapRemoteQuota(input:unknown, now=new Date()) {
  const parsed=inputSchema.safeParse(input);
  const base={remoteExecutionAuthorized:false as const,freeDailyRows:100000};
  if(!parsed.success)return {...base,status:'QUOTA_VERIFICATION_REQUIRED' as const};
  const p=parsed.data, plan=p.preflight, a=p.account, day=now.toISOString().slice(0,10);
  const through=Date.parse(a.through), observed=Date.parse(a.observedAt), age=now.getTime()-through;
  if(plan.budgetDay!==day||a.day!==day||a.since!==day+'T00:00:00Z'||age<0||age>5*60*1000||observed<through||observed>now.getTime())return {...base,status:'QUOTA_VERIFICATION_REQUIRED' as const};
  const bound=plan.metrics.requiredBound;
  if(bound>95000)return {...base,status:'BOOTSTRAP_BUDGET_EXCEEDED' as const};
  if(bound+plan.priorLocalReservations>95000)return {...base,status:'WRITE_BUDGET_INSUFFICIENT' as const};
  // Prior local reservations are liabilities, never a replacement for account
  // usage. Adding them can double-count already billed writes, conservatively.
  const expectedUpperBound=a.rowsWritten+a.unobservedWritesUpperBound+plan.priorLocalReservations+bound+p.setupWritesUpperBound+p.otherWorkloadWritesUpperBound+p.safetyMarginRows;
  if(!Number.isSafeInteger(expectedUpperBound))return {...base,status:'QUOTA_VERIFICATION_REQUIRED' as const};
  if(expectedUpperBound>100000)return {...base,status:'FREE_QUOTA_INSUFFICIENT' as const,expectedUpperBound,remainingRows:100000-expectedUpperBound};
  const limits=plan.metrics;
  if(!p.remoteLimitsVerified||!p.recoveryPlanVerified||!p.writersQuiesced||limits.publicationStatements>8000||limits.publicationBytes>8388608||limits.maxStatementParameters>80||limits.maxStatementSqlBytes>65536)return {...base,status:'REMOTE_ACTIVATION_REVIEW_REQUIRED' as const,expectedUpperBound};
  return {...base,status:'READY_FOR_MANUAL_REMOTE_REVIEW' as const,expectedUpperBound,remainingRows:100000-expectedUpperBound};
}
