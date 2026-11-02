// Regression for the first password-only cloud pilot: D1 schemas exist but
// neither a CATALOG snapshot nor the PERSONAL owner context has been imported.
// No cloud credentials, no remote D1 access, and no synthetic personal history.
import {beforeAll,afterAll,describe,it,expect} from 'vitest';
import {randomBytes} from 'node:crypto';
import {build} from 'esbuild';
import {SignJWT} from 'jose';
import {Miniflare,convertV4MiniflareOptions} from 'miniflare';
import worker from '../worker/index';
import {applySchema} from '../tools/model-c-schema';
import type {PasswordAuthEnv} from '../worker/password-auth';

const host='job-watch.empty-pilot.workers.dev';
const origin='https://'+host;
const owner='pilot-absent-owner';
let runtime:Miniflare;
let catalog:D1Database,personal:D1Database;
const sessionKey=randomBytes(32);
let env:PasswordAuthEnv;

const req=(path:string,token?:string)=>new Request(origin+path,{
  ...(token?{headers:{Cookie:'__Host-jobwatch_session='+token}}:{}),
});
async function token(){
  return new SignJWT({sub:'single-owner',type:'password'})
    .setProtectedHeader({alg:'HS256'}).setIssuer('job-watch-password')
    .setAudience(host).setIssuedAt().setExpirationTime('4h')
    .setJti('local-empty-pilot').sign(sessionKey);
}
beforeAll(async()=>{
  const bundled=await build({entryPoints:['worker/index.ts'],bundle:true,
    write:false,format:'esm',platform:'browser',target:'es2023'});
  runtime=new Miniflare(convertV4MiniflareOptions({modules:true,
    script:bundled.outputFiles[0]!.text,compatibilityDate:'2026-10-29',
    cf:false,d1Databases:{CATALOG:'empty-pilot-catalog',PERSONAL:'empty-pilot-personal'}}));
  catalog=await runtime.getD1Database('CATALOG');
  personal=await runtime.getD1Database('PERSONAL');
  await applySchema(catalog,'catalog');
  await applySchema(personal,'personal');
  env={APP_ENV:'password',PASSWORD_HOSTNAME:host,PRIVATE_OWNER_ID:owner,
    CATALOG:catalog,PERSONAL:personal,
    PASSWORD_HMAC_KEY:randomBytes(32).toString('base64url'),
    PASSWORD_HMAC_VERIFIER:randomBytes(32).toString('base64url'),
    PASSWORD_SESSION_KEY:sessionKey.toString('base64url'),
    PASSWORD_RATE_LIMITER:{limit:async()=>({success:true})}};
});
afterAll(async()=>{await runtime?.dispose();});

describe('Password pilot with independently migrated but uninitialized D1 databases',()=>{
  it('denies all personal data queries before authentication',async()=>{
    for(const path of ['/api/model-c/personal/summary','/api/model-c/personal/jobs',
      '/api/model-c/catalog/snapshot','/api/model-c/opportunities/jobs']){
      const result=await worker.fetch(req(path),env);
      expect(result.status).toBe(401);
      expect(result.headers.get('cache-control')).toContain('no-store');
    }
  });
  it('returns a real empty CATALOG and preserves the explicit missing-owner 404',async()=>{
    const session=await token();
    const catalogResponse=await worker.fetch(req('/api/model-c/catalog/snapshot',session),env);
    expect(catalogResponse.status).toBe(200);
    expect(await catalogResponse.json()).toEqual({snapshot:null,productionAccess:false});

    const list=await worker.fetch(req('/api/model-c/catalog/jobs',session),env);
    expect(list.status).toBe(200);
    expect(await list.json()).toMatchObject({snapshot:null,items:[],total:0});

    const combined=await worker.fetch(req('/api/model-c/opportunities/jobs',session),env);
    expect(combined.status).toBe(200);
    expect(await combined.json()).toMatchObject({
      snapshot:null,items:[],personalRevision:null,total:0,
    });

    for(const path of ['/api/model-c/personal/summary','/api/model-c/personal/jobs']){
      const response=await worker.fetch(req(path,session),env);
      expect(response.status).toBe(404);
      expect(await response.json()).toEqual({error:'PERSONAL_CONTEXT_UNAVAILABLE'});
    }
    const invalid=await worker.fetch(req('/api/model-c/personal/summary?owner_id=other',session),env);
    expect(invalid.status).toBe(400);
    const status=await worker.fetch(req('/api/model-c/private/status',session),env);
    expect(status.status).toBe(200);
    expect(await status.json()).toMatchObject({accessVerified:true,readOnly:true});

    // No owner is provisioned, no synthetic vacancy or revision manufactured,
    // and no PERSONAL writes result from empty-state consultation.
    expect(await personal.prepare('SELECT count(*) AS n FROM personal_owners').first<number>('n')).toBe(0);
    expect(await personal.prepare('SELECT count(*) AS n FROM personal_heads').first<number>('n')).toBe(0);
    expect(await personal.prepare('SELECT count(*) AS n FROM personal_app_events').first<number>('n')).toBe(0);
    expect(await catalog.prepare('SELECT count(*) AS n FROM catalog_head').first<number>('n')).toBe(0);
  });
});
