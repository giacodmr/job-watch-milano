/** M47 local-only workload scenarios: explicit sensitivity inputs, NOT a
 * D1 account meter, remote quota attestation or automatic import permission.
 * Default coefficients are stress assumptions, not measured per-vacancy costs.
 * The measured 30-cycle run MUST be used to calibrate them before Gate B.
 */
export type FreeWorkload = 'bootstrap'|'daily-delta'|'worst-case';
export type FreeForecastInput={
 vacancies:number; mode:FreeWorkload;
 fixedCatalogWrites:number;fixedPersonalWrites:number;
 writesPerVacancy:number; readsPerVacancy:number;
 retainedBytesPerVacancy:number; temporaryBytesPerVacancy:number;
 chunksPerInvocation:number;subrequestsPerInvocation:number;
};
const limits={
 internalWriteUnits:30000,d1FreeDailyWrites:100000,
 d1FreeDailyReads:5000000,
 freeDatabaseBytes:500000000,freeAccountBytes:5000000000,
 freeWorkerSubrequests:50,freeWorkerCpuMs:10,
 maxBoundParameters:100,maxStatementBytes:100000,
} as const;
function checked(v:number,name:string){
 if(!Number.isSafeInteger(v)||v<0||v>Number.MAX_SAFE_INTEGER/2)
  throw Error('INVALID_LOCAL_FORECAST_'+name);
 return v;
}
const safe=(n:number)=>{if(!Number.isSafeInteger(n))throw Error('FORECAST_OVERFLOW');return n;};
export function estimateLocalFreeWorkload(input:FreeForecastInput){
 for(const [name,v] of Object.entries(input)){
  if(name!=='mode')checked(v as number,name);
 }
 if(!['bootstrap','daily-delta','worst-case'].includes(input.mode))
  throw Error('INVALID_LOCAL_FORECAST_MODE');
 if(input.chunksPerInvocation<1||input.subrequestsPerInvocation<1)
  throw Error('INVALID_INVOCATION');
 const rowsWritten=safe(input.fixedCatalogWrites+input.fixedPersonalWrites+
   input.vacancies*input.writesPerVacancy);
 const rowsRead=safe(input.vacancies*input.readsPerVacancy);
 const retainedBytes=safe(input.vacancies*input.retainedBytesPerVacancy);
 const peakBytes=safe(retainedBytes+input.vacancies*input.temporaryBytesPerVacancy);
 const invocations=safe(1+Math.ceil(input.vacancies/input.chunksPerInvocation));
 const localInternalBudgetSatisfied=rowsWritten<=limits.internalWriteUnits;
 const nominalFreeWriteLimitSatisfied=rowsWritten<=limits.d1FreeDailyWrites;
 const nominalFreeReadLimitSatisfied=rowsRead<=limits.d1FreeDailyReads;
 const nominalDbSizeSatisfied=peakBytes<=limits.freeDatabaseBytes;
 const nominalSubrequestLimitSatisfied=input.subrequestsPerInvocation<=limits.freeWorkerSubrequests;
 return {mode:input.mode,vacancies:input.vacancies,rowsWritten,
  rowsRead,retainedBytes,peakBytes,estimatedWorkerInvocations:invocations,
  internalWriteBudget:limits.internalWriteUnits,
  localInternalBudgetSatisfied,nominalFreeWriteLimitSatisfied,
  nominalFreeReadLimitSatisfied,nominalDbSizeSatisfied,
  nominalSubrequestLimitSatisfied,
  // No CPU time or account share can be projected from Miniflare latency.
  cpuLimitMs:limits.freeWorkerCpuMs,
  remoteCpuMeasured:false as const,remoteReadQuotaVerified:false as const,
  remoteWriteQuotaVerified:false as const,remoteStorageVerified:false as const,
  remoteExecutionAuthorized:false as const,
  gateBDecision:'DENY_UNKNOWN_REMOTE_QUOTA' as const};
}
/** Workload sensitivity coefficients. NOT an admission bound: these require
 * recalibration from full empirical write/byte/CPU telemetry on allowed hosts. */
export function illustrativeFreeWorkload(vacancies:number,mode:FreeWorkload){
 const rates={
  bootstrap:{fixedCatalogWrites:550,fixedPersonalWrites:200,writesPerVacancy:14,
   readsPerVacancy:70,retainedBytesPerVacancy:6500,temporaryBytesPerVacancy:3000},
  'daily-delta':{fixedCatalogWrites:200,fixedPersonalWrites:80,writesPerVacancy:9,
   readsPerVacancy:100,retainedBytesPerVacancy:6500,temporaryBytesPerVacancy:3000},
  'worst-case':{fixedCatalogWrites:600,fixedPersonalWrites:200,writesPerVacancy:45,
   readsPerVacancy:300,retainedBytesPerVacancy:10000,temporaryBytesPerVacancy:10000},
 } as const;
 return estimateLocalFreeWorkload({vacancies,mode,...rates[mode],
  chunksPerInvocation:40,subrequestsPerInvocation:4});
}
export const CLOUDFLARE_FREE_LIMITS_FOR_MODEL=limits;
