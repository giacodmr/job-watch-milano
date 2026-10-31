import {readFile} from 'node:fs/promises';
import {describe,it,expect,beforeAll,afterAll} from 'vitest';
import {SignJWT,generateKeyPair,exportJWK,createLocalJWKSet} from 'jose';
import type {JWTVerifyGetKey} from 'jose';
import {Miniflare,convertV4MiniflareOptions} from 'miniflare';
import {build} from 'esbuild';
import worker from '../worker/index';
import {applySchema} from '../tools/model-c-schema';
import {stageCatalog,publicationFixture,seedPersonal,owner,hash,commit,jobId} from './helpers/model-c-fixtures';
import {authenticatePrivateRequest,privateAccessConfig,privateRequestPolicy} from '../worker/private-access';
import type {PrivateAccessEnv} from '../worker/private-access';
import {handlePrivateRuntime,privateD1ErrorCode} from '../worker/private-runtime';

const issuer='https://job-watch-tests.cloudflareaccess.com';
const audience='a'.repeat(64);
const host='jobs.example.com';
const sub='access-user-123456789';
const person='personal-user-123456';
const addr='https://'+host;
const envConfig={APP_ENV:'private',PRIVATE_HOSTNAME:host,PRIVATE_ACCESS_ISSUER:issuer,
  PRIVATE_ACCESS_AUD:audience,PRIVATE_ALLOWED_SUB:sub,PRIVATE_OWNER_ID:person};
let runtime:Miniflare,catalog:D1Database,personal:D1Database,verifyKey:JWTVerifyGetKey;
let privateKey:CryptoKey;
const req=(path='/',token?:string,options?:RequestInit)=>new Request(addr+path,{
  ...options,headers:{...(token?{'Cf-Access-Jwt-Assertion':token}:{}),...options?.headers},
});
async function jwt(overrides:Record<string,unknown>={},key=privateKey){
  const payload={sub,email:'synthetic-user@example.test',type:'app',...overrides};
  return new SignJWT(payload).setProtectedHeader({alg:'RS256',kid:'valid-key'})
    .setIssuer(issuer).setAudience(audience).setIssuedAt().setNotBefore('0s')
    .setExpirationTime('10m').sign(key);
}
function env():PrivateAccessEnv{return {...envConfig,CATALOG:catalog,PERSONAL:personal};}
const error=async(fn:()=>Promise<unknown>)=>{try{await fn();throw Error('EXPECTED_AUTH_REJECTION');}catch(e){
  if(e instanceof Error&&e.message==='EXPECTED_AUTH_REJECTION')throw e;
  expect(e).toMatchObject({status:expect.any(Number)});return e;
}};

beforeAll(async()=>{
  const bundle=await build({entryPoints:['worker/index.ts'],bundle:true,write:false,
    format:'esm',platform:'browser',target:'es2023'});
  runtime=new Miniflare(convertV4MiniflareOptions({modules:true,
    script:bundle.outputFiles[0]!.text,compatibilityDate:'2026-10-29',
    cf:false,bindings:{APP_ENV:'local',MODEL_C_LOCAL_API:'synthetic-only',MODEL_C_TEST_OWNER:owner},
    d1Databases:{CATALOG:'auth-catalog',PERSONAL:'auth-personal'}}));
  catalog=await runtime.getD1Database('CATALOG');
  personal=await runtime.getD1Database('PERSONAL');
  await applySchema(catalog,'catalog');await applySchema(personal,'personal');
  await stageCatalog(catalog);await catalog.batch(publicationFixture(catalog,'run-one'));
  await seedPersonal(personal);
  await personal.prepare('INSERT INTO personal_owners VALUES (?)').bind(person).run();
  await personal.prepare('INSERT INTO personal_heads VALUES (?,1,?,?)').bind(person,hash,commit).run();
  const pair=await generateKeyPair('RS256',{extractable:true});
  privateKey=pair.privateKey;
  const jwk=await exportJWK(pair.publicKey);
  verifyKey=createLocalJWKSet({keys:[{...jwk,kid:'valid-key',alg:'RS256',use:'sig'}]});
});
afterAll(async()=>{await runtime?.dispose();});

