import {describe,it,expect,beforeAll,afterAll} from 'vitest';
import {execFileSync} from 'node:child_process';
import {Miniflare,convertV4MiniflareOptions} from 'miniflare';
import {applySchema} from '../tools/model-c-schema';
import {prepareSafeRemoteBootstrapPlan,evaluateRemoteQuotaForPlan} from '../tools/model-c-remote-plan';
import {executeEphemeralAtomicBatch,inspectOfflineBatch,
  rejectRemoteTransport,classifyUncertainDelivery} from '../tools/model-c-transport-readiness';

const day='2026-10-31';
const preflight=()=>({
  status:'PREFLIGHT',budgetDay:day,priorLocalReservations:0,remoteExecutionAuthorized:false,
  provenance:{observedCommit:'a'.repeat(40),manifestDigest:'b'.repeat(64),projectionDigest:'c'.repeat(64)},
  syncRevision:1,
  metrics:{requiredBound:120,publicationStatements:18,publicationBytes:3500,
    maxStatementParameters:10,maxStatementSqlBytes:800,
    writeBounds:{staging:40,promotion:40,checkpoint:10,personal:10,reconciliation:20}},
});
const setup=()=>({
  catalog:{migrationFiles:4,localRowsWritten:16,remoteUpperBound:32},
  personal:{migrationFiles:3,localRowsWritten:8,remoteUpperBound:16},
});
let runtime:Miniflare,catalog:D1Database,personal:D1Database;
beforeAll(async()=>{
  runtime=new Miniflare(convertV4MiniflareOptions({
    modules:true,script:'export default {fetch(){return new Response("offline")}}',cf:false,
    compatibilityDate:'2026-10-29',d1Databases:{CATALOG:'m45-test-cat',PERSONAL:'m45-test-personal'},
  }));
  catalog=await runtime.getD1Database('CATALOG');
  personal=await runtime.getD1Database('PERSONAL');
  await applySchema(catalog,'catalog');await applySchema(personal,'personal');
});
afterAll(async()=>{await runtime?.dispose();});

