import {z} from 'zod';
import {readApi} from './api';
import {personalRowSchema,personalDetailSchema} from './model-c-personal-client';
const jobId=z.string().regex(/^job:[a-f0-9]{64}$/);
export const catalogJobSchema=z.object({
  id:jobId,jobKey:z.string(),companyId:z.string(),company:z.string(),
  sourceId:z.string().nullable(),kind:z.enum(['OPPORTUNITY','AI_QUEUE']),
  lifecycle:z.enum(['NEW','STILL_OPEN','UPDATED']),title:z.string().nullable(),
  location:z.string().nullable(),canonicalUrl:z.string().nullable(),applyUrl:z.string().nullable(),
  fingerprint:z.string().nullable(),batch:z.string().nullable(),
  firstSeenAt:z.string().nullable(),lastSeenAt:z.string().nullable(),
  needsAnalysis:z.boolean().nullable(),workerEligible:z.boolean().nullable(),technicalStatus:z.string().nullable(),
  originCommit:z.string(),originPath:z.string(),originSha256:z.string(),
});
const catalogHead=z.object({
  syncRevision:z.number().int().positive(),contentRevision:z.number().int().positive(),
  ledgerRevision:z.number().int().positive(),runId:z.string(),observedCommit:z.string(),
  contentDigest:z.string(),ledgerDigest:z.string(),contentOriginCommit:z.string(),
  identityCount:z.number(),mappingCount:z.number(),
});
export const opportunitySchema=catalogJobSchema.extend({personal:personalRowSchema.nullable()});
export const opportunityPageSchema=z.object({
  snapshot:catalogHead.nullable(),productionAccess:z.literal(false),
  personalRevision:z.number().int().positive().nullable(),
  appRevision:z.number().int().nonnegative().nullable().optional(),
  items:z.array(opportunitySchema),total:z.number().int().nonnegative(),
  nextCursor:z.string().nullable(),
});
export const opportunityDetailSchema=z.object({
  snapshot:catalogHead,productionAccess:z.literal(false),
  job:catalogJobSchema,aliases:z.array(z.string()),aliasesTruncated:z.boolean(),
  personalRevision:z.number().int().positive(),
  appRevision:z.number().int().nonnegative().optional(),
  personal:personalRowSchema.nullable(),personalDetail:personalDetailSchema.nullable(),
});
export const opportunitySnapshotSchema=z.object({
  productionAccess:z.literal(false),
  snapshot:catalogHead.extend({
    currentJobs:z.number().int().nonnegative(),
    companies:z.array(z.object({id:z.string(),name:z.string(),membership:z.string()})),
    companiesTruncated:z.boolean(),
  }).nullable(),
});
export type Opportunity=z.infer<typeof opportunitySchema>;
export type OpportunityPage=z.infer<typeof opportunityPageSchema>;
export type OpportunityDetail=z.infer<typeof opportunityDetailSchema>;
export type OpportunitySnapshot=z.infer<typeof opportunitySnapshotSchema>['snapshot'];
export type OpportunityView='all'|'new'|'updated'|'analysis';
export type OpportunityFilters={
  view:OpportunityView;q:string;companyId?:string;kind?:'OPPORTUNITY'|'AI_QUEUE';
  batch?:'jw1'|'jw2'|'jw3'|'jw4';lifecycle?:'NEW'|'STILL_OPEN'|'UPDATED';
  needsAnalysis?:'true'|'false';cursor?:string;limit?:number;
};
export function opportunityPagePath(filters:OpportunityFilters) {
  const url=new URLSearchParams();
  if(filters.q.trim())url.set('q',filters.q.trim().slice(0,120));
  if(filters.companyId)url.set('companyId',filters.companyId);
  if(filters.kind)url.set('kind',filters.kind);
  if(filters.batch)url.set('batch',filters.batch);
  const lifecycle=filters.view==='new'?'NEW':filters.view==='updated'?'UPDATED':filters.lifecycle;
  const needs=filters.view==='analysis'?'true':filters.needsAnalysis;
  if(lifecycle)url.set('lifecycle',lifecycle);
  if(needs)url.set('needsAnalysis',needs);
  if(filters.cursor)url.set('cursor',filters.cursor);
  url.set('limit',String(filters.limit??25));
  return '/api/model-c/opportunities/jobs?'+url;
}
export const readOpportunities=(filters:OpportunityFilters,signal:AbortSignal)=>
  readApi(opportunityPagePath(filters),opportunityPageSchema,signal);
export const readOpportunitySnapshot=(signal:AbortSignal)=>
  readApi('/api/model-c/catalog/snapshot',opportunitySnapshotSchema,signal)
    .then(result=>result.snapshot);
export const readOpportunityDetail=(job:string,revision:number,signal:AbortSignal)=>
  readApi('/api/model-c/opportunities/jobs/'+jobId.parse(job)+'?revision='+revision,opportunityDetailSchema,signal);
