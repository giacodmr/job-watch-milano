import {describe,expect,it} from 'vitest';
import {CLOUDFLARE_FREE_LIMITS_FOR_MODEL,
 estimateLocalFreeWorkload,illustrativeFreeWorkload} from '../tools/model-c-free-local-forecast';

describe('M47 AC-10: Free tier local sensitivity, not remote authorization',()=>{
 it.each([30,100,1000,10000])('computes bootstrap, daily delta and worst-case for %i vacancies',n=>{
  const bootstrap=illustrativeFreeWorkload(n,'bootstrap');
  const delta=illustrativeFreeWorkload(n,'daily-delta');
  const worst=illustrativeFreeWorkload(n,'worst-case');
  expect(bootstrap.vacancies).toBe(n);
  expect(delta.rowsWritten).toBeLessThan(worst.rowsWritten);
  expect(worst.rowsWritten).toBeGreaterThan(bootstrap.rowsWritten);
  expect(bootstrap.retainedBytes).toBeLessThanOrEqual(bootstrap.peakBytes);
  expect(worst.peakBytes).toBeGreaterThan(bootstrap.retainedBytes);
  for(const r of [bootstrap,delta,worst]){
   expect(r.remoteExecutionAuthorized).toBe(false);
   expect(r.gateBDecision).toBe('DENY_UNKNOWN_REMOTE_QUOTA');
   expect(r.remoteCpuMeasured).toBe(false);
   expect(r.remoteWriteQuotaVerified).toBe(false);
   expect(r.remoteReadQuotaVerified).toBe(false);
   expect(r.remoteStorageVerified).toBe(false);
   expect(r.localInternalBudgetSatisfied)
    .toBe(r.rowsWritten<=CLOUDFLARE_FREE_LIMITS_FOR_MODEL.internalWriteUnits);
  }
  console.log('M47_LOCAL_SENSITIVITY '+JSON.stringify({n,bootstrap,delta,worst}));
 });
 it('fails closed on invalid or overflowing assumptions',()=>{
  const valid={vacancies:30,mode:'daily-delta' as const,fixedCatalogWrites:10,
   fixedPersonalWrites:10,writesPerVacancy:10,readsPerVacancy:10,
   retainedBytesPerVacancy:1024,temporaryBytesPerVacancy:1000,
   chunksPerInvocation:40,subrequestsPerInvocation:3};
  expect(()=>estimateLocalFreeWorkload({...valid,vacancies:-1})).toThrow('INVALID_LOCAL_FORECAST');
  expect(()=>estimateLocalFreeWorkload({...valid,writesPerVacancy:Number.NaN})).toThrow('INVALID_LOCAL_FORECAST');
  expect(()=>estimateLocalFreeWorkload({...valid,chunksPerInvocation:0})).toThrow('INVALID_INVOCATION');
  expect(()=>estimateLocalFreeWorkload({...valid,subrequestsPerInvocation:0})).toThrow('INVALID_INVOCATION');
  expect(()=>estimateLocalFreeWorkload({...valid,vacancies:5000000000,
   writesPerVacancy:1000000000})).toThrow('FORECAST_OVERFLOW');
 });
});
