// Deterministic, sanitized read-only bootstrap decision. Never accepts secrets,
// raw events, SQL statements, account IDs, owner IDs or a remote D1 binding.
import {z} from 'zod';
import {canonical,sha256} from '../shared/canonical';
import {assessFreeBootstrapRemoteQuota} from './model-c-free-bootstrap';

const integer=z.number().int().nonnegative().max(Number.MAX_SAFE_INTEGER);
const sha=z.string().regex(/^[a-f0-9]{64}$/);
const preflightSchema=z.strictObject({
  status:z.literal('PREFLIGHT'),
  provenance:z.strictObject({
    observedCommit:z.string().regex(/^[a-f0-9]{40}$/),
    manifestDigest:sha,projectionDigest:sha,
  }),
  budgetDay:z.string().regex(/^\d{4}-\d\d-\d\d$/),
  priorLocalReservations:integer,
  remoteExecutionAuthorized:z.literal(false),
  syncRevision:integer,
  metrics:z.object({
    requiredBound:integer,publicationStatements:integer,publicationBytes:integer,
    maxStatementParameters:integer,maxStatementSqlBytes:integer,
    writeBounds:z.record(z.string(),integer),
  }),
});
const setupSchema=z.strictObject({
  catalog:z.strictObject({migrationFiles:integer,localRowsWritten:integer,remoteUpperBound:integer}),
  personal:z.strictObject({migrationFiles:integer,localRowsWritten:integer,remoteUpperBound:integer}),
});
export type OfflineBootstrapPreflight=z.infer<typeof preflightSchema>;
export type OfflineSchemaCosts=z.infer<typeof setupSchema>;
export async function prepareSafeRemoteBootstrapPlan(preflight:unknown,setup:unknown){
  const plan=preflightSchema.parse(preflight),schema=setupSchema.parse(setup);
  if(schema.catalog.migrationFiles!==4||schema.personal.migrationFiles!==3||
    schema.catalog.remoteUpperBound<schema.catalog.localRowsWritten||
    schema.personal.remoteUpperBound<schema.personal.localRowsWritten)
    throw Error('REMOTE_SCHEMA_COST_NOT_BOUNDED');
  const metrics=plan.metrics;
  if(metrics.maxStatementParameters>80||metrics.maxStatementSqlBytes>64*1024||
    metrics.publicationStatements>8000||metrics.publicationBytes>8*1024*1024)
    throw Error('REMOTE_PUBLICATION_CONTRACT_LIMIT');
  const bound=metrics.requiredBound+schema.catalog.remoteUpperBound+schema.personal.remoteUpperBound;
  if(!Number.isSafeInteger(bound))throw Error('REMOTE_WRITE_BOUND_OVERFLOW');
  const steps=[
    {id:'schema-catalog',scope:'CATALOG',dependsOn:[]},
    {id:'schema-personal',scope:'PERSONAL',dependsOn:[]},
    {id:'catalog-and-personal-preflight',scope:'BOTH_READ_ONLY',dependsOn:['schema-catalog','schema-personal']},
    {id:'personal-append',scope:'PERSONAL',dependsOn:['catalog-and-personal-preflight']},
    {id:'catalog-atomic-publication',scope:'CATALOG',dependsOn:['personal-append']},
    {id:'personal-reconciliation',scope:'PERSONAL',dependsOn:['catalog-atomic-publication']},
    {id:'verify-cross-db-checkpoints',scope:'BOTH_READ_ONLY',dependsOn:['personal-reconciliation']},
  ];
  const report={
    format:'job-watch-remote-plan/1' as const,
    target:'OFFLINE_REVIEW_ONLY' as const,
    origin:plan.provenance,
    mode:plan.syncRevision===1?'BOOTSTRAP_INITIAL' as const:'INCREMENTAL_PREFLIGHT' as const,
    syncRevision:plan.syncRevision,
    bounds:{
      catalogAndPersonalImport:metrics.requiredBound,
      catalogSchema: schema.catalog.remoteUpperBound,
      personalSchema: schema.personal.remoteUpperBound,
      combinedUpperBound:bound,
      publicationStatements:metrics.publicationStatements,
      publicationBytes:metrics.publicationBytes,
      maxStatementSqlBytes:metrics.maxStatementSqlBytes,
      maxStatementParameters:metrics.maxStatementParameters,
    },
    requiredSequence:steps,
    readiness:['LOCAL_PLAN_VALID','REMOTE_SEMANTICS_UNVERIFIED',
      'REMOTE_QUOTA_UNVERIFIED','REMOTE_EXECUTION_NOT_AUTHORIZED'] as const,
    crossDatabaseAtomicity:false as const,
    remoteExecutionAuthorized:false as const,
    // A sanitized deterministic read-only digest never includes a user identity.
  };
  return {...report,digest:await sha256(canonical(report))};
}
/** Unknown or incomplete account evidence must not be treated as Free quota. */
export function evaluateRemoteQuotaForPlan(plan:Awaited<ReturnType<typeof prepareSafeRemoteBootstrapPlan>>,
  preflight:unknown,accountEvidence:unknown,now=new Date()){
  // Bind accounting evidence to the *same* pinned source/plan; never let a
  // different (cheaper) preflight or an unbounded migration pass admission.
  const p=preflightSchema.safeParse(preflight);
  const ev=accountEvidence&&typeof accountEvidence==='object'&&!Array.isArray(accountEvidence)
    ? accountEvidence as Record<string,unknown> : null;
  const migrations=plan.bounds.catalogSchema+plan.bounds.personalSchema;
  const compatible=p.success &&
    canonical(p.data.provenance)===canonical(plan.origin) &&
    p.data.metrics.requiredBound===plan.bounds.catalogAndPersonalImport &&
    p.data.metrics.publicationStatements===plan.bounds.publicationStatements &&
    p.data.metrics.publicationBytes===plan.bounds.publicationBytes &&
    ev!==null && typeof ev.setupWritesUpperBound==='number' &&
    Number.isSafeInteger(ev.setupWritesUpperBound) &&
    ev.setupWritesUpperBound>=migrations;
  const input=compatible?{...ev,preflight:p.data}:null;
  const assessment=assessFreeBootstrapRemoteQuota(input,now);
  return {planDigest:plan.digest,quotaStatus:assessment.status,
    remoteExecutionAuthorized:false as const};
}
