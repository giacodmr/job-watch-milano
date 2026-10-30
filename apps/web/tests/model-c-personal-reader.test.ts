import {beforeAll,afterAll,describe,it,expect} from 'vitest';
import {Miniflare,convertV4MiniflareOptions} from 'miniflare';
import {applySchema} from '../tools/model-c-schema';
import {stageCatalog,publicationFixture,seedPersonal,jobId,hash,commit,owner} from './helpers/model-c-fixtures';
import {canonical,sha256} from '../shared/canonical';
import {getModelCPersonalSummary,listModelCPersonalJobs,getModelCPersonalJob} from '../worker/data/model-c-personal';
let runtime:Miniflare,seq=0;
beforeAll(()=>{runtime=new Miniflare(convertV4MiniflareOptions({modules:true,
 script:'export default {fetch(){return new Response("synthetic")}}',cf:false,compatibilityDate:'2026-10-29',
 d1Databases:Object.fromEntries(Array.from({length:15},(_,i)=>['DB'+i,'personal-reader-'+i]))}));});
afterAll(async()=>{await runtime?.dispose();});
async function fixture() {
 const c=await runtime.getD1Database('DB'+seq++), p=await runtime.getD1Database('DB'+seq++);
 await applySchema(c,'catalog');await applySchema(p,'personal');
 await stageCatalog(c);await c.batch(publicationFixture(c,'run-one'));
 await seedPersonal(p);
 return {c,p};
}
describe('inactive trusted-owner Model C personal read service',()=>{
 it('preserves explicit decisions, private assessments and archived captures, without promoting PENDING to VERIFIED',async()=>{
  const {c,p}=await fixture();
  expect(await getModelCPersonalSummary(c,p,{ownerId:owner})).toMatchObject({
    personalRevision:1,catalogRevision:1,counts:{referencesCount:1,decisionsCount:1,assessmentsCount:1},
    productionAccess:false,
  });
  const page=await listModelCPersonalJobs(c,p,{ownerId:owner});
  expect(page).toMatchObject({total:1,nextCursor:null,items:[{
    jobId,decision:'NOT_INTERESTED',reconciliation:'PENDING',knownIdentity:true,
    currentlyVisible:true,activeReferences:['DISMISSED'],
    lastKnownLifecycle:'CLOSED',
    assessment:{method:'chatgpt_semantic_full_jd',fitScore:75,reportable:true},
  }]});
  const detail=await getModelCPersonalJob(c,p,{ownerId:owner},jobId);
  expect(detail.decisionEvents).toHaveLength(1);
  expect(detail.assessmentEvents).toHaveLength(1);
  expect(detail.assessmentEvents[0].reportable).toBe(true);
  expect(await p.prepare('SELECT count(*) AS n FROM personal_audit').first('n')).toBe(1);
 });
 it('restricts every personal read by owner and rejects cross-owner cursors',async()=>{
  const {c,p}=await fixture();
  const other='other-synthetic-owner';
  await p.prepare('INSERT INTO personal_owners VALUES (?)').bind(other).run();
  await p.prepare('INSERT INTO personal_heads VALUES (?,1,?,?)').bind(other,hash,commit).run();
  await p.prepare(`INSERT INTO personal_job_refs VALUES (?,?,'Other owner',NULL,NULL,?,'job_memory_jw1.json',?,1)`).bind(other,jobId,commit,hash).run();
  const a=await listModelCPersonalJobs(c,p,{ownerId:owner});
  const b=await listModelCPersonalJobs(c,p,{ownerId:other});
  expect(a.items).toHaveLength(1);expect(b.items).toHaveLength(1);
  expect(b.items[0]).toMatchObject({decision:null,activeReferences:[],capturedTitle:'Other owner',reconciliation:'PENDING'});
  expect(b.items[0].assessment).toBeNull();
  await expect(getModelCPersonalJob(c,p,{ownerId:'missing'},jobId)).rejects.toMatchObject({code:'PERSONAL_CONTEXT_UNAVAILABLE'});
  const cursor=btoa(JSON.stringify({ownerDigest:await sha256(owner),personalRevision:1,catalogRevision:1,
    catalogRun:'run-one',lastId:jobId})).replace(/\+/g,'-').replace(/\//g,'_').replace(/=+$/,'');
  await expect(listModelCPersonalJobs(c,p,{ownerId:other},{cursor})).rejects.toMatchObject({code:'CURSOR_OWNER_MISMATCH'});
 });
 it('recognizes verified receipts only when anchored to CURRENT catalog head and personal revision',async()=>{
  const {c,p}=await fixture();
  const headDigest=await sha256(canonical({syncRevision:1,run:'run-one',contentRevision:1,ledgerRevision:1,ledgerDigest:hash}));
  await p.prepare('INSERT INTO personal_catalog_receipts VALUES (?,1,1,?,?,?)')
    .bind('receipt:synthetic',commit,hash,headDigest).run();
  await p.prepare("UPDATE personal_reconciliation SET state='VERIFIED',receipt_id='receipt:synthetic' WHERE owner_id=? AND job_id=?")
    .bind(owner,jobId).run();
  expect((await getModelCPersonalJob(c,p,{ownerId:owner},jobId)).job.reconciliation).toBe('VERIFIED');
  await stageCatalog(c,'run-two',1,2,'c'.repeat(64));
  await c.batch(publicationFixture(c,'run-two',1,2));
  expect((await getModelCPersonalJob(c,p,{ownerId:owner},jobId)).job.reconciliation).toBe('STALE');
  await p.prepare('UPDATE personal_heads SET revision=2 WHERE owner_id=?').bind(owner).run();
  expect((await listModelCPersonalJobs(c,p,{ownerId:owner})).items[0].reconciliation).toBe('STALE');
 });
 it('keeps unknown identities visible only to their owner, never treats them as VERIFIED',async()=>{
  const {c,p}=await fixture(),missing='job:'+'2'.repeat(64);
  await p.prepare("INSERT INTO personal_job_refs VALUES (?,?,'Old archived capture',NULL,'UNKNOWN',?,'job_memory_jw1.json',?,1)")
    .bind(owner,missing,commit,hash).run();
  const page=await listModelCPersonalJobs(c,p,{ownerId:owner},{limit:1});
  expect(page.total).toBe(2);expect(page.nextCursor).not.toBeNull();
  const second=await listModelCPersonalJobs(c,p,{ownerId:owner},{limit:1,cursor:page.nextCursor!});
  expect(second.items).toHaveLength(1);
  const unresolved=await getModelCPersonalJob(c,p,{ownerId:owner},missing);
  expect(unresolved.job).toMatchObject({knownIdentity:false,currentlyVisible:false,reconciliation:'UNRESOLVED_REFERENCE'});
  await expect(getModelCPersonalJob(c,p,{ownerId:owner},'bad-id')).rejects.toThrow();
  await expect(listModelCPersonalJobs(c,p,{ownerId:owner},{limit:51})).rejects.toThrow();
 });
 it('rejects wrong database scope and missing owner without issuing writes',async()=>{
  const {c,p}=await fixture();
  await expect(getModelCPersonalSummary(p,c,{ownerId:owner})).rejects.toMatchObject({code:'PERSONAL_SCHEMA_MISMATCH'});
  await expect(getModelCPersonalSummary(c,c,{ownerId:owner})).rejects.toMatchObject({code:'DATABASE_SCOPE_COLLISION'});
  await expect(getModelCPersonalSummary(c,p,{ownerId:''})).rejects.toThrow();
  await expect(listModelCPersonalJobs(c,p,{ownerId:owner},{cursor:'not-a-cursor'})).rejects.toMatchObject({code:'INVALID_CURSOR'});
 });
});
