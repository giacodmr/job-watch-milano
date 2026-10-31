import {beforeAll,afterAll,describe,expect,it} from 'vitest';
import {generateKeyPair,SignJWT,createLocalJWKSet,exportJWK} from 'jose';
import type {JWTVerifyGetKey} from 'jose';
import {Miniflare,convertV4MiniflareOptions} from 'miniflare';
import {applySchema} from '../tools/model-c-schema';
import {createOfflineServiceIngestionHarness} from '../worker/model-c-ingest-lab';
import {verifyServicePrincipal} from '../worker/model-c-service-auth';
import {prepareOfflineIngestPackets,submitOfflinePackets} from '../tools/model-c-ingest-offline-client';
import {validateChunk,validateRun} from '../shared/model-c-ingestion';
import {authenticatePrivateRequest} from '../worker/private-access';

const issuer='https://job-watch-tests.cloudflareaccess.com';
const aud='a'.repeat(64);
const host='sync.synthetic.invalid';
const client='c'.repeat(32)+'.access';
const keys={hostname:host,issuer,audience:aud,allowedClientId:client};
const base='https://'+host+'/api/model-c/sync/runs';
const payload={commitSha:'a'.repeat(40),manifestDigest:'b'.repeat(64),
  projectionDigest:'c'.repeat(64),planDigest:'d'.repeat(64),expectedRevision:0};
const example={kind:'job' as const,id:'job:'+'e'.repeat(64),companyId:'company:123',
  sourceId:null,title:'Synthetic analyst',location:'Milano',lifecycle:'NEW' as const,
  officialUrl:'https://example.test/role',fingerprint:null};
let runtime:Miniflare,db:D1Database,privateKey:CryptoKey,resolver:JWTVerifyGetKey;
const quota={syntheticVerified:true as const,writeUnitsRemaining:2000};
let serial=0;
async function token(claims:Record<string,unknown>={},signKey=privateKey){
  return new SignJWT({type:'app',sub:'',common_name:client,...claims})
    .setProtectedHeader({alg:'RS256',kid:'service-key'}).setIssuer(issuer)
    .setAudience(aud).setIssuedAt().setExpirationTime('10m').sign(signKey);
}
const request=(url:string,jwt:string,method='GET',data?:unknown,extra:Record<string,string>={})=>
  new Request(url,{method,headers:{'cf-access-jwt-assertion':jwt,
    ...(data===undefined?{}:{'content-type':'application/json'}),...extra},
    ...(data===undefined?{}:{body:JSON.stringify(data)})});
const packets=async(size=2)=>{
  // Include a unique pinned plan per test, preserving deterministic hashes.
  return prepareOfflineIngestPackets({...payload,planDigest:(++serial).toString(16).padStart(64,'0')},
    Array.from({length:size},(_,i)=>({...example,id:'job:'+String(i+1).padStart(64,'0')})),1);
};
const count=async(table:string)=>Number(await db.prepare('SELECT count(*) AS n FROM '+table).first('n'));
beforeAll(async()=>{
  runtime=new Miniflare(convertV4MiniflareOptions({modules:true,cf:false,
    script:'export default {fetch(){return new Response("offline")}}',
    compatibilityDate:'2026-10-29',d1Databases:{CATALOG:'m46-catalog',PERSONAL:'m46-personal'}}));
  db=await runtime.getD1Database('CATALOG');
  const personal=await runtime.getD1Database('PERSONAL');
  expect((await applySchema(db,'catalog')).applied).toBe(6);
  expect((await applySchema(personal,'personal')).applied).toBe(3);
  const pair=await generateKeyPair('RS256',{extractable:true});
  privateKey=pair.privateKey;
  const jwk=await exportJWK(pair.publicKey);
  resolver=createLocalJWKSet({keys:[{...jwk,alg:'RS256',kid:'service-key',use:'sig'}]});
});
afterAll(async()=>{await runtime?.dispose();});

