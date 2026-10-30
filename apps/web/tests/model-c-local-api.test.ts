import {readFile,readdir} from 'node:fs/promises';
import {build} from 'esbuild';
import {Miniflare,convertV4MiniflareOptions} from 'miniflare';
import {beforeAll,afterAll,describe,expect,it} from 'vitest';
import {z} from 'zod';
import worker from '../worker/index';
import {applySchema,captureSynthetic} from '../tools/model-c-schema';
import {stageCatalog,publicationFixture,seedPersonal,hash,commit,jobId,owner} from './helpers/model-c-fixtures';
import {canonical,sha256} from '../shared/canonical';

const unknown='job:'+'2'.repeat(64);
const other='synthetic-other';
let runtime:Miniflare, catalog:D1Database, personal:D1Database, v1:D1Database;
const endpoint=(path:string,opts?:RequestInit)=>runtime.dispatchFetch('http://localhost'+path,opts);
const pageSchema=z.strictObject({total:z.number(),nextCursor:z.string().nullable(),items:z.array(z.unknown()).max(50)});
const firstResponse=async (path:string)=> {
  const response=await endpoint(path);expect(response.status).toBe(200);return response;
};

beforeAll(async()=>{
  const bundle=await build({entryPoints:['worker/index.ts'],bundle:true,write:false,
    format:'esm',platform:'browser',target:'es2023'});
  const script=bundle.outputFiles.at(0)?.text;
  if(!script)throw Error('MISSING_WORKER_BUNDLE');
  runtime=new Miniflare(convertV4MiniflareOptions({
    modules:true,script,cf:false,compatibilityDate:'2026-10-29',
    bindings:{APP_ENV:'local',MODEL_C_LOCAL_API:'synthetic-only',MODEL_C_TEST_OWNER:owner},
    d1Databases:{DB:'model-c-api-v1',CATALOG:'model-c-api-catalog',PERSONAL:'model-c-api-personal'},
  }));
  catalog=await runtime.getD1Database('CATALOG');
  personal=await runtime.getD1Database('PERSONAL');
  v1=await runtime.getD1Database('DB');
  await applySchema(catalog,'catalog');
  await applySchema(personal,'personal');
  for(const name of (await readdir('migrations')).filter(n=>n.endsWith('.sql')).sort()) {
    const file=await readFile('migrations/'+name,'utf8');
    for(const statement of file.split('-- statement-breakpoint'))
      if(statement.trim())await v1.prepare(statement).run();
  }
  await stageCatalog(catalog);
  await seedPersonal(personal);
  await personal.prepare('INSERT INTO personal_owners VALUES (?)').bind(other).run();
  await personal.prepare('INSERT INTO personal_heads VALUES (?,1,?,?)').bind(other,hash,commit).run();
  await personal.prepare("INSERT INTO personal_job_refs VALUES (?,?,'Owner B private title',NULL,NULL,?,'job_memory_jw1.json',?,1)")
    .bind(other,jobId,commit,hash).run();
});
afterAll(async()=>{await runtime?.dispose()});

