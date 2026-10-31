import {beforeAll,afterAll,describe,it,expect} from 'vitest';
import {Miniflare,convertV4MiniflareOptions} from 'miniflare';
import {applySchema} from '../tools/model-c-schema';
import {stageCatalog,publicationFixture,seedPersonal,jobId,hash,commit,owner} from './helpers/model-c-fixtures';
import {canonical,sha256} from '../shared/canonical';
import {captureSynthetic} from '../tools/model-c-schema';
import {getModelCPersonalSummary,listModelCPersonalJobs,getModelCPersonalJob} from '../worker/data/model-c-personal';
let runtime:Miniflare,seq=0;
beforeAll(()=>{runtime=new Miniflare(convertV4MiniflareOptions({modules:true,
 script:'export default {fetch(){return new Response("synthetic")}}',cf:false,compatibilityDate:'2026-10-29',
 d1Databases:Object.fromEntries(Array.from({length:24},(_,i)=>['DB'+i,'personal-reader-'+i]))}));});
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
  expect(detail.assessmentEvents.at(0)?.reportable).toBe(true);
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
  expect(b.items.at(0)?.assessment).toBeNull();
  const otherDetail=await getModelCPersonalJob(c,p,{ownerId:other},jobId);
  expect(otherDetail.decisionEvents).toEqual([]);
  expect(otherDetail.assessmentEvents).toEqual([]);
  await expect(getModelCPersonalJob(c,p,{ownerId:'missing'},jobId)).rejects.toMatchObject({code:'PERSONAL_CONTEXT_UNAVAILABLE'});
  const cursor=btoa(JSON.stringify({ownerDigest:await sha256(owner),personalRevision:1,catalogRevision:1,
    catalogRun:'run-one',personalDigest:hash,lastId:jobId})).replace(/\+/g,'-').replace(/\//g,'_').replace(/=+$/,'');
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
  expect((await listModelCPersonalJobs(c,p,{ownerId:owner})).items.at(0)?.reconciliation).toBe('STALE');
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
 it('labels an assessment CURRENT only when the published job fingerprint matches',async()=>{
  const {c,p}=await fixture();
  const ownerContext={ownerId:owner};
  // A missing catalog fingerprint must not validate a historical score.
  expect((await getModelCPersonalJob(c,p,ownerContext,jobId)).job.assessment?.freshness).toBe('UNVERIFIED');
  await c.prepare('UPDATE catalog_vacancy_current SET fingerprint=? WHERE job_id=?')
    .bind('opaque-fingerprint',jobId).run();
  expect((await getModelCPersonalJob(c,p,ownerContext,jobId)).job.assessment?.freshness).toBe('CURRENT');
  await c.prepare('UPDATE catalog_vacancy_current SET fingerprint=? WHERE job_id=?')
    .bind('new-fingerprint',jobId).run();
  const detail=await getModelCPersonalJob(c,p,ownerContext,jobId);
  expect(detail.job.assessment).toMatchObject({
    freshness:'STALE',fingerprint:'opaque-fingerprint',fitScore:75,
  });
  expect(detail.decisionEvents.at(0)).toMatchObject({fingerprint:'opaque-fingerprint',resultSha256:hash});
  expect(detail.assessmentEvents.at(0)).toMatchObject({fingerprint:'opaque-fingerprint',resultSha256:hash});
 });
 it('reports CONFLICT and refuses a VERIFIED state linked to mismatched receipts',async()=>{
  const {c,p}=await fixture();
  await p.prepare("UPDATE personal_reconciliation SET state='CONFLICT',error_code='SYNTHETIC_CONFLICT' WHERE owner_id=? AND job_id=?")
    .bind(owner,jobId).run();
  expect((await getModelCPersonalJob(c,p,{ownerId:owner},jobId)).job.reconciliation).toBe('CONFLICT');
  await p.prepare('INSERT INTO personal_catalog_receipts VALUES (?,1,1,?,?,?)')
    .bind('receipt:wrong',commit,'c'.repeat(64),hash).run();
  await p.prepare("UPDATE personal_reconciliation SET state='VERIFIED',receipt_id='receipt:wrong',error_code=NULL WHERE owner_id=? AND job_id=?")
    .bind(owner,jobId).run();
  expect((await getModelCPersonalJob(c,p,{ownerId:owner},jobId)).job.reconciliation).toBe('STALE');
 });
 it('does not modify CATALOG or PERSONAL when reading summary, pages and detail',async()=>{
  const {c,p}=await fixture();
  const beforeCatalog=(await captureSynthetic(c,'catalog')).sha256;
  const beforePersonal=(await captureSynthetic(p,'personal')).sha256;
  await getModelCPersonalSummary(c,p,{ownerId:owner});
  await listModelCPersonalJobs(c,p,{ownerId:owner});
  await getModelCPersonalJob(c,p,{ownerId:owner},jobId);
  expect((await captureSynthetic(c,'catalog')).sha256).toBe(beforeCatalog);
  expect((await captureSynthetic(p,'personal')).sha256).toBe(beforePersonal);
 });
 it('fails closed if the PERSONAL head changes between the first read and final consistency check',async()=>{
  const {c,p}=await fixture();
  let checks=0;
  const racingPersonal=new Proxy(p,{
    get(target,property) {
      if (property!=='prepare') return Reflect.get(target,property,target);
      return (sql:string)=>{
        const statement=target.prepare(sql);
        if (!sql.includes('SELECT revision,context_digest AS contextDigest FROM personal_heads'))
          return statement;
        return new Proxy(statement,{
          get(inner,key) {
            if (key!=='bind') return Reflect.get(inner,key,inner);
            return (ownerId:string)=>{
              const bound=inner.bind(ownerId);
              return new Proxy(bound,{
                get(ready,operation) {
                  if (operation!=='first') return Reflect.get(ready,operation,ready);
                  return async ()=>{
                    const row=await ready.first<{revision:number;contextDigest:string}>();
                    checks++;
                    return checks===2 && row ? {...row,revision:row.revision+1}:row;
                  };
                },
              });
            };
          },
        });
      };
    },
  });
  await expect(getModelCPersonalSummary(c,racingPersonal,{ownerId:owner}))
    .rejects.toMatchObject({code:'CONTEXT_CHANGED'});
  expect(checks).toBe(2);
 });
 it('provides bounded CATALOG display data and filters PERSONAL globally before pagination',async()=>{
  const {c,p}=await fixture();
  const initial=await listModelCPersonalJobs(c,p,{ownerId:owner},{view:'dismissed',q:'archived'});
  expect(initial.total).toBe(1);
  expect(initial.items.at(0)?.catalog).toMatchObject({
    company:'Synthetic Company',title:'Synthetic Analyst',
    companyId:'company:synthetic',lifecycle:'STILL_OPEN',
  });
  expect((await listModelCPersonalJobs(c,p,{ownerId:owner},{view:'applied'})).total).toBe(0);
  expect((await listModelCPersonalJobs(c,p,{ownerId:owner},{view:'to_apply'})).total).toBe(0);
  expect((await listModelCPersonalJobs(c,p,{ownerId:owner},{decision:'NOT_INTERESTED'})).total).toBe(1);
  expect((await listModelCPersonalJobs(c,p,{ownerId:owner},{reference:'DISMISSED'})).total).toBe(1);
  expect((await listModelCPersonalJobs(c,p,{ownerId:owner},{q:'unrelated'})).total).toBe(0);
  await p.prepare("INSERT INTO personal_job_refs VALUES (?,?,'Historical candidate',NULL,'UNKNOWN',?,'job_memory_jw1.json',?,1)")
    .bind(owner,'job:'+'2'.repeat(64),commit,hash).run();
  const first=await listModelCPersonalJobs(c,p,{ownerId:owner},{limit:1,view:'all'});
  expect(first.total).toBe(2);
  const second=await listModelCPersonalJobs(c,p,{ownerId:owner},{limit:1,view:'all',cursor:first.nextCursor});
  expect(second.items).toHaveLength(1);
  expect(second.items.at(0)?.catalog).toBeNull();
  await expect(listModelCPersonalJobs(c,p,{ownerId:owner},{limit:1,view:'applied',cursor:first.nextCursor}))
    .rejects.toMatchObject({code:'CURSOR_FILTER_MISMATCH'});
 });
 it('rejects wrong database scope and missing owner without issuing writes',async()=>{
  const {c,p}=await fixture();
  await expect(getModelCPersonalSummary(p,c,{ownerId:owner})).rejects.toMatchObject({code:'PERSONAL_SCHEMA_MISMATCH'});
  await expect(getModelCPersonalSummary(c,c,{ownerId:owner})).rejects.toMatchObject({code:'DATABASE_SCOPE_COLLISION'});
  await expect(getModelCPersonalSummary(c,p,{ownerId:''})).rejects.toThrow();
  await expect(listModelCPersonalJobs(c,p,{ownerId:owner},{cursor:'not-a-cursor'})).rejects.toMatchObject({code:'INVALID_CURSOR'});
 });
});
