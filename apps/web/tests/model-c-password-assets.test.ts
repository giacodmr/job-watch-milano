import {afterAll,beforeAll,describe,expect,it} from 'vitest';
import {createHmac} from 'node:crypto';
import {mkdtemp,mkdir,writeFile,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {build} from 'esbuild';
import {Miniflare,convertV4MiniflareOptions} from 'miniflare';

const origin='https://password-assets.example.test';
const password='jw1_'+Buffer.alloc(32,11).toString('base64url');
let runtime:Miniflare,directory:string;
beforeAll(async()=>{
  directory=await mkdtemp(join(tmpdir(),'job-watch-password-assets-'));
  await mkdir(join(directory,'assets'));
  await writeFile(join(directory,'index.html'),'<h1>Protected synthetic SPA</h1>');
  await writeFile(join(directory,'assets/app.js'),'/* protected synthetic JS */');
  await writeFile(join(directory,'assets/app.css'),'/* protected synthetic CSS */');
  const bundle=await build({entryPoints:['worker/index.ts'],bundle:true,write:false,
    format:'esm',platform:'browser',target:'es2023'});
  const salt=Buffer.alloc(32,3);
  runtime=new Miniflare(convertV4MiniflareOptions({modules:true,script:bundle.outputFiles[0]!.text,
    compatibilityDate:'2026-10-29',cf:false,
    bindings:{APP_ENV:'password',PASSWORD_HOSTNAME:'password-assets.example.test',
      PRIVATE_OWNER_ID:'fixture-owner',PASSWORD_HMAC_KEY:salt.toString('base64url'),
      PASSWORD_HMAC_VERIFIER:createHmac('sha256',salt).update('job-watch-login:v1\0'+password).digest('base64url'),
      PASSWORD_SESSION_KEY:Buffer.alloc(32,5).toString('base64url')},
    d1Databases:{CATALOG:'password-assets-catalog',PERSONAL:'password-assets-personal'},
    ratelimits:{PASSWORD_RATE_LIMITER:{namespace_id:'1001',simple:{limit:5,period:60}}},
    assets:{directory,binding:'ASSETS',run_worker_first:true,
      routerConfig:{has_user_worker:true},
      assetConfig:{not_found_handling:'single-page-application'}},
  }));
});
afterAll(async()=>{await runtime?.dispose();if(directory)await rm(directory,{recursive:true,force:true});});

describe('password gate with the real local workerd Static Assets router',()=>{
  it('protects existing JS/CSS and SPA navigation before the asset router can serve them',async()=>{
    for(const path of ['/','/opportunita','/candidature','/assets/app.js','/assets/app.css']){
      const response=await runtime.dispatchFetch(origin+path,{
        redirect:'manual',headers:{'Sec-Fetch-Mode':'navigate'},
      });
      expect(response.status,await response.clone().text()).toBe(303);
      expect(response.headers.get('location')).toBe('/login');
      expect(await response.text()).not.toContain('Protected synthetic');
    }
    expect((await runtime.dispatchFetch(origin+'/login')).status).toBe(200);
  });
  it('serves actual assets only after password login and keeps API/session boundaries',async()=>{
    const login=await runtime.dispatchFetch(origin+'/login',{method:'POST',redirect:'manual',
      headers:{Origin:origin,'Content-Type':'application/x-www-form-urlencoded'},
      body:new URLSearchParams({password}).toString()});
    expect(login.status,await login.clone().text()).toBe(303);
    expect(login.headers.get('location')).toBe('/opportunita');
    const cookie=login.headers.get('set-cookie')?.split(';')[0];
    if(!cookie)throw Error('missing_synthetic_session');
    for(const method of ['GET','HEAD']){
      const landing=await runtime.dispatchFetch(origin+'/',{
        method,redirect:'manual',headers:{Cookie:cookie}});
      expect(landing.status).toBe(303);
      expect(landing.headers.get('location')).toBe('/opportunita');
      expect(await landing.text()).toBe('');
    }
    for(const path of ['/opportunita','/candidature']){
      const page=await runtime.dispatchFetch(origin+path,{headers:{Cookie:cookie}});
      expect(page.status).toBe(200);
      expect(await page.text()).toContain('Protected synthetic SPA');
    }
    for(const path of ['/assets/app.js','/assets/app.css']){
      const asset=await runtime.dispatchFetch(origin+path,{headers:{Cookie:cookie}});
      expect(asset.status).toBe(200);
      expect(await asset.text()).toContain('protected synthetic');
      expect(asset.headers.get('cache-control')).toBe('private, no-store');
    }
    const status=await runtime.dispatchFetch(origin+'/api/model-c/private/status',{headers:{Cookie:cookie}});
    expect(await status.json()).toMatchObject({accessVerified:true,readOnly:true});
    const unauthenticated=await runtime.dispatchFetch(origin+'/api/model-c/personal/summary');
    expect(unauthenticated.status).toBe(401);
  });
});
