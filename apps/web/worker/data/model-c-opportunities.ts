// Private synthetic-only composition. CATALOG endpoints remain strictly public metadata.
import {z} from 'zod';
import {
  getModelCCatalogSnapshot,getModelCCatalogJob,listModelCCatalogJobs,
  modelCCatalogQuerySchema,ModelCReadError,
} from './data/model-c-catalog';
import {getModelCPersonalJob,getModelCPersonalOverlays} from './data/model-c-personal';
import type {ModelCLocalEnv} from './model-c-local-api';

const idSchema=z.string().regex(/^job:[a-f0-9]{64}$/);
const revisionSchema=z.strictObject({revision:z.string().regex(/^[1-9][0-9]{0,9}$/).transform(Number)});
function checkCatalog(before: {syncRevision:number;runId:string;contentRevision:number;ledgerDigest:string;observedCommit:string}|null,
  after: typeof before) {
  if(!before || !after ||
    before.syncRevision!==after.syncRevision || before.runId!==after.runId ||
    before.contentRevision!==after.contentRevision ||
    before.ledgerDigest!==after.ledgerDigest ||
    before.observedCommit!==after.observedCommit)
    throw new ModelCReadError('CATALOG_CHANGED',409);
}
function verifyOwner(env:ModelCLocalEnv) {
  if(!env.CATALOG||!env.PERSONAL)throw new ModelCReadError('database_unavailable',503);
  if(!env.MODEL_C_TEST_OWNER || !/^synthetic-[a-z][a-z0-9-]{0,63}$/.test(env.MODEL_C_TEST_OWNER))
    throw new ModelCReadError('synthetic_owner_unavailable',403);
  return {catalog:env.CATALOG,personal:env.PERSONAL,owner:{ownerId:env.MODEL_C_TEST_OWNER}};
}
export async function readModelCOpportunities(env:ModelCLocalEnv,suffix:string,input:Record<string,string>) {
  const {catalog,personal,owner}=verifyOwner(env);
  if(suffix==='jobs'){
    const filters=modelCCatalogQuerySchema.parse(input);
    const page=await listModelCCatalogJobs(catalog,filters);
    // A missing CATALOG publication is not a personal-data publication.
    if(!page.snapshot)return {...page,personalRevision:null,items:[]};
    const overlay=await getModelCPersonalOverlays(catalog,personal,owner,page.items.map(j=>j.id));
    if(overlay.catalogRevision!==page.snapshot.syncRevision)
      throw new ModelCReadError('CATALOG_CHANGED',409);
    const now=(await getModelCCatalogSnapshot(catalog)).snapshot;
    checkCatalog(page.snapshot,now);
    return {...page,personalRevision:overlay.personalRevision,
      items:page.items.map(job=>({...job,personal:overlay.items[job.id]??null}))};
  }
  if(!suffix.startsWith('jobs/'))throw new ModelCReadError('not_found',404);
  const id=idSchema.parse(suffix.slice('jobs/'.length));
  const {revision}=revisionSchema.parse(input);
  const page=await getModelCCatalogJob(catalog,id,revision);
  const overlay=await getModelCPersonalOverlays(catalog,personal,owner,[id]);
  if(overlay.catalogRevision!==page.snapshot.syncRevision)
    throw new ModelCReadError('CATALOG_CHANGED',409);
  const personalRow=overlay.items[id]??null;
  const personalDetail=personalRow?await getModelCPersonalJob(catalog,personal,owner,id):null;
  if(personalDetail && (personalDetail.catalogRevision!==revision ||
    personalDetail.personalRevision!==overlay.personalRevision))
    throw new ModelCReadError('CONTEXT_CHANGED',409);
  const now=(await getModelCCatalogSnapshot(catalog)).snapshot;
  checkCatalog(page.snapshot,now);
  return {...page,personalRevision:overlay.personalRevision,personal:personalRow,personalDetail};
}
