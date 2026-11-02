import {beforeAll,describe,expect,it,vi} from 'vitest';
import {createHmac,randomBytes} from 'node:crypto';
import worker from '../worker/index';
import {SignJWT} from 'jose';
import {authenticatePasswordRequest,checkPassword,handlePasswordWorker,passwordConfig} from '../worker/password-auth';
import type {PasswordAuthEnv} from '../worker/password-auth';

const host='job-watch.test.workers.dev';
const origin='https://'+host;
const password='jw1_'+Buffer.alloc(32,11).toString('base64url');
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
  const salt=randomBytes(32);
  calls=0;
  const c={} as D1Database,p={} as D1Database;
  env={APP_ENV:'password',PASSWORD_HOSTNAME:host,PRIVATE_OWNER_ID:'pilot-owner-1234',
    CATALOG:c,PERSONAL:p,PASSWORD_HMAC_KEY:salt.toString('base64url'),
    PASSWORD_HMAC_VERIFIER:createHmac('sha256',salt).update('job-watch-login:v1\0'+password).digest('base64url'),
    PASSWORD_SESSION_KEY:randomBytes(32).toString('base64url'),
    PASSWORD_RATE_LIMITER:{limit:async()=>({success:++calls<=8})},
    ASSETS:{fetch:async()=>new Response('only for an authenticated visitor',
      {headers:{'content-type':'text/html'}})} as unknown as Fetcher};
});
describe('Isolated password authentication for Job Watch private pilot',()=>{
  it('fails closed without configured secrets, a limiter or separate databases',()=>{
    const withoutLimiter={...env};
    delete withoutLimiter.PASSWORD_RATE_LIMITER;
    const withoutPersonal={...env};
    delete withoutPersonal.PERSONAL;
    const catalog=env.CATALOG;
    if(!catalog)throw Error('missing_test_catalog');
    expect(()=>passwordConfig(withoutLimiter)).toThrow('password_config_missing');
    expect(()=>passwordConfig(withoutPersonal)).toThrow('password_config_missing');
    expect(()=>passwordConfig({...env,PASSWORD_SESSION_KEY:'invalid'})).toThrow('password_config_missing');
    expect(()=>passwordConfig({...env,PERSONAL:catalog})).toThrow('password_config_missing');
    expect(()=>passwordConfig({...env,APP_ENV:'private'})).toThrow('password_runtime_disabled');
    expect(()=>passwordConfig({...env,PRIVATE_OWNER_ID:'synthetic-owner'})).toThrow('password_config_missing');
  });
  it('rejects malformed and wrong canonical credentials and legacy-only or incomplete configurations',async()=>{
    const config=passwordConfig(env);
    const independent={...env,PASSWORD_RATE_LIMITER:{limit:async()=>({success:true})}};
    for(const value of ['', 'human-password-123456789',password+'=',password+' ',
      password.slice(0,-1)+'B','jw1_'+Buffer.alloc(31).toString('base64url'),
      'jw2_'+password.slice(4),'jw1_'+Buffer.alloc(32,12).toString('base64url')]){
      expect(await checkPassword(value,config)).toBe(false);
      const response=await worker.fetch(authenticate(value),independent);
      expect(response.headers.get('Location')).toBe('/login?error=1');
      expect(response.headers.get('set-cookie')).toBeNull();
    }
    for(const name of ['PASSWORD_HMAC_KEY','PASSWORD_HMAC_VERIFIER','PASSWORD_SESSION_KEY'] as const){
      const missing={...env};delete missing[name];
      expect(()=>passwordConfig(missing)).toThrow('password_config_missing');
    }
    const legacy={...env,
      PASSWORD_PBKDF2_SALT:randomBytes(16).toString('base64url'),
      PASSWORD_PBKDF2_VERIFIER:randomBytes(32).toString('base64url')};
    delete legacy.PASSWORD_HMAC_KEY;delete legacy.PASSWORD_HMAC_VERIFIER;
    expect((await worker.fetch(authenticate(password),legacy)).status).toBe(503);
    expect(()=>passwordConfig({...env,PASSWORD_HMAC_KEY:env.PASSWORD_SESSION_KEY!})).toThrow('password_config_missing');
    expect(()=>passwordConfig({...env,PASSWORD_HMAC_VERIFIER:env.PASSWORD_HMAC_VERIFIER+'='})).toThrow('password_config_missing');
    const changed={...independent,PASSWORD_HMAC_KEY:randomBytes(32).toString('base64url')};
    expect((await worker.fetch(authenticate(password),changed)).headers.get('set-cookie')).toBeNull();
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
  it('rejects a wrong password without issuing a session cookie',async()=>{
    const bad=await worker.fetch(authenticate('not-the-correct-password-123456789'),env);
    expect(bad.status).toBe(303);
    expect(bad.headers.get('Location')).toBe('/login?error=1');
    expect(bad.headers.get('set-cookie')).toBeNull();
  });
  it('rejects expired signed sessions and wrong-session audience',async()=>{
    const key=Buffer.from(env.PASSWORD_SESSION_KEY!,'base64url');
    for(const audience of [host,'someone-else.workers.dev']){
      const expired=await new SignJWT({sub:'single-owner',type:'password'})
        .setProtectedHeader({alg:'HS256'})
        .setIssuer('job-watch-password').setAudience(audience)
        .setIssuedAt(-1200).setExpirationTime(-600)
        .setJti('expired-token').sign(key);
      const out=await worker.fetch(withCookie('/api/model-c/private/status',
        '__Host-jobwatch_session='+expired),env);
      expect(out.status).toBe(401);
    }
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
    const flags={...env,PRIVATE_APP_WRITE_GATE:'gate-b-approved',
      PRIVATE_QUOTA_ATTESTED:'gate-b-approved',
      PRIVATE_INGESTION_QUOTA_REMAINING:'30000',
      PRIVATE_INGESTION_QUOTA_VALID_UNTIL:new Date(Date.now()+60000).toISOString()};
    const login=await worker.fetch(authenticate(password),flags),active=cookie(login);
    const cmd=await worker.fetch(withCookie('/api/model-c/personal/commands/saved',active,{
      method:'POST',headers:{Origin:origin,'Content-Type':'application/json'},body:'{}'}),flags);
    expect(cmd.status).toBe(405);
    const service=await worker.fetch(withCookie('/api/model-c/sync/v2/runs',active),env);
    expect(service.status).toBe(404);
    const legacy=await worker.fetch(withCookie('/api/jobs',active),env);
    expect(legacy.status).toBe(404);
    const ownerQuery=await worker.fetch(withCookie('/api/model-c/personal/summary?owner_id=another-owner',active),flags);
    expect(ownerQuery.status).toBe(400);
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
  it('authenticates every SPA, asset and API route before any database or asset access',async()=>{
    const catalog=env.CATALOG,personal=env.PERSONAL,assets=env.ASSETS;
    if(!catalog||!personal||!assets)throw Error('missing_test_bindings');
    const dbRead=vi.fn(()=>{throw Error('unexpected_database_read');});
    const assetRead=vi.fn(()=>{throw Error('unexpected_asset_read');});
    const guard=(db:D1Database)=>new Proxy(db,{get(target,key,receiver){
      return key==='prepare'?dbRead:Reflect.get(target,key,receiver);
    }});
    const guarded={...env,CATALOG:guard(catalog),PERSONAL:guard(personal),
      ASSETS:new Proxy(assets,{get(target,key,receiver){
        return key==='fetch'?assetRead:Reflect.get(target,key,receiver);
      }})};
    for(const path of ['/','/opportunita','/candidature','/assets/main.js','/assets/main.css',
      '/api/model-c/catalog/snapshot','/api/model-c/personal/summary',
      '/api/model-c/opportunities/jobs','/api/jobs','/api/model-c/sync/v2/runs',
      '/api/model-c/personal/commands/saved']){
      for(const method of ['GET','HEAD','POST','OPTIONS']){
        const response=await worker.fetch(request(path,{method,headers:{
          'Cf-Access-Jwt-Assertion':'untrusted','X-HTTP-Method-Override':'GET',
          'Cookie':'owner_id=another-owner; session=untrusted',
        }}),guarded);
        expect([303,401]).toContain(response.status);
      }
    }
    expect(dbRead).not.toHaveBeenCalled();
    expect(assetRead).not.toHaveBeenCalled();
  });
  it('rejects duplicate host cookies and signed sessions with invalid claims or signatures',async()=>{
    const config=passwordConfig(env),now=Math.floor(Date.now()/1000);
    const key=Buffer.from(env.PASSWORD_SESSION_KEY!,'base64url');
    const token=async(overrides:Record<string,unknown>={},signingKey=key,alg='HS256')=>
      new SignJWT({sub:'single-owner',type:'password',iss:'job-watch-password',
        aud:host,iat:now,exp:now+14400,jti:'synthetic-session',...overrides})
        .setProtectedHeader({alg}).sign(signingKey);
    const valid=await token();
    for(const value of [
      '__Host-jobwatch_session='+valid+'; __Host-jobwatch_session='+valid,
      '__Host-jobwatch_session=',
      '__Host-jobwatch_session='+await token({aud:'wrong.example.test'}),
      '__Host-jobwatch_session='+await token({iss:'wrong-issuer'}),
      '__Host-jobwatch_session='+await token({sub:'another-owner'}),
      '__Host-jobwatch_session='+await token({type:'service'}),
      '__Host-jobwatch_session='+await token({jti:''}),
      '__Host-jobwatch_session='+await token({exp:now-1}),
      '__Host-jobwatch_session='+await token({},randomBytes(32)),
      '__Host-jobwatch_session='+await token({},randomBytes(48),'HS384'),
    ])await expect(authenticatePasswordRequest(withCookie('/',value),config))
      .rejects.toMatchObject({code:'password_auth_required',status:401});
  });
  it('bounds login bodies and rejects duplicate fields, invalid types and cross-site logout',async()=>{
    const independent={...env,PASSWORD_RATE_LIMITER:{limit:async()=>({success:true})}};
    for(const [body,extra,status] of [
      ['password='+password,{'content-length':'2048'},413],
      ['password='+'z'.repeat(1025),{},400],
      ['password='+password,{'content-type':'application/json'},403],
      ['password='+password,{'Origin':'https://evil.example'},403],
      ['password='+password+'&password='+password,{},303],
    ] as const){
      const response=await worker.fetch(request('/login',{method:'POST',body,headers:{
        Origin:origin,'content-type':'application/x-www-form-urlencoded',...extra,
      }}),independent);
      expect(response.status).toBe(status);
      expect(response.headers.get('set-cookie')).toBeNull();
    }
    const login=await worker.fetch(authenticate(password),independent),active=cookie(login);
    const csrf=await worker.fetch(withCookie('/logout',active,{
      method:'POST',headers:{Origin:'https://evil.example'}}),independent);
    expect(csrf.status).toBe(403);
    for(const method of ['PUT','DELETE','PATCH','OPTIONS']){
      expect((await worker.fetch(request('/login',{method}),independent)).status).toBe(405);
      expect((await worker.fetch(withCookie('/logout',active,{method}),independent)).status).toBe(405);
    }
  });
  it('contains an aborted login body inside the sanitized fail-closed response',async()=>{
    const independent={...env,PASSWORD_RATE_LIMITER:{limit:async()=>({success:true})}};
    const init={method:'POST',duplex:'half' as const,
      headers:{Origin:origin,'Content-Type':'application/x-www-form-urlencoded'},
      body:new ReadableStream<Uint8Array>({start(controller){
        controller.error(Error('sensitive_stream_detail'));
      }})};
    const response=await handlePasswordWorker(request('/login',init),independent);
    expect(response.status).toBe(503);
    expect(await response.text()).toBe('password_runtime_unavailable');
  });
  it('documents browser-only logout and proves key rotation invalidates copied sessions',async()=>{
    const independent={...env,PASSWORD_RATE_LIMITER:{limit:async()=>({success:true})}};
    const login=await worker.fetch(authenticate(password),independent),active=cookie(login);
    const logout=await worker.fetch(withCookie('/logout',active,{
      method:'POST',headers:{Origin:origin}}),independent);
    expect(logout.headers.get('set-cookie')).toContain('Max-Age=0');
    // Deliberate pilot limitation: logout cannot revoke a stolen JWT copy.
    expect((await worker.fetch(withCookie('/api/model-c/private/status',active),independent)).status).toBe(200);
    const rotated={...independent,PASSWORD_SESSION_KEY:randomBytes(32).toString('base64url')};
    expect((await worker.fetch(withCookie('/api/model-c/private/status',active),rotated)).status).toBe(401);
    const fresh=await worker.fetch(authenticate(password),rotated);
    expect((await worker.fetch(withCookie('/api/model-c/private/status',cookie(fresh)),rotated)).status).toBe(200);
  });
});