describe('M46 cryptographically separated service identity',()=>{
  it('accepts only a verified RS256 service application JWT with empty sub and allowlisted common_name',async()=>{
    const jwt=await token();
    const p=await verifyServicePrincipal(request(base,jwt),keys,resolver);
    expect(p).toEqual({principalType:'service',clientId:client,capabilities:['catalog:stage']});
    await expect(authenticatePrivateRequest(request('https://jobs.example.com/',jwt),
      {APP_ENV:'private',PRIVATE_HOSTNAME:'jobs.example.com',PRIVATE_ACCESS_ISSUER:issuer,
        PRIVATE_ACCESS_AUD:aud,PRIVATE_ALLOWED_SUB:'access-user-123456789',
        PRIVATE_OWNER_ID:'personal-user-123456',CATALOG:db,PERSONAL:await runtime.getD1Database('PERSONAL')},
      resolver)).rejects.toMatchObject({code:'private_access_denied'});
  });
  it('denies browser users, forged principals, signed wrong audience/issuer, expiry, future nbf and unknown keys',async()=>{
    const h=createOfflineServiceIngestionHarness({catalog:db,auth:keys,keys:resolver,quota});
    const p=await packets(1);
    const bad=[
      await token({sub:'interactive-user',email:'user@example.test',common_name:undefined}),
      await token({common_name:'other-client-credential.access'}),
      await token({email:'user@example.test'}),
      await token({sub:'interactive-user'}),
      await token({},(await generateKeyPair('RS256')).privateKey),
      await new SignJWT({sub:'',common_name:client,type:'app'})
        .setProtectedHeader({alg:'RS256',kid:'service-key'}).setIssuer(issuer)
        .setAudience('x'.repeat(64)).setIssuedAt().setExpirationTime('10m').sign(privateKey),
      await new SignJWT({sub:'',common_name:client,type:'app'})
        .setProtectedHeader({alg:'RS256',kid:'service-key'})
        .setIssuer('https://other.cloudflareaccess.com').setAudience(aud)
        .setIssuedAt().setExpirationTime('10m').sign(privateKey),
      await new SignJWT({sub:'',common_name:client,type:'app'})
        .setProtectedHeader({alg:'RS256',kid:'service-key'}).setIssuer(issuer)
        .setAudience(aud).setIssuedAt(-900).setExpirationTime(-600).sign(privateKey),
      await new SignJWT({sub:'',common_name:client,type:'app'})
        .setProtectedHeader({alg:'RS256',kid:'service-key'}).setIssuer(issuer)
        .setAudience(aud).setIssuedAt().setNotBefore('10m').setExpirationTime('20m').sign(privateKey),
      await new SignJWT({sub:'',common_name:client,type:'app'})
        .setProtectedHeader({alg:'RS256',kid:'unknown-key'}).setIssuer(issuer)
        .setAudience(aud).setIssuedAt().setExpirationTime('10m').sign(privateKey),
    ];
    for(const jwt of bad)expect((await h(request(base,jwt,'POST',p.run))).status).toBeGreaterThanOrEqual(400);
    expect((await h(new Request(base,{method:'POST',body:JSON.stringify(p.run),
      headers:{'content-type':'application/json'}}))).status).toBe(401);
    expect((await h(request(base,await token(),'POST',p.run,{'Origin':'https://evil.test'}))).status).toBe(403);
    expect((await h(request(base,await token(),'POST',p.run,{'x-owner-id':'synthetic-owner'}))).status).toBe(403);
    expect((await h(request(base,await token(),'POST',p.run,{'cookie':'CF_Authorization=abc'}))).status).toBe(403);
    expect(await count('catalog_ingest_runs')).toBe(0);
  });
  it('requires real signed assertions, not unverified client-secret headers or unsupported algorithms',async()=>{
    const fake=new Request(base,{headers:{'CF-Access-Client-Id':client,'CF-Access-Client-Secret':'synthetic'}});
    await expect(verifyServicePrincipal(fake,keys,resolver))
      .rejects.toMatchObject({code:'service_browser_context_forbidden'});
    const hs=await new SignJWT({type:'app',sub:'',common_name:client})
      .setProtectedHeader({alg:'HS256',kid:'service-key'}).setIssuer(issuer)
      .setAudience(aud).setIssuedAt().setExpirationTime('10m')
      .sign(new Uint8Array(32).fill(1));
    await expect(verifyServicePrincipal(request(base,hs),keys,resolver))
      .rejects.toMatchObject({code:'service_auth_invalid'});
  });
});
describe('M46 local-only HTTP → real ephemeral D1 staging',()=>{
  it('accepts chunks out of order, idempotently replays and does not publish catalog or PERSONAL',async()=>{
    const jwt=await token(),p=await packets();
    const h=createOfflineServiceIngestionHarness({catalog:db,auth:keys,keys:resolver,quota});
    expect((await h(request(base,jwt,'POST',p.run))).status).toBe(201);
    expect((await h(request(base,jwt,'POST',p.run))).status).toBe(200);
    const url=base+'/'+p.run.runId+'/chunks';
    expect((await h(request(url,jwt,'POST',p.chunks[1]))).status).toBe(201);
    let state=await (await h(request(base+'/'+p.run.runId+'/status',jwt))).json() as {missing:number[];complete:boolean};
    expect(state.missing).toEqual([0]);expect(state.complete).toBe(false);
    expect((await h(request(url,jwt,'POST',p.chunks[0]))).status).toBe(201);
    expect((await h(request(url,jwt,'POST',p.chunks[0]))).status).toBe(200);
    state=await (await h(request(base+'/'+p.run.runId+'/status',jwt))).json() as typeof state;
    expect(state.complete).toBe(true);expect(state.missing).toEqual([]);
    expect(await count('catalog_ingest_chunks')).toBe(2);
    expect(await count('catalog_head')).toBe(0);
    expect(await count('catalog_vacancy_current')).toBe(0);
  });
  it('rejects mismatched digest, arbitrary SQL/owner fields, payload abuse and conflicting idempotency key',async()=>{
    const jwt=await token(),p=await packets(1);
    const h=createOfflineServiceIngestionHarness({catalog:db,auth:keys,keys:resolver,quota});
    const wrong={...p.run,manifestDigest:'f'.repeat(64)};
    expect((await h(request(base,jwt,'POST',wrong))).status).toBe(400);
    expect((await h(request(base,jwt,'POST',{...p.run,sql:'DROP TABLE catalog_head'}))).status).toBe(400);
    expect((await h(request(base,jwt,'POST',p.run))).status).toBe(201);
    const url=base+'/'+p.run.runId+'/chunks';
    const malicious={...p.chunks[0],records:[{...example,sql:'DROP TABLE catalog_head'}]};
    expect((await h(request(url,jwt,'POST',malicious))).status).toBe(400);
    expect((await h(request(url,jwt,'POST',p.chunks[0],{'x-owner-id':'evil'}))).status).toBe(403);
    const large=new Request(url,{method:'POST',headers:{'cf-access-jwt-assertion':jwt,
      'content-type':'application/json'},body:' '.repeat(13000)});
    expect((await h(large)).status).toBe(413);
    expect((await h(request(url,jwt,'POST',p.chunks[0]))).status).toBe(201);
    const conflictDigest='e'.repeat(64);
    const altered={...p.chunks[0],chunkDigest:conflictDigest,
      idempotencyKey:'f'.repeat(64)};
    expect((await h(request(url,jwt,'POST',altered))).status).toBe(400);
    const change=await prepareOfflineIngestPackets(
      {...payload,planDigest:p.run.planDigest},[{...example,title:'Changed'}],1);
    const realCollision={...change.chunks[0],runId:p.run.runId,
      idempotencyKey:await import('../shared/model-c-ingestion').then(x=>
        x.expectedIdempotencyKey(p.run.runId,0,change.chunks[0]!.chunkDigest))};
    expect((await h(request(url,jwt,'POST',realCollision))).status).toBe(409);
    expect(await count('catalog_head')).toBe(0);
  });
  it('denies unknown account budget and never permits PERSONAL writes',async()=>{
    const jwt=await token(),p=await packets(1);
    const h=createOfflineServiceIngestionHarness({catalog:db,auth:keys,keys:resolver});
    expect((await h(request(base,jwt,'POST',p.run))).status).toBe(503);
    const low=createOfflineServiceIngestionHarness({catalog:db,auth:keys,keys:resolver,
      quota:{syntheticVerified:true,writeUnitsRemaining:0}});
    expect((await low(request(base,jwt,'POST',p.run))).status).toBe(503);
    const enabled=createOfflineServiceIngestionHarness({catalog:db,auth:keys,keys:resolver,quota});
    expect((await enabled(request('https://'+host+'/api/model-c/personal/commands',jwt,'POST',{}))).status).toBe(404);
    expect(await count('catalog_head')).toBe(0);
  });
  it('rolls back aborted D1 batch, preserves receipt absence and fails safely',async()=>{
    const jwt=await token(),p=await packets(1);
    const h=createOfflineServiceIngestionHarness({catalog:db,auth:keys,keys:resolver,quota});
    expect((await h(request(base,jwt,'POST',p.run))).status).toBe(201);
    await db.prepare(`CREATE TRIGGER test_abort_m46 BEFORE INSERT ON catalog_ingest_chunks
       WHEN NEW.run_id='${p.run.runId}' BEGIN SELECT RAISE(ABORT,'synthetic_failure'); END`).run();
    const result=await h(request(base+'/'+p.run.runId+'/chunks',jwt,'POST',p.chunks[0]));
    expect(result.status).toBe(503);
    expect(await db.prepare('SELECT count(*) AS n FROM catalog_ingest_chunks WHERE run_id=?')
      .bind(p.run.runId).first('n')).toBe(0);
    await db.prepare('DROP TRIGGER test_abort_m46').run();
    expect((await h(request(base+'/'+p.run.runId+'/chunks',jwt,'POST',p.chunks[0]))).status).toBe(201);
  });
  it('serializes two concurrent duplicate writes with one receipt, rejects stale revisions',async()=>{
    const jwt=await token(),p=await packets(1);
    const h=createOfflineServiceIngestionHarness({catalog:db,auth:keys,keys:resolver,quota});
    expect((await h(request(base,jwt,'POST',p.run))).status).toBe(201);
    const path=base+'/'+p.run.runId+'/chunks';
    const replies=await Promise.all([h(request(path,jwt,'POST',p.chunks[0])),
      h(request(path,jwt,'POST',p.chunks[0]))]);
    expect(replies.map(r=>r.status).every(n=>[200,201,503].includes(n))).toBe(true);
    expect(await db.prepare('SELECT count(*) AS n FROM catalog_ingest_chunks WHERE run_id=?')
      .bind(p.run.runId).first('n')).toBe(1);
    const stale=await packets(1);
    stale.run.expectedRevision=1;
    expect((await h(request(base,jwt,'POST',stale.run))).status).toBe(400);
  });
  it('offline deterministic client sends no network requests, inspects receipts after uncertain delivery',async()=>{
    const jwt=await token(),p=await packets(1);
    const h=createOfflineServiceIngestionHarness({catalog:db,auth:keys,keys:resolver,quota});
    let dropped=false;
    const dispatcher=async (r:Request)=>{
      const real=await h(r);
      if(!dropped&&r.url.endsWith('/chunks')&&r.method==='POST'){
        dropped=true;return new Response('not acknowledged',{status:503});
      }
      return real;
    };
    const result=await submitOfflinePackets(p,dispatcher,jwt);
    expect(result.status).toBe('STAGED_NOT_PUBLISHED');
    expect(dropped).toBe(true);
    expect(await db.prepare('SELECT count(*) AS n FROM catalog_ingest_chunks WHERE run_id=?')
      .bind(p.run.runId).first('n')).toBe(1);
    expect(await count('catalog_head')).toBe(0);
  });
  it('keeps deployable Worker entrypoints isolated from the offline ingestion handler',async()=>{
    const {readFile}=await import('node:fs/promises');
    const entry=await readFile('worker/index.ts','utf8');
    const runtime=await readFile('worker/private-runtime.ts','utf8');
    expect(entry).not.toContain('model-c-ingest-lab');
    expect(entry).not.toContain('model-c-service-auth');
    expect(runtime).not.toContain('model-c-ingest-lab');
    expect(runtime).not.toContain('/api/model-c/sync/runs');
  });
  it('rejects invalid incoming wire fields before SQL; valid signed source digest alone is not Git provenance',async()=>{
    const p=await packets(1);
    await expect(validateRun({...p.run,ownerId:'injected'})).rejects.toThrow();
    await expect(validateChunk({...p.chunks[0],db:'PERSONAL'})).rejects.toThrow();
    expect(p.run.runId).toMatch(/^ingest:[a-f0-9]{64}$/);
  });
});