describe('Private Cloudflare Access authentication boundary (no cloud resources)',()=>{
  it('verifies real RS256 Access token and maps subject to configured owner, not email',async()=>{
    const token=await jwt({email:'untrusted@example.test'});
    const principal=await authenticatePrivateRequest(req('/',token),env(),verifyKey);
    expect(principal).toMatchObject({subject:sub,ownerId:person,issuer,audience,
      principalType:'interactive',capabilities:['catalog:read','personal:read']});
    expect(JSON.stringify(principal)).not.toContain('untrusted@example.test');
  });
  it('rejects missing, malformed, forged JWT and unknown key',async()=>{
    for(const token of [undefined,'abc.def.ghi',await jwt({},(await generateKeyPair('RS256')).privateKey)]){
      const failure=await error(()=>authenticatePrivateRequest(req('/',token),env(),verifyKey));
      expect([401,403]).toContain((failure as {status:number}).status);
    }
    const unknown=await new SignJWT({sub}).setProtectedHeader({alg:'RS256',kid:'unknown-key'})
      .setIssuer(issuer).setAudience(audience).setIssuedAt().setExpirationTime('10m').sign(privateKey);
    await expect(authenticatePrivateRequest(req('/',unknown),env(),verifyKey))
      .rejects.toMatchObject({code:'private_auth_invalid',status:401});
  });
  it('rejects audience, issuer, expiry, future nbf and non-RS256 algorithms',async()=>{
    const valid=await jwt();
    const badAudience=await new SignJWT({sub}).setProtectedHeader({alg:'RS256',kid:'valid-key'})
      .setIssuer(issuer).setAudience('x'.repeat(64)).setIssuedAt().setExpirationTime('10m').sign(privateKey);
    const badIssuer=await new SignJWT({sub}).setProtectedHeader({alg:'RS256',kid:'valid-key'})
      .setIssuer('https://other.cloudflareaccess.com').setAudience(audience).setIssuedAt().setExpirationTime('10m').sign(privateKey);
    const expired=await new SignJWT({sub}).setProtectedHeader({alg:'RS256',kid:'valid-key'})
      .setIssuer(issuer).setAudience(audience).setIssuedAt(-900).setExpirationTime(-600).sign(privateKey);
    const future=await new SignJWT({sub}).setProtectedHeader({alg:'RS256',kid:'valid-key'})
      .setIssuer(issuer).setAudience(audience).setIssuedAt().setNotBefore('10m').setExpirationTime('20m').sign(privateKey);
    const unsupportedAlgorithm=await new SignJWT({sub,email:'synthetic-user@example.test',type:'app'})
      .setProtectedHeader({alg:'HS256',kid:'valid-key'}).setIssuer(issuer).setAudience(audience)
      .setIssuedAt().setExpirationTime('10m').sign(new Uint8Array(32).fill(2));
    for(const token of [badAudience,badIssuer,expired,future,unsupportedAlgorithm])
      await expect(authenticatePrivateRequest(req('/',token),env(),verifyKey))
        .rejects.toMatchObject({code:'private_auth_invalid'});
    expect(valid).toContain('.');
  });
  it('accepts rotated matching JWKS keys and fails closed when JWKS retrieval is unavailable',async()=>{
    const rotated=await generateKeyPair('RS256',{extractable:true});
    const newJwk=await exportJWK(rotated.publicKey);
    const initialJwk=await exportJWK((await generateKeyPair('RS256',{extractable:true})).publicKey);
    const keySet=createLocalJWKSet({keys:[
      {...initialJwk,kid:'old-key',alg:'RS256',use:'sig'},
      {...newJwk,kid:'rotated-key',alg:'RS256',use:'sig'},
    ]});
    const token=await new SignJWT({sub,email:'synthetic-user@example.test',type:'app'})
      .setProtectedHeader({alg:'RS256',kid:'rotated-key'})
      .setIssuer(issuer).setAudience(audience).setIssuedAt().setExpirationTime('10m')
      .sign(rotated.privateKey);
    const principal=await authenticatePrivateRequest(req('/',token),env(),keySet);
    expect(principal.ownerId).toBe(person);
    await expect(authenticatePrivateRequest(req('/',token),env(),async()=>{
      throw Error('JWKS_UNAVAILABLE');
    })).rejects.toMatchObject({code:'private_auth_invalid',status:401});
  });
  it('rejects unknown identity, service token claims and missing owner mapping',async()=>{
    for(const token of [await jwt({sub:'different-user-987654321'}),
      await jwt({common_name:'service-token'}),await jwt({type:'service'})])
      await expect(authenticatePrivateRequest(req('/',token),env(),verifyKey))
        .rejects.toMatchObject({code:'private_access_denied'});
    const missingOwner=env();
    delete missingOwner.PRIVATE_OWNER_ID;
    await expect(authenticatePrivateRequest(req('/',await jwt()),missingOwner,verifyKey))
      .rejects.toMatchObject({code:'private_config_missing'});
    await expect(authenticatePrivateRequest(req('/',await jwt()),
      {...env(),PRIVATE_OWNER_ID:'synthetic-owner'},verifyKey))
      .rejects.toMatchObject({code:'private_config_invalid'});
  });
  it('denies wrong host, URL scheme, alternate workers.dev and incomplete team config',async()=>{
    const token=await jwt();
    await expect(authenticatePrivateRequest(new Request('https://preview.example.com/',
      {headers:{'Cf-Access-Jwt-Assertion':token}}),env(),verifyKey))
      .rejects.toMatchObject({code:'private_hostname_forbidden'});
    await expect(authenticatePrivateRequest(new Request('http://jobs.example.com/',
      {headers:{'Cf-Access-Jwt-Assertion':token}}),env(),verifyKey))
      .rejects.toMatchObject({code:'private_hostname_forbidden'});
    expect(()=>privateAccessConfig({...env(),PRIVATE_HOSTNAME:'preview.workers.dev'}))
      .toThrowError('private_config_invalid');
    expect(()=>privateAccessConfig({...env(),PRIVATE_ACCESS_ISSUER:'https://attacker.invalid'}))
      .toThrowError('private_config_invalid');
    expect(()=>privateAccessConfig({...env(),APP_ENV:'local'}))
      .toThrowError('private_runtime_disabled');
  });
  it('checks strict HTTP methods, owner overrides and cross-origin requests',()=>{
    for(const request of [
      req('/api/model-c/personal/commands/saved',undefined,{method:'POST'}),
      req('/',undefined,{headers:{Origin:'https://evil.example'}}),
      req('/api/model-c/personal/jobs',undefined,{headers:{'x-owner-id':owner}}),
      req('/api/model-c/personal/jobs',undefined,{method:'OPTIONS'}),
    ])expect(()=>privateRequestPolicy(request)).toThrow();
    expect(()=>privateRequestPolicy(req('/'))).not.toThrow();
  });
  it('maps a verified principal to only the configured owner, never imported synthetic records',async()=>{
    const principal=await authenticatePrivateRequest(req('/',await jwt()),env(),verifyKey);
    const list=await handlePrivateRuntime(req('/api/model-c/personal/jobs'),env(),principal);
    expect(list.status).toBe(200);
    const data=await list.json() as {total:number;items:unknown[]};
    expect(data.total).toBe(0);expect(data.items).toHaveLength(0);
    const other=await handlePrivateRuntime(req('/api/model-c/personal/jobs/'+jobId),env(),principal);
    expect(other.status).toBe(404);
    const caps=await handlePrivateRuntime(req('/api/model-c/personal/capabilities'),env(),principal);
    expect(await caps.json()).toEqual({writeEnabled:false,productionAccess:false});
    const catalogList=await handlePrivateRuntime(req('/api/model-c/catalog/jobs'),env(),principal);
    expect(catalogList.status).toBe(200);
    const composite=await handlePrivateRuntime(req('/api/model-c/opportunities/jobs'),env(),principal);
    expect(composite.status).toBe(200);
    const parsed=await composite.json() as {items:Array<{personal:unknown}>};
    expect(parsed.items[0]?.personal).toBeNull();
    expect(await personal.prepare('SELECT count(*) AS n FROM personal_app_events').first('n')).toBe(0);
  });
  it('reports official D1 Free daily quota failures without exposing the provider error or retrying',async()=>{
    const principal=await authenticatePrivateRequest(req('/',await jwt()),env(),verifyKey);
    const quota='D1_ERROR: Your account has exceeded D1\\'s free tier daily row read limit. Upgrade to a paid plan or wait until tomorrow (midnight UTC) to continue.';
    expect(privateD1ErrorCode(new Error(quota))).toBe('cloudflare_quota_exceeded');
    expect(privateD1ErrorCode(new Error(quota.replace('read','write')))).toBe('cloudflare_quota_exceeded');
    expect(privateD1ErrorCode(new Error('D1 storage unavailable'))).toBe('database_unavailable');
    const quotaDb={prepare:(_sql:string)=>{throw new Error(quota);}} as unknown as D1Database;
    const privateEnv={...env(),CATALOG:quotaDb};
    const response=await handlePrivateRuntime(req('/api/model-c/catalog/snapshot'),privateEnv,principal);
    expect(response.status).toBe(503);
    expect(await response.json()).toEqual({error:'cloudflare_quota_exceeded'});
    expect(response.headers.get('cache-control')).toBe('no-store');
  });
  it('keeps CATALOG readable for an Access user whose PERSONAL history has not been verified',async()=>{
    const unprovisioned={...env(),PRIVATE_OWNER_ID:'personal-unprovisioned'};
    const principal=await authenticatePrivateRequest(req('/',await jwt()),unprovisioned,verifyKey);
    const catalogResponse=await handlePrivateRuntime(req('/api/model-c/catalog/snapshot'),unprovisioned,principal);
    expect(catalogResponse.status).toBe(200);
    const catalogBody=await catalogResponse.json() as {snapshot:{syncRevision:number}|null};
    expect(catalogBody.snapshot).not.toBeNull();
    const personalResponse=await handlePrivateRuntime(req('/api/model-c/personal/jobs'),unprovisioned,principal);
    expect(personalResponse.status).toBe(404);
    expect(await personalResponse.json()).toEqual({error:'PERSONAL_CONTEXT_UNAVAILABLE'});
    const composite=await handlePrivateRuntime(req('/api/model-c/opportunities/jobs'),unprovisioned,principal);
    expect(composite.status).toBe(200);
    const page=await composite.json() as {items:Array<{personal:unknown}>,personalRevision:number|null};
    expect(page.personalRevision).toBeNull();
    expect(page.items).toHaveLength(1);
    expect(page.items[0]?.personal).toBeNull();
    const detail=await handlePrivateRuntime(req('/api/model-c/opportunities/jobs/'+jobId+
      '?revision='+catalogBody.snapshot!.syncRevision),unprovisioned,principal);
    expect(detail.status).toBe(200);
    const detailBody=await detail.json() as {personal:unknown,personalDetail:unknown,personalRevision:unknown};
    expect(detailBody.personal).toBeNull();
    expect(detailBody.personalDetail).toBeNull();
    expect(detailBody.personalRevision).toBeNull();
    // An absent owner never seeds an implicit PERSONAL head or APP events.
    expect(await personal.prepare("SELECT count(*) AS n FROM personal_heads WHERE owner_id=?")
      .bind('personal-unprovisioned').first('n')).toBe(0);
  });
  it('protects every asset and SPA route in private router; no legacy, ingestion or command API',async()=>{
    const principal=await authenticatePrivateRequest(req('/',await jwt()),env(),verifyKey);
    let fetched=0;
    const assetEnv={...env(),ASSETS:{fetch:async(request:Request)=>{
      fetched++;return new Response('private asset: '+new URL(request.url).pathname);
    }} as unknown as Fetcher};
    for(const path of ['/','/assets/index.js','/assets/site.css','/candidature']){
      const response=await handlePrivateRuntime(req(path),assetEnv,principal);
      expect(response.status).toBe(200);
      expect(response.headers.get('cache-control')).toContain('no-store');
    }
    expect(fetched).toBe(4);
    for(const path of ['/api/health','/api/jobs','/api/commands','/api/model-c/personal/commands/saved'])
      expect((await handlePrivateRuntime(req(path),env(),principal)).status).toBe(404);
    expect((await handlePrivateRuntime(req('/api/model-c/personal/commands/decision',undefined,{method:'POST'}),
      env(),principal)).status).toBe(405);
  });
  it('refuses unauthenticated requests at root, assets, SPA, legacy and private API before any D1 access',async()=>{
    // Actual Worker entry, no test resolver injected. The absence of JWT must fail
    // before consulting a database or attempting the asset binding.
    const noAssets={...envConfig,CATALOG:catalog,PERSONAL:personal};
    for(const path of ['/','/assets/app.js','/candidature','/api/health',
      '/api/model-c/catalog/jobs','/api/model-c/personal/jobs']){
      const response=await worker.fetch(req(path),noAssets);
      expect(response.status).toBe(401);
      expect(response.headers.get('Cache-Control')).toBe('no-store');
    }
    // Every method is authenticated before policy rejection.
    expect((await worker.fetch(req('/api/model-c/personal/commands/decision',undefined,{method:'POST'}),
      noAssets)).status).toBe(401);
    expect((await worker.fetch(req('/api/model-c/personal/jobs',undefined,{method:'OPTIONS'}),
      noAssets)).status).toBe(401);
  });
  it('commits only a non-deployable protected private template, preserving local setup',async()=>{
    const template=await readFile('wrangler.private.template.jsonc','utf8');
    const local=await readFile('wrangler.jsonc','utf8');
    expect(template).toContain('"workers_dev": false');
    expect(template).toContain('"preview_urls": false');
    expect(template).toContain('"run_worker_first": true');
    expect(template).toContain('"APP_ENV": "private"');
    expect(template).not.toMatch(/"d1_databases"\\s*:/);
    expect(template).not.toContain('PRIVATE_ALLOWED_SUB":');
    expect(local).toContain('"APP_ENV": "local"');
    expect(local).toContain('"workers_dev": false');
  });
  it('requires physical distinct database bindings and never falls back to synthetic owner',async()=>{
    const noPersonal=env();
    delete noPersonal.PERSONAL;
    Object.assign(noPersonal,{MODEL_C_TEST_OWNER:'synthetic-owner'});
    await expect(authenticatePrivateRequest(req('/',await jwt()),noPersonal,verifyKey))
      .rejects.toMatchObject({code:'private_databases_unavailable',status:503});
  });
});
