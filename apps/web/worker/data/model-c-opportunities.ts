// Private synthetic-only composition. CATALOG endpoints remain strictly public metadata.
import {z} from 'zod';
import {
  getModelCCatalogSnapshot,getModelCCatalogJob,listModelCCatalogJobs,
  modelCCatalogQuerySchema,ModelCReadError,
} from './model-c-catalog';
import {getModelCPersonalJob,getModelCPersonalOverlays,ModelCPersonalReadError} from './model-c-personal';
import type {ModelCLocalEnv} from '../model-c-local-api';
import type {TrustedOwner} from './model-c-personal';

const idSchema=z.string().regex(/^job:[a-f0-9]{64}$/);
const revisionSchema=z.strictObject({revision:z.string().regex(/^[1-9][0-9]{0,9}$/).transform(Number)});
type PublishedCheckpoint = {
  syncRevision?:number;runId?:string;contentRevision?:number;
  ledgerDigest?:string;observedCommit?:string;
};
function checkCatalog(before:PublishedCheckpoint|null,after:PublishedCheckpoint|null) {
  const complete=(v:PublishedCheckpoint|null)=>!!v &&
    Number.isSafeInteger(v.syncRevision) && (v.syncRevision??0)>0 &&
    Number.isSafeInteger(v.contentRevision) && (v.contentRevision??0)>0 &&
    !!v.runId && !!v.ledgerDigest && !!v.observedCommit;
  if(!complete(before) || !complete(after) ||
    before?.syncRevision!==after?.syncRevision || before?.runId!==after?.runId ||
    before?.contentRevision!==after?.contentRevision ||
    before?.ledgerDigest!==after?.ledgerDigest ||
    before?.observedCommit!==after?.observedCommit)
    throw new ModelCReadError('CATALOG_CHANGED',409);
}
function verifyOwner(env:ModelCLocalEnv,authenticatedOwner?:TrustedOwner) {
  if(!env.CATALOG||!env.PERSONAL)throw new ModelCReadError('database_unavailable',503);
  if(authenticatedOwner)return {catalog:env.CATALOG,personal:env.PERSONAL,owner:authenticatedOwner};
  if(!env.MODEL_C_TEST_OWNER || !/^synthetic-[a-z][a-z0-9-]{0,63}$/.test(env.MODEL_C_TEST_OWNER))
    throw new ModelCReadError('synthetic_owner_unavailable',403);
  return {catalog:env.CATALOG,personal:env.PERSONAL,owner:{ownerId:env.MODEL_C_TEST_OWNER}};
}
// An Access-authenticated user can read the catalog before their PERSONAL import.
// This exception is ONLY for an absent verified owner context, never for invalid
// schema, wrong scope, database faults, or unauthenticated local callers.
async function personalOverlayOrAbsent(
  catalog:D1Database,personal:D1Database,owner:TrustedOwner,ids:string[],
  authenticatedOwner?:TrustedOwner,
) {
  try { return await getModelCPersonalOverlays(catalog,personal,owner,ids); }
  catch(error) {
    if(authenticatedOwner && error instanceof ModelCPersonalReadError &&
       error.code==='PERSONAL_CONTEXT_UNAVAILABLE')return null;
    throw error;
  }
}
export async function readModelCOpportunities(env:ModelCLocalEnv,suffix:string,input:Record<string,string>,authenticatedOwner?:TrustedOwner) {
  const {catalog,personal,owner}=verifyOwner(env,authenticatedOwner);
  if(suffix==='jobs'){
    const filters=modelCCatalogQuerySchema.parse(input);
    const page=await listModelCCatalogJobs(catalog,filters);
    // A missing CATALOG publication is not a personal-data publication.
    if(!page.snapshot)return {...page,personalRevision:null,items:[]};
    const overlay=await personalOverlayOrAbsent(catalog,personal,owner,page.items.map(j=>j.id),authenticatedOwner);
    if(overlay && overlay.catalogRevision!==page.snapshot.syncRevision)
      throw new ModelCReadError('CATALOG_CHANGED',409);
    const now=(await getModelCCatalogSnapshot(catalog)).snapshot;
    checkCatalog(page.snapshot,now);
    return {...page,personalRevision:overlay?.personalRevision??null,appRevision:overlay?.appRevision??null,
      items:page.items.map(job=>({...job,personal:overlay?.items[job.id]??null}))};
  }
  if(!suffix.startsWith('jobs/'))throw new ModelCReadError('not_found',404);
  const id=idSchema.parse(suffix.slice('jobs/'.length));
  const {revision}=revisionSchema.parse(input);
  const page=await getModelCCatalogJob(catalog,id,revision);
  if(!page.snapshot)throw new ModelCReadError('NO_PUBLISHED_CATALOG',404);
  const overlay=await personalOverlayOrAbsent(catalog,personal,owner,[id],authenticatedOwner);
  if(overlay && overlay.catalogRevision!==page.snapshot.syncRevision)
    throw new ModelCReadError('CATALOG_CHANGED',409);
  const personalRow=overlay?.items[id]??null;
  const personalDetail=personalRow?await getModelCPersonalJob(catalog,personal,owner,id):null;
  if(personalDetail && (personalDetail.catalogRevision!==revision ||
    personalDetail.personalRevision!==overlay?.personalRevision))
    throw new ModelCReadError('CONTEXT_CHANGED',409);
  const now=(await getModelCCatalogSnapshot(catalog)).snapshot;
  checkCatalog(page.snapshot,now);
  return {...page,personalRevision:overlay?.personalRevision??null,appRevision:overlay?.appRevision??null,
    personal:personalRow,personalDetail};
}