describe('M45 safe offline D1 remote bootstrap readiness',()=>{
  it('emits a safe blocked status when no real owner context is available; no cloud access',()=>{
    const output=execFileSync(process.execPath,
      ['tools/model-c-bootstrap-runner.mjs','--commit','a'.repeat(40)],
      {cwd:process.cwd(),encoding:'utf8',
        env:{...process.env,JOB_WATCH_PRIVATE_OWNER_ID:''}});
    const report=JSON.parse(output) as {status:string;remoteExecutionAuthorized:boolean;blockers:string[]};
    expect(report.status).toBe('REAL_DATA_PREFLIGHT_NOT_EXECUTED');
    expect(report.remoteExecutionAuthorized).toBe(false);
    expect(report.blockers).toContain('REMOTE_EXECUTION_NOT_AUTHORIZED');
  });

  it('builds a deterministic PII-free and owner-free plan with per-DB dependencies',async()=>{
    const first=await prepareSafeRemoteBootstrapPlan(preflight(),setup());
    expect(first).toMatchObject({mode:'BOOTSTRAP_INITIAL',target:'OFFLINE_REVIEW_ONLY',
      bounds:{combinedUpperBound:168,catalogSchema:32,personalSchema:16},
      crossDatabaseAtomicity:false,remoteExecutionAuthorized:false});
    expect(first.requiredSequence.map(x=>x.scope)).toContain('BOTH_READ_ONLY');
    expect(first.readiness).toContain('REMOTE_QUOTA_UNVERIFIED');
    expect(first.digest).toBe((await prepareSafeRemoteBootstrapPlan(preflight(),setup())).digest);
    expect(JSON.stringify(first)).not.toContain('owner_id');
  });
  it('fails closed on unknown schema, underbounded setup, invalid provenance and publication limits',async()=>{
    const bad=setup();bad.catalog.remoteUpperBound=15;
    await expect(prepareSafeRemoteBootstrapPlan(preflight(),bad)).rejects.toThrow('REMOTE_SCHEMA_COST_NOT_BOUNDED');
    const wrong=preflight();wrong.provenance.observedCommit='main';
    await expect(prepareSafeRemoteBootstrapPlan(wrong,setup())).rejects.toThrow();
    const big=preflight();big.metrics.publicationStatements=8001;
    await expect(prepareSafeRemoteBootstrapPlan(big,setup())).rejects.toThrow('REMOTE_PUBLICATION_CONTRACT_LIMIT');
    const mismatched=setup();mismatched.personal.migrationFiles=2;
    await expect(prepareSafeRemoteBootstrapPlan(preflight(),mismatched)).rejects.toThrow('REMOTE_SCHEMA_COST_NOT_BOUNDED');
  });
  it('never treats unknown remote quota as available or turns a positive review into write authority',async()=>{
    const plan=await prepareSafeRemoteBootstrapPlan(preflight(),setup());
    expect(evaluateRemoteQuotaForPlan(plan,preflight(),null,new Date(day+'T12:00:00Z')))
      .toMatchObject({quotaStatus:'QUOTA_VERIFICATION_REQUIRED',remoteExecutionAuthorized:false});
    const evidence={account:{plan:'WORKERS_FREE',source:'cloudflare-account-analytics',
      scope:'ALL_ACCOUNT_D1_DATABASES',complete:true,reliable:true,day,since:day+'T00:00:00Z',
      through:day+'T12:00:00Z',observedAt:day+'T12:00:00Z',rowsWritten:0,
      unobservedWritesUpperBound:0},setupWritesUpperBound:48,otherWorkloadWritesUpperBound:0,
      safetyMarginRows:5000,remoteLimitsVerified:true,recoveryPlanVerified:true,writersQuiesced:true};
    expect(evaluateRemoteQuotaForPlan(plan,preflight(),evidence,new Date(day+'T12:00:00Z')))
      .toMatchObject({quotaStatus:'READY_FOR_MANUAL_REMOTE_REVIEW',remoteExecutionAuthorized:false});
    const undercount={...evidence,setupWritesUpperBound:47};
    expect(evaluateRemoteQuotaForPlan(plan,preflight(),undercount,new Date(day+'T12:00:00Z')))
      .toMatchObject({quotaStatus:'QUOTA_VERIFICATION_REQUIRED',remoteExecutionAuthorized:false});
    const unrelated=preflight();unrelated.provenance.observedCommit='d'.repeat(40);
    expect(evaluateRemoteQuotaForPlan(plan,unrelated,evidence,new Date(day+'T12:00:00Z')))
      .toMatchObject({quotaStatus:'QUOTA_VERIFICATION_REQUIRED',remoteExecutionAuthorized:false});
  });
  it('rejects any remote target before D1 mutation and enforces statement parameters and size',async()=>{
    expect(()=>rejectRemoteTransport('remote')).toThrow('REMOTE_EXECUTION_NOT_AUTHORIZED');
    expect(()=>inspectOfflineBatch([{sql:'INSERT INTO x VALUES (?)',values:Array(81).fill(1)}]))
      .toThrow('BATCH_CONTRACT_INVALID');
    expect(()=>inspectOfflineBatch([{sql:'x'.repeat(65537),values:[]}])).toThrow('D1_SQL_LIMIT');
    await expect(executeEphemeralAtomicBatch(catalog,'CATALOG','remote',
      [{sql:'INSERT INTO catalog_company_identity VALUES (?)',values:['should-not-exist']}]))
      .rejects.toThrow('REMOTE_EXECUTION_NOT_AUTHORIZED');
    expect(await catalog.prepare("SELECT count(*) AS n FROM catalog_company_identity WHERE id='should-not-exist'").first('n')).toBe(0);
  });
  it('uses a real D1 local batch transaction and rolls back on a SQL failure',async()=>{
    const fail=[
      {sql:'INSERT INTO catalog_company_identity(id) VALUES (?)',values:['rollback-1']},
      {sql:'INSERT INTO missing_m45_table VALUES (?)',values:['rollback-2']},
    ];
    await expect(executeEphemeralAtomicBatch(catalog,'CATALOG','local-ephemeral',fail))
      .rejects.toThrow('TRANSPORT_OUTCOME_REQUIRES_CHECKPOINT_INSPECTION');
    expect(await catalog.prepare("SELECT count(*) AS n FROM catalog_company_identity WHERE id='rollback-1'").first('n')).toBe(0);
  });
  it('prevents database scope confusion; no transaction is claimed across both D1 databases',async()=>{
    await expect(executeEphemeralAtomicBatch(personal,'CATALOG','local-ephemeral',
      [{sql:'SELECT 1',values:[]}])).rejects.toThrow('WRONG_DATABASE_SCOPE');
    const result=await executeEphemeralAtomicBatch(catalog,'CATALOG','local-ephemeral',
      [{sql:'INSERT INTO catalog_company_identity(id) VALUES (?)',values:['committed-local']}]);
    expect(result).toHaveLength(1);
    expect(await catalog.prepare("SELECT count(*) AS n FROM catalog_company_identity WHERE id='committed-local'").first('n')).toBe(1);
    expect(classifyUncertainDelivery('UNKNOWN')).toBe('INSPECT_CHECKPOINT_AND_RECEIPT_BEFORE_RETRY');
    expect(classifyUncertainDelivery('FAILED')).toBe('VERIFY_ABORT_OR_COMMIT_BEFORE_RETRY');
  });
});
