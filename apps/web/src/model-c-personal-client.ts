// Browser-only read contracts. Never import Worker/D1 modules into React.
import {z} from 'zod';
import {readApi} from './api';

const nullable=z.string().nullable();
export const decisionSchema=z.enum(['TO_REVIEW','INTERESTED','APPLIED','NOT_INTERESTED']);
export const reconciliationSchema=z.enum(['PENDING','VERIFIED','STALE','CONFLICT','UNRESOLVED_REFERENCE']);
export const personalViewSchema=z.enum(['all','to_apply','applied','dismissed']);
const assessmentSchema=z.object({
  method:z.string(),fingerprint:nullable,fitScore:z.number().nullable(),
  reportable:z.boolean().nullable(),summary:nullable,
  freshness:z.enum(['CURRENT','STALE','UNVERIFIED']),
});
export const personalRowSchema=z.object({
  jobId:z.string().regex(/^job:[a-f0-9]{64}$/),
  capturedTitle:nullable,officialUrl:nullable,lastKnownLifecycle:nullable,
  capturedCommit:z.string(),capturedPath:z.string(),capturedSha256:z.string(),
  decision:decisionSchema.nullable(),decidedAt:nullable,
  rejectionReason:nullable,reasonSummary:nullable,
  assessment:assessmentSchema.nullable(),
  activeReferences:z.array(z.enum(['SAVED','APPLICATION','DISMISSED'])),
  knownIdentity:z.boolean(),currentlyVisible:z.boolean(),
  reconciliation:reconciliationSchema,
  catalog:z.object({
    company:z.string(),companyId:z.string(),title:nullable,location:nullable,
    lifecycle:z.string(),canonicalUrl:nullable,applyUrl:nullable,
    firstSeenAt:nullable,lastSeenAt:nullable,
  }).nullable(),
});
const context={
  personalRevision:z.number().int().positive(),
  catalogRevision:z.number().int().positive(),
  productionAccess:z.literal(false),
};
export const personalPageSchema=z.object({
  ...context,total:z.number().int().nonnegative(),
  nextCursor:nullable,items:z.array(personalRowSchema),
});
export const personalSummarySchema=z.object({
  ...context,counts:z.object({
    referencesCount:z.number().int().nonnegative(),
    decisionsCount:z.number().int().nonnegative(),
    assessmentsCount:z.number().int().nonnegative(),
  }),
});
const eventFields={
  id:z.string(),sourceCommit:z.string(),sourcePath:z.string(),sourceSha256:z.string(),
  resultSha256:z.string(),
};
export const personalDetailSchema=z.object({
  ...context,job:personalRowSchema,
  decisionEvents:z.array(z.object({
    ...eventFields,decision:decisionSchema,
    fingerprint:nullable,decidedAt:z.string(),
    rejectionReason:nullable,reasonSummary:nullable,
  })),
  decisionEventsTruncated:z.boolean(),
  assessmentEvents:z.array(z.object({
    ...eventFields,method:z.string(),fingerprint:z.string(),
    decision:nullable,fitScore:z.number().nullable(),
    reportable:z.boolean().nullable(),summary:nullable,
    evidenceState:z.string(),analyzedAt:z.string(),
  })),
  assessmentEventsTruncated:z.boolean(),
});
export type PersonalRow=z.infer<typeof personalRowSchema>;
export type PersonalPage=z.infer<typeof personalPageSchema>;
export type PersonalSummary=z.infer<typeof personalSummarySchema>;
export type PersonalDetail=z.infer<typeof personalDetailSchema>;
export type PersonalView=z.infer<typeof personalViewSchema>;
export type Decision=z.infer<typeof decisionSchema>;

export type PersonalFilters={
  view:PersonalView;q:string;decision?:Decision;reference?:'SAVED'|'APPLICATION'|'DISMISSED';
  cursor?:string;limit?:number;
};
export function personalPagePath(input:PersonalFilters):string {
  const url=new URLSearchParams();
  url.set('view',input.view);
  const q=input.q.trim();
  if(q)url.set('q',q.slice(0,120));
  if(input.decision)url.set('decision',input.decision);
  if(input.reference)url.set('reference',input.reference);
  if(input.cursor)url.set('cursor',input.cursor);
  url.set('limit',String(input.limit??25));
  return '/api/model-c/personal/jobs?'+url.toString();
}
export const readPersonalPage=(input:PersonalFilters,signal:AbortSignal)=>
  readApi(personalPagePath(input),personalPageSchema,signal);
export const readPersonalSummary=(signal:AbortSignal)=>
  readApi('/api/model-c/personal/summary',personalSummarySchema,signal);
export const readPersonalDetail=(id:string,signal:AbortSignal)=>
  readApi('/api/model-c/personal/jobs/'+z.string().regex(/^job:[a-f0-9]{64}$/).parse(id),personalDetailSchema,signal);

export function safeExternalUrl(value:string|null):string|null {
  if(!value)return null;
  try { const url=new URL(value);return url.protocol==='https:'||url.protocol==='http:'?url.href:null; }
  catch {return null;}
}
export const decisionLabel:Record<Decision,string>={
  TO_REVIEW:'Da valutare',INTERESTED:'Interessante',
  APPLIED:'Candidatura inviata',NOT_INTERESTED:'Non interessato',
};
export const reconciliationLabel:Record<z.infer<typeof reconciliationSchema>,string>={
  VERIFIED:'Verificata',PENDING:'In attesa',
  STALE:'Da riconciliare',CONFLICT:'Conflitto',UNRESOLVED_REFERENCE:'Riferimento non risolto',
};
export function personalReadError(error:unknown):string {
  if(error instanceof Error&&error.message==='The operation was aborted.')return 'Richiesta annullata.';
  const code=error instanceof Error&&'code' in error?String(error.code):'';
  if(['CONTEXT_CHANGED','CATALOG_CHANGED','CURSOR_FILTER_MISMATCH'].includes(code))
    return 'Il catalogo o la selezione sono cambiati. Aggiorna la consultazione.';
  if(code==='not_found')return 'Model C è disabilitato nell’ambiente corrente. È disponibile solo nel laboratorio locale sintetico.';
  if(code==='PERSONAL_CONTEXT_UNAVAILABLE')return 'Non esiste un contesto PERSONAL per questa identità sintetica.';
  return 'Impossibile leggere Candidature. Verifica che il laboratorio Model C sia attivo e i database siano inizializzati.';
}