describe('PR #38: real Worker HTTP / CATALOG+PERSONAL ephemeral D1',()=>{
  it('keeps Model C staging unpublished while V1 routes remain unchanged',async()=>{
    const snap=await firstResponse('/api/model-c/catalog/snapshot');
    expect(await snap.json()).toEqual({snapshot:null,productionAccess:false});
    const list=await firstResponse('/api/model-c/catalog/jobs');
    expect(await list.json()).toMatchObject({items:[],total:0,snapshot:null});
    const privateResp=await endpoint('/api/model-c/personal/summary');
    expect(privateResp.status).toBe(503);
    expect(await privateResp.json()).toEqual({error:'NO_PUBLISHED_CATALOG'});
    const v1health=await endpoint('/api/health');
    expect(v1health.status).toBe(200);
    const v1snapshot=await endpoint('/api/snapshot');
    expect(v1snapshot.status).toBe(200);
    expect(await v1snapshot.json()).toMatchObject({snapshot:null,productionAccess:false});
    const oldCommand=await endpoint('/api/commands',{method:'POST',body:'not-an-action'});
    expect(oldCommand.status).toBe(501);
  });
  it('reads published CATALOG snapshot, list, provenance and aliases through HTTP',async()=>{
    await catalog.batch(publicationFixture(catalog,'run-one'));
    const snapshot=await firstResponse('/api/model-c/catalog/snapshot');
    expect(await snapshot.json()).toMatchObject({
      productionAccess:false,snapshot:{syncRevision:1,runId:'run-one',currentJobs:1,
        identityCount:1,mappingCount:2},
    });
    const list=await firstResponse('/api/model-c/catalog/jobs?q=Synthetic&limit=1');
    const data=await list.json();
    expect(data).toMatchObject({total:1,nextCursor:null,items:[{
      id:jobId,title:'Synthetic Analyst',company:'Synthetic Company',kind:'OPPORTUNITY',
      originPath:'current_jobs_jw1.json',
    }]});
    expect(JSON.stringify(data)).not.toContain('NOT_INTERESTED');
    expect(JSON.stringify(data)).not.toContain('Synthetic bounded summary');
    const detail=await firstResponse('/api/model-c/catalog/jobs/'+jobId+'?revision=1');
    expect(await detail.json()).toMatchObject({job:{id:jobId,originCommit:commit},
      aliases:['Synthetic Company::current','Synthetic Company::old']});
    expect(detail.headers.get('Cache-Control')).toBe('no-store');
    expect(detail.headers.get('X-Content-Type-Options')).toBe('nosniff');
    expect(detail.headers.get('Access-Control-Allow-Origin')).toBeNull();
  });
  it('filters CATALOG and rejects invalid or duplicated HTTP parameters',async()=>{
    const filtered=await firstResponse('/api/model-c/catalog/jobs?q=synthetic&companyId=company%3Asynthetic&kind=OPPORTUNITY&batch=jw1');
    expect(await filtered.json()).toMatchObject({total:1});
    for(const query of ['?kind=AI_QUEUE','?q=%25_%5B%5D','?companyId=wrong','?lifecycle=UPDATED']){
      const r=await firstResponse('/api/model-c/catalog/jobs'+query);
      expect(await r.json()).toMatchObject({total:0,items:[]});
    }
    const invalid=[
      '/api/model-c/catalog/snapshot?other=1',
      '/api/model-c/catalog/jobs?limit=101',
      '/api/model-c/catalog/jobs?limit=1&limit=2',
      '/api/model-c/catalog/jobs?cursor=%%%25',
      '/api/model-c/catalog/jobs?unexpected=secret',
      '/api/model-c/catalog/jobs/bad-id?revision=1',
      '/api/model-c/catalog/jobs/'+jobId,
      '/api/model-c/catalog/jobs/'+jobId+'?revision=1e2',
      '/api/model-c/catalog/jobs/'+jobId+'?revision=0',
      '/api/model-c/personal/summary?ownerId='+other,
      '/api/model-c/personal/jobs?limit=51',
      '/api/model-c/personal/jobs?cursor=invalid',
    ];
    for(const path of invalid) {
      const r=await endpoint(path);
      expect(r.status,path).toBe(400);
      expect(r.headers.get('Cache-Control')).toBe('no-store');
    }
    const missing=await endpoint('/api/model-c/catalog/jobs/'+unknown+'?revision=1');
    expect(missing.status).toBe(404);
    expect(await missing.json()).toEqual({error:'JOB_NOT_CURRENT'});
  });
  it('exposes PERSONAL summary, decision pointer, assessment and original event history over HTTP',async()=>{
    const sum=await firstResponse('/api/model-c/personal/summary');
    expect(await sum.json()).toMatchObject({personalRevision:1,catalogRevision:1,
      counts:{referencesCount:1,decisionsCount:1,assessmentsCount:1},productionAccess:false});
    const list=await firstResponse('/api/model-c/personal/jobs');
    expect(await list.json()).toMatchObject({total:1,items:[{
      jobId,decision:'NOT_INTERESTED',currentlyVisible:true,knownIdentity:true,
      reconciliation:'PENDING',activeReferences:['DISMISSED'],
      assessment:{fitScore:75,freshness:'UNVERIFIED'},
    }]});
    const detail=await firstResponse('/api/model-c/personal/jobs/'+jobId);
    expect(await detail.json()).toMatchObject({job:{jobId,decision:'NOT_INTERESTED'},
      decisionEvents:[{decision:'NOT_INTERESTED',resultSha256:hash}],
      assessmentEvents:[{method:'chatgpt_semantic_full_jd',resultSha256:hash}]});
  });
  it('does not allow clients to choose an owner and refuses unauthorized runtime access',async()=>{
    for(const header of ['x-owner-id','x-user-id','x-job-watch-owner','x-actor-ref']){
      const r=await endpoint('/api/model-c/personal/summary',{headers:{[header]:other}});
      expect(r.status).toBe(403);
      expect(await r.json()).toEqual({error:'owner_override_forbidden'});
    }
    const spoof=await endpoint('/api/model-c/personal/jobs',{
      headers:{'Cf-Access-Jwt-Assertion':'fake.jwt.signature',cookie:'ownerId='+other}});
    expect(spoof.status).toBe(200);
    expect(JSON.stringify(await spoof.json())).not.toContain('Owner B private title');
    const cross=await endpoint('/api/model-c/personal/jobs',{headers:{origin:'https://evil.example.test'}});
    expect(cross.status).toBe(403);
    const remote=await runtime.dispatchFetch('https://example.test/api/model-c/personal/jobs',{
      headers:{'Cf-Access-Jwt-Assertion':'fake.jwt.signature'}});
    expect(remote.status).toBe(403);
    expect(await remote.json()).toEqual({error:'remote_runtime_disabled'});
    const off=await worker.fetch(new Request('http://localhost/api/model-c/personal/jobs'),
      {APP_ENV:'local',CATALOG:catalog,PERSONAL:personal,MODEL_C_TEST_OWNER:owner});
    expect(off.status).toBe(404);
    const disabled=await worker.fetch(new Request('http://localhost/api/model-c/personal/jobs'),
      {APP_ENV:'production',MODEL_C_LOCAL_API:'synthetic-only',CATALOG:catalog,PERSONAL:personal,MODEL_C_TEST_OWNER:owner});
    expect(disabled.status).toBe(403);
    const missingOwner=await worker.fetch(new Request('http://localhost/api/model-c/personal/summary'),
      {APP_ENV:'local',MODEL_C_LOCAL_API:'synthetic-only',CATALOG:catalog,PERSONAL:personal});
    expect(missingOwner.status).toBe(403);
  });
  it('scopes same-job facts by trusted server owner even with a colliding identity',async()=>{
    const otherResponse=await worker.fetch(new Request('http://localhost/api/model-c/personal/jobs/'+jobId),
      {APP_ENV:'local',MODEL_C_LOCAL_API:'synthetic-only',MODEL_C_TEST_OWNER:other,CATALOG:catalog,PERSONAL:personal});
    expect(otherResponse.status).toBe(200);
    expect(await otherResponse.json()).toMatchObject({
      job:{capturedTitle:'Owner B private title',decision:null,activeReferences:[],assessment:null},
      decisionEvents:[],assessmentEvents:[],
    });
    const main=await firstResponse('/api/model-c/personal/jobs/'+jobId);
    expect(JSON.stringify(await main.json())).not.toContain('Owner B private title');
    const unknownRef=await endpoint('/api/model-c/personal/jobs/'+unknown);
    expect(unknownRef.status).toBe(404);
  });
  it('enforces missing bindings and missing routes without leaking private content',async()=>{
    const env={APP_ENV:'local',MODEL_C_LOCAL_API:'synthetic-only',MODEL_C_TEST_OWNER:owner};
    const noCatalog=await worker.fetch(new Request('http://localhost/api/model-c/catalog/jobs'),env);
    expect(noCatalog.status).toBe(503);
    const noPersonal=await worker.fetch(new Request('http://localhost/api/model-c/personal/jobs'),
      {...env,CATALOG:catalog});
    expect(noPersonal.status).toBe(503);
    const wrongScope=await worker.fetch(new Request('http://localhost/api/model-c/personal/jobs'),
      {...env,CATALOG:catalog,PERSONAL:v1});
    expect(wrongScope.status).toBe(503);
    expect(JSON.stringify(await wrongScope.json())).not.toContain('SELECT');
    const post=await endpoint('/api/model-c/catalog/jobs',{method:'POST',body:'no writes'});
    expect(post.status).toBe(405);
    expect(post.headers.get('Allow')).toBe('GET');
    const unknownRoute=await endpoint('/api/model-c/unknown');
    expect(unknownRoute.status).toBe(404);
    expect((await unknownRoute.text())).not.toContain('<html');
    const other=await endpoint('/api/model-c/personal/private-route');
    expect(other.status).toBe(404);
  });
  it('supports owner-bound pagination, unresolved captures and stale cursors',async()=>{
    await personal.prepare("INSERT INTO personal_job_refs VALUES (?,?,'Old private capture',NULL,'UNKNOWN',?,'job_memory_jw1.json',?,1)")
      .bind(owner,unknown,commit,hash).run();
    const p1=pageSchema.parse(await (await firstResponse('/api/model-c/personal/jobs?limit=1')).json());
    expect(p1.total).toBe(2);
    expect(p1.nextCursor).not.toBeNull();
    const p2=pageSchema.parse(await (await firstResponse('/api/model-c/personal/jobs?limit=1&cursor='+encodeURIComponent(p1.nextCursor??''))).json());
    expect(p2.items).toHaveLength(1);
    expect(p2.nextCursor).toBeNull();
    const missing=await firstResponse('/api/model-c/personal/jobs/'+unknown);
    expect(await missing.json()).toMatchObject({job:{jobId:unknown,currentlyVisible:false,knownIdentity:false,reconciliation:'UNRESOLVED_REFERENCE'}});
    const crossCursor=await worker.fetch(new Request('http://localhost/api/model-c/personal/jobs?cursor='+encodeURIComponent(p1.nextCursor??'')),
      {APP_ENV:'local',MODEL_C_LOCAL_API:'synthetic-only',MODEL_C_TEST_OWNER:other,CATALOG:catalog,PERSONAL:personal});
    expect(crossCursor.status).toBe(403);
  });
  it('checks trusted receipt state, stale receipt, conflict and fingerprint freshness over HTTP',async()=>{
    const digest=await sha256(canonical({syncRevision:1,run:'run-one',contentRevision:1,ledgerRevision:1,ledgerDigest:hash}));
    await personal.prepare('INSERT INTO personal_catalog_receipts VALUES (?,1,1,?,?,?)')
      .bind('receipt:synthetic',commit,hash,digest).run();
    await personal.prepare("UPDATE personal_reconciliation SET state='VERIFIED',receipt_id='receipt:synthetic' WHERE owner_id=? AND job_id=?")
      .bind(owner,jobId).run();
    const verified=await firstResponse('/api/model-c/personal/jobs/'+jobId);
    expect(await verified.json()).toMatchObject({job:{reconciliation:'VERIFIED'}});
    await catalog.prepare('UPDATE catalog_vacancy_current SET fingerprint=? WHERE job_id=?')
      .bind('opaque-fingerprint',jobId).run();
    const current=await firstResponse('/api/model-c/personal/jobs/'+jobId);
    expect(await current.json()).toMatchObject({job:{assessment:{freshness:'CURRENT'}}});
    await catalog.prepare('UPDATE catalog_vacancy_current SET fingerprint=? WHERE job_id=?')
      .bind('updated-fingerprint',jobId).run();
    const staleScore=await firstResponse('/api/model-c/personal/jobs/'+jobId);
    expect(await staleScore.json()).toMatchObject({job:{assessment:{freshness:'STALE'}}});
    await personal.prepare("UPDATE personal_reconciliation SET state='CONFLICT',error_code='CONFLICT_TEST' WHERE owner_id=? AND job_id=?")
      .bind(owner,jobId).run();
    const conflict=await firstResponse('/api/model-c/personal/jobs/'+jobId);
    expect(await conflict.json()).toMatchObject({job:{reconciliation:'CONFLICT'}});
    await personal.prepare("UPDATE personal_reconciliation SET state='VERIFIED',receipt_id='receipt:synthetic',error_code=NULL WHERE owner_id=? AND job_id=?")
      .bind(owner,jobId).run();
    await personal.prepare('UPDATE personal_heads SET revision=2 WHERE owner_id=?').bind(owner).run();
    const stale=await firstResponse('/api/model-c/personal/jobs/'+jobId);
    expect(await stale.json()).toMatchObject({job:{reconciliation:'STALE'}});
  });
  it('performs zero D1 writes during real HTTP read requests',async()=>{
    const beforeCat=(await captureSynthetic(catalog,'catalog')).sha256;
    const beforePersonal=(await captureSynthetic(personal,'personal')).sha256;
    for(const path of ['/api/model-c/catalog/snapshot','/api/model-c/catalog/jobs',
      '/api/model-c/catalog/jobs/'+jobId+'?revision=1','/api/model-c/personal/summary',
      '/api/model-c/personal/jobs','/api/model-c/personal/jobs/'+jobId]){
      const r=await endpoint(path);
      expect(r.status,path).toBe(200);
    }
    expect((await captureSynthetic(catalog,'catalog')).sha256).toBe(beforeCat);
    expect((await captureSynthetic(personal,'personal')).sha256).toBe(beforePersonal);
  });
  it('fails stale CATALOG cursor/detail after a new published run and keeps private history',async()=>{
    const cursor=btoa(JSON.stringify({revision:1,runId:'run-one',lastId:'job:'+'0'.repeat(64),filters:canonical({q:''})}))
      .replace(/\+/g,'-').replace(/\//g,'_').replace(/=+$/,'');
    const before=await endpoint('/api/model-c/catalog/jobs?cursor='+encodeURIComponent(cursor));
    expect(before.status).toBe(200);
    await stageCatalog(catalog,'run-two',1,2,'c'.repeat(64));
    await catalog.batch(publicationFixture(catalog,'run-two',1,2));
    const oldCursor=await endpoint('/api/model-c/catalog/jobs?cursor='+encodeURIComponent(cursor));
    expect(oldCursor.status).toBe(409);
    const oldDetail=await endpoint('/api/model-c/catalog/jobs/'+jobId+'?revision=1');
    expect(oldDetail.status).toBe(409);
    const personalSnapshot=await firstResponse('/api/model-c/personal/jobs/'+jobId);
    expect(await personalSnapshot.json()).toMatchObject({job:{reconciliation:'STALE',decision:'NOT_INTERESTED'}});
  });
});