describe('M47 immutable staging capacity admission',()=>{
  it('rejects the ninth run in SQL, not through an unsafe pre-insert count',async()=>{
    const isolated=new Miniflare(convertV4MiniflareOptions({
      modules:true,cf:false,compatibilityDate:'2026-10-29',
      script:'export default {fetch(){return new Response("offline")}}',
      d1Databases:{CATALOG:'m47-capacity-race'},
    }));
    try{
      const catalog=await isolated.getD1Database('CATALOG');
      expect((await applySchema(catalog,'catalog')).applied).toBe(6);
      const h=createOfflineServiceIngestionHarness({
        catalog,auth:keys,keys:resolver,quota,
      });
      const jwt=await token();
      const list=await Promise.all(Array.from({length:11},()=>packets(1)));
      for(const p of list.slice(0,7)){
        expect((await h(request(base,jwt,'POST',p.run))).status).toBe(201);
      }
      // Exercise the boundary with genuinely overlapping, distinct requests.
      // Depending on SQLite scheduling, the loser is a 429 or a recoverable
      // 503; neither may advance the durable run count beyond eight.
      const concurrent=await Promise.all(list.slice(7,9).map(p=>
        h(request(base,jwt,'POST',p.run))));
      expect(concurrent.every(r=>[201,429,503].includes(r.status))).toBe(true);
      let n=Number(await catalog.prepare('SELECT count(*) AS n FROM catalog_ingest_runs').first('n'));
      expect(n).toBeLessThanOrEqual(8);
      if(n===7){
        expect((await h(request(base,jwt,'POST',list[9]!.run))).status).toBe(201);
        n=8;
      }
      expect(n).toBe(8);
      expect((await h(request(base,jwt,'POST',list[10]!.run))).status).toBe(429);
      expect(Number(await catalog.prepare('SELECT count(*) AS n FROM catalog_ingest_runs').first('n'))).toBe(8);
      const replay=await h(request(base,jwt,'POST',list[0]!.run));
      expect(replay.status).toBe(200);
      expect(Number(await catalog.prepare('SELECT count(*) AS n FROM catalog_head').first('n'))).toBe(0);
    }finally{await isolated.dispose();}
  });
});
