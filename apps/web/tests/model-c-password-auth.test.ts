import {beforeAll,describe,expect,it} from 'vitest';
import {pbkdf2Sync,randomBytes} from 'node:crypto';
import worker from '../worker/index';
import {authenticatePasswordRequest,checkPassword,handlePasswordWorker,passwordConfig} from '../worker/password-auth';
import type {PasswordAuthEnv} from '../worker/password-auth';

const host='job-watch.test.workers.dev';
const origin='https://'+host;
const password='test-'+'z'.repeat(35);
let env:PasswordAuthEnv;
let calls=0;
const request=(path:string,init:RequestInit={})=>new Request(origin+path,init);
const authenticate=(input:string,hostOrigin=origin)=>new Request(hostOrigin+'/login',{
  method:'POST',
  headers:{Origin:hostOrigin,'Content-Type':'application/x-www-form-urlencoded'},
  body:new URLSearchParams({password:input}).toString(),
});
const cookie=(response:Response)=>response.headers.get('set-cookie')?.split(';')[0]||'';
const withCookie=(path:string,c:string,options:RequestInit={})=>request(path,{
  ...options,headers:{Cookie:c,...options.headers}
});
beforeAll(()=>{
  const salt=randomBytes(16);
  calls=0;
  const c={} as D1Database,p={} as D1Database;
  env={APP_ENV:'password',PASSWORD_HOSTNAME:host,PRIVATE_OWNER_ID:'pilot-owner-1234',
    CATALOG:c,PERSONAL:p,PASSWORD_PBKDF2_SALT:salt.toString('base64url'),
    PASSWORD_PBKDF2_VERIFIER:pbkdf2Sync(password,salt,100_000,32,'sha256').toString('base64url'),
    PASSWORD_SESSION_KEY:randomBytes(32).toString('base64url'),
    PASSWORD_RATE_LIMITER:{limit:async()=>({success:++calls<=8})},
    ASSETS:{fetch:async()=>new Response('only for an authenticated visitor',
      {headers:{'content-type':'text/html'}})} as unknown as Fetcher};
});
describe('Isolated password authentication for Job Watch private pilot',()=>{
  it('fails closed without configured secrets, a limiter or separate databases',()=>{
    expect(()=>passwordConfig({...env,PASSWORD_RATE_LIMITER:undefined})).toThrow('password_config_missing');
    expect(()=>passwordConfig({...env,PASSWORD_SESSION_KEY:'invalid'})).toThrow('password_config_missing');
    expect(()=>passwordConfig({...env,PERSONAL:env.CATALOG})).toThrow('password_config_missing');
    expect(()=>passwordConfig({...env,APP_ENV:'private'})).toThrow('password_runtime_disabled');
    expect(()=>passwordConfig({...env,PRIVATE_OWNER_ID:'synthetic-owner'})).toThrow('password_config_missing');
  });
  it('denies arbitrary hosts, HTTP, forwarded-host mismatch and discloses no assets before login',async()=>{
    for(const path of ['/','/assets/main.js','/candidature','/opportunita']){
      const r=await worker.fetch(request(path),env);
      expect(r.status).toBe(303);
      expect(r.headers.get('Location')).toBe('/login');
    }
    const api=await worker.fetch(request('/api/model-c/private/status'),env);
    expect(api.status).toBe(401);
    const badHost=await worker.fetch(new Request('https://evil.example/login'),env);
    expect(badHost.status).toBe(403);
    const badScheme=await worker.fetch(new Request('http://'+host+'/login'),env);
    expect(badScheme.status).toBe(403);
    const forwarded=await worker.fetch(request('/login',{headers:{'x-forwarded-host':'evil.example'}}),env);
    expect(forwarded.status).toBe(403);
  });
  it('serves only the minimal public login page, not personal data',async()=>{
    const r=await worker.fetch(request('/login'),env);
    expect(r.status).toBe(200);
    expect(await r.text()).toContain('Job Watch');
    expect(r.headers.get('content-security-policy')).toContain("form-action 'self'");
    expect(r.headers.get('cache-control')).toContain('no-store');
    const head=await worker.fetch(request('/login',{method:'HEAD'}),env);
    expect(head.status).toBe(200);
    expect(await head.text()).toBe('');
  });
  it('checks a high-entropy password and issues a short-lived host-only HttpOnly session',async()=>{
    const config=passwordConfig(env);
    expect(await checkPassword(password,config)).toBe(true);
    expect(await checkPassword('bad-credentials',config)).toBe(false);
    const login=await worker.fetch(authenticate(password),env);
    expect(login.status).toBe(303);
    expect(login.headers.get('Location')).toBe('/');
    const setCookie=login.headers.get('set-cookie')||'';
    expect(setCookie).toContain('__Host-jobwatch_session=');
    expect(setCookie).toContain('Secure; HttpOnly; SameSite=Strict');
    expect(setCookie).not.toContain('Domain=');
    const active=cookie(login);
    const principal=await authenticatePasswordRequest(withCookie('/',active),config);
    expect(principal).toMatchObject({ownerId:'pilot-owner-1234',principalType:'interactive'});
    const status=await worker.fetch(withCookie('/api/model-c/private/status',active),env);
    expect(status.status).toBe(200);
    expect(await status.json()).toEqual({accessVerified:true,readOnly:true,environment:'private'});
    const asset=await worker.fetch(withCookie('/',active),env);
    expect(asset.status).toBe(200);
    expect(await asset.text()).toContain('only for an authenticated visitor');
  });
  it('rejects forged sessions, unknown cookies, cross-site password POSTs and owner override',async()=>{
    const login=await worker.fetch(authenticate(password),env);
    const active=cookie(login);
    const malformed=await worker.fetch(withCookie('/api/model-c/private/status',
      '__Host-jobwatch_session=abc.def.ghi'),env);
    expect(malformed.status).toBe(401);
    const injected=await worker.fetch(withCookie('/api/model-c/private/status',active,{
      headers:{'x-owner-id':'another-user'}}),env);
    expect(injected.status).toBe(403);
    const csrf=await worker.fetch(request('/login',{method:'POST',
      headers:{Origin:'https://evil.example','content-type':'application/x-www-form-urlencoded'},
      body:new URLSearchParams({password}).toString()}),env);
    expect(csrf.status).toBe(403);
  });
  it('keeps APP mutations and service ingestion disabled even with a valid session',async()=>{
    const login=await worker.fetch(authenticate(password),env),active=cookie(login);
    const cmd=await worker.fetch(withCookie('/api/model-c/personal/commands/saved',active,{
      method:'POST',headers:{Origin:origin,'Content-Type':'application/json'},body:'{}'}),env);
    expect(cmd.status).toBe(405);
    const service=await worker.fetch(withCookie('/api/model-c/sync/v2/runs',active),env);
    expect(service.status).toBe(404);
    const legacy=await worker.fetch(withCookie('/api/jobs',active),env);
    expect(legacy.status).toBe(404);
  });
  it('requires same-origin logout POST and deletes only the host session cookie',async()=>{
    const login=await worker.fetch(authenticate(password),env),active=cookie(login);
    const denied=await worker.fetch(withCookie('/logout',active,{method:'POST'}),env);
    expect(denied.status).toBe(403);
    const allowed=await worker.fetch(withCookie('/logout',active,{
      method:'POST',headers:{Origin:origin}}),env);
    expect(allowed.status).toBe(303);
    expect(allowed.headers.get('set-cookie')).toContain('Max-Age=0');
    expect(allowed.headers.get('Location')).toBe('/login');
  });
  it('fails closed if rate limiter is unavailable or has exhausted its small quota',async()=>{
    const errorEnv={...env,PASSWORD_RATE_LIMITER:{limit:async()=>{throw Error('unavailable');}}};
    const missing=await handlePasswordWorker(authenticate(password),errorEnv);
    expect(missing.status).toBe(503);
    const throttled={...env,PASSWORD_RATE_LIMITER:{limit:async()=>({success:false})}};
    const denied=await handlePasswordWorker(authenticate(password),throttled);
    expect(denied.status).toBe(429);
    expect(denied.headers.get('retry-after')).toBe('60');
  });
});
