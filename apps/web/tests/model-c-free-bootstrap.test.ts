import { describe, expect, it } from 'vitest';
import { assessFreeBootstrapRemoteQuota } from '../tools/model-c-free-bootstrap';

const now=new Date('2026-10-30T12:00:00Z');
const candidate=()=>({
  preflight:{status:'PREFLIGHT',budgetDay:'2026-10-30',priorLocalReservations:0,remoteExecutionAuthorized:false,
    provenance:{observedCommit:'a'.repeat(40),manifestDigest:'b'.repeat(64),projectionDigest:'c'.repeat(64)},
    metrics:{requiredBound:94173,publicationStatements:739,publicationBytes:2704855,maxStatementParameters:80,maxStatementSqlBytes:1015}},
  account:{plan:'WORKERS_FREE',source:'cloudflare-account-analytics',scope:'ALL_ACCOUNT_D1_DATABASES',complete:true,reliable:true,
    day:'2026-10-30',since:'2026-10-30T00:00:00Z',through:'2026-10-30T12:00:00Z',observedAt:'2026-10-30T12:00:00Z',rowsWritten:100,unobservedWritesUpperBound:0},
  setupWritesUpperBound:400,otherWorkloadWritesUpperBound:100,safetyMarginRows:5000,
  remoteLimitsVerified:true,recoveryPlanVerified:true,writersQuiesced:true,
});
describe('read-only future Free bootstrap quota review',()=>{
  it('includes actual account usage, setup, other workloads, uncertainty, reservations and margin without authorizing execution',()=>{
    expect(assessFreeBootstrapRemoteQuota(candidate(),now)).toMatchObject({status:'READY_FOR_MANUAL_REMOTE_REVIEW',expectedUpperBound:99773,remainingRows:227,remoteExecutionAuthorized:false});
    const c=candidate();c.account.unobservedWritesUpperBound=100;c.preflight.priorLocalReservations=100;
    expect(assessFreeBootstrapRemoteQuota(c,now)).toMatchObject({expectedUpperBound:99973,remainingRows:27,remoteExecutionAuthorized:false});
  });
  it('requires reliable full-account UTC-day coverage, not local reservations or sampled/incomplete/stale metrics',()=>{
    const missing={...candidate(),account:undefined};
    expect(assessFreeBootstrapRemoteQuota(missing,now).status).toBe('QUOTA_VERIFICATION_REQUIRED');
    const mutations:((c:ReturnType<typeof candidate>)=>void)[]=[c=>{c.account.reliable=false;},c=>{c.account.complete=false;},c=>{c.account.scope='ONE_DATABASE';},
      c=>{c.account.source='local-reservations';},c=>{c.account.through='2026-10-30T11:54:59Z';},c=>{c.account.since='2026-10-29T00:00:00Z';},
      c=>{c.account.observedAt='2026-10-30T12:01:00Z';},c=>{c.account.plan='WORKERS_PAID';}];
    for(const mutate of mutations) {
      const c=candidate();mutate(c);expect(assessFreeBootstrapRemoteQuota(c,now).status).toBe('QUOTA_VERIFICATION_REQUIRED');
    }
    expect(assessFreeBootstrapRemoteQuota({...candidate(),setupWritesUpperBound:undefined},now).status).toBe('QUOTA_VERIFICATION_REQUIRED');
  });
  it('refuses insufficient free quota and never offers a Paid fallback',()=>{
    const c=candidate();c.account.rowsWritten=1000;
    expect(assessFreeBootstrapRemoteQuota(c,now)).toMatchObject({status:'FREE_QUOTA_INSUFFICIENT',remoteExecutionAuthorized:false});
    c.account.rowsWritten=0;c.preflight.metrics.requiredBound=95001;
    expect(assessFreeBootstrapRemoteQuota(c,now).status).toBe('BOOTSTRAP_BUDGET_EXCEEDED');
    c.preflight.metrics.requiredBound=94173;c.preflight.priorLocalReservations=1000;
    expect(assessFreeBootstrapRemoteQuota(c,now).status).toBe('WRITE_BUDGET_INSUFFICIENT');
  });
  it('requires current-day evidence, remote limits, recovery and quiesced writers independently of quota arithmetic',()=>{
    const c=candidate();c.remoteLimitsVerified=false;
    expect(assessFreeBootstrapRemoteQuota(c,now).status).toBe('REMOTE_ACTIVATION_REVIEW_REQUIRED');
    c.remoteLimitsVerified=true;c.recoveryPlanVerified=false;
    expect(assessFreeBootstrapRemoteQuota(c,now).status).toBe('REMOTE_ACTIVATION_REVIEW_REQUIRED');
    c.recoveryPlanVerified=true;c.writersQuiesced=false;
    expect(assessFreeBootstrapRemoteQuota(c,now).status).toBe('REMOTE_ACTIVATION_REVIEW_REQUIRED');
    expect(assessFreeBootstrapRemoteQuota(candidate(),new Date('2026-10-31T00:00:00Z')).status).toBe('QUOTA_VERIFICATION_REQUIRED');
  });
});
