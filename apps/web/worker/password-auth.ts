// Separate single-owner password runtime. Never weakens the Access JWT runtime.
// Not enabled by any committed deploy configuration.
import {SignJWT,jwtVerify} from 'jose';
import {PrivateAuthError,privateRequestPolicy} from './private-access';
import type {AuthenticatedPrincipal,PrivateAccessEnv} from './private-access';
import {handlePrivateRuntime} from './private-runtime';

export interface PasswordAuthEnv extends PrivateAccessEnv {
  PASSWORD_HOSTNAME?:string;
  PASSWORD_PBKDF2_SALT?:string;
  PASSWORD_PBKDF2_VERIFIER?:string;
  PASSWORD_SESSION_KEY?:string;
  PASSWORD_RATE_LIMITER?:{limit(arg:{key:string}):Promise<{success:boolean}>};
}

const cookieName='__Host-jobwatch_session';
const sessionSeconds=4*60*60;
const iterations=100_000;
const enc=new TextEncoder();
const ownerPattern=/^[a-z][a-z0-9:_-]{0,199}$/;
const hostPart=/^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/;
type Config={host:string;ownerId:string;salt:Uint8Array;verifier:Uint8Array;key:Uint8Array};

function decodeSecret(value:string|undefined,length:number):Uint8Array|null{
  if(!value||!/^[A-Za-z0-9_-]+$/.test(value)||value.length>180)return null;
  try{
    const bytes=Uint8Array.from(atob(value.replace(/-/g,'+').replace(/_/g,'/')+
      '='.repeat((4-value.length%4)%4)),c=>c.charCodeAt(0));
    return bytes.length===length?bytes:null;
  }catch{return null;}
}
export function passwordConfig(env:PasswordAuthEnv):Config{
  if(env.APP_ENV!=='password')throw new PrivateAuthError('password_runtime_disabled',503);
  const host=env.PASSWORD_HOSTNAME,ownerId=env.PRIVATE_OWNER_ID;
  if(!host||host!==host.toLowerCase()||host.length>253||host.includes(':')||
    host.split('.').length<3||!host.split('.').every(part=>hostPart.test(part))||
    host==='localhost'||!ownerId||!ownerPattern.test(ownerId)||
    ownerId.startsWith('synthetic-')||
    !env.CATALOG||!env.PERSONAL||env.CATALOG===env.PERSONAL||
    !env.PASSWORD_RATE_LIMITER)throw new PrivateAuthError('password_config_missing',503);
  const salt=decodeSecret(env.PASSWORD_PBKDF2_SALT,16);
  const verifier=decodeSecret(env.PASSWORD_PBKDF2_VERIFIER,32);
  const key=decodeSecret(env.PASSWORD_SESSION_KEY,32);
  if(!salt||!verifier||!key)throw new PrivateAuthError('password_config_missing',503);
  return {host,ownerId,salt,verifier,key};
}
function checkHost(request:Request,host:string){
  const url=new URL(request.url);
  if(url.protocol!=='https:'||url.hostname!==host||url.port||
    (request.headers.has('x-forwarded-host')&&request.headers.get('x-forwarded-host')!==host))
    throw new PrivateAuthError('password_hostname_forbidden',403);
}
function fixedEqual(a:Uint8Array,b:Uint8Array){
  if(a.length!==b.length)return false;
  let difference=0;
  for(let i=0;i<a.length;i++)difference|=a[i]!^b[i]!;
  return difference===0;
}
export async function checkPassword(password:string,config:Config){
  if(password.length<20||password.length>256)return false;
  const material=await crypto.subtle.importKey('raw',enc.encode(password),'PBKDF2',false,['deriveBits']);
  const result=new Uint8Array(await crypto.subtle.deriveBits(
    {name:'PBKDF2',hash:'SHA-256',salt:config.salt as BufferSource,iterations},material,256));
  return fixedEqual(result,config.verifier);
}
function headers(extra:Record<string,string>={}):Headers{
  return new Headers({'Cache-Control':'no-store, private','X-Content-Type-Options':'nosniff',
    'Referrer-Policy':'no-referrer','X-Frame-Options':'DENY',
    'Content-Security-Policy':"default-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'; style-src 'unsafe-inline'",
    ...extra});
}
function answer(body:string,status=200,extra:Record<string,string>={}){
  return new Response(body,{status,headers:headers(extra)});
}
function redirect(location:string,cookie?:string){
  return answer('',303,cookie?{Location:location,'Set-Cookie':cookie}:{Location:location});
}
function loginPage(invalid:boolean){
  const html=`<!doctype html><html lang="it"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Job Watch · Accesso</title>
<style>body{margin:0;min-height:100vh;display:grid;place-items:center;background:#f5f4fa;font-family:system-ui,sans-serif;color:#1c1940}main{width:min(400px,calc(100% - 56px));background:#fff;padding:28px;border-radius:16px;box-shadow:0 4px 20px #1c194019}h1{margin:0 0 8px;font-size:25px}p{color:#625f76}label{display:block;margin:24px 0 8px}input{box-sizing:border-box;width:100%;padding:14px;border:1px solid #bcb8ce;border-radius:8px;font:inherit}button{margin-top:20px;width:100%;background:#6245df;border:0;border-radius:9px;color:#fff;padding:14px;font:inherit;cursor:pointer}.error{color:#a31930}</style>
</head><body><main><h1>Job Watch</h1><p>Accesso personale</p>
${invalid?'<p class="error" role="alert">Credenziali non valide.</p>':''}
<form action="/login" method="post" autocomplete="off">
<label for="password">Password</label><input id="password" name="password" type="password" autocomplete="current-password" minlength="20" maxlength="256" required autofocus>
<button type="submit">Accedi</button></form></main></body></html>`;
  return answer(html,200,{'Content-Type':'text/html; charset=utf-8'});
}
async function readSmallBody(request:Request):Promise<string|null>{
  if(!request.body)return null;
  const reader=request.body.getReader();
  let size=0;const parts:Uint8Array[]=[];
  try{
    for(;;){
      const next=await reader.read();
      if(next.done)break;
      size+=next.value.byteLength;
      if(size>1024){await reader.cancel();return null;}
      parts.push(next.value);
    }
  }finally{reader.releaseLock();}
  const all=new Uint8Array(size);let offset=0;
  for(const part of parts){all.set(part,offset);offset+=part.length;}
  try{return new TextDecoder('utf-8',{fatal:true}).decode(all);}
  catch{return null;}
}
async function sessionToken(config:Config){
  return new SignJWT({sub:'single-owner',type:'password'})
    .setProtectedHeader({alg:'HS256'}).setIssuer('job-watch-password')
    .setAudience(config.host).setIssuedAt().setExpirationTime(sessionSeconds+'s')
    .setJti(crypto.randomUUID()).sign(config.key);
}
function sessionCookie(token:string){
  return `${cookieName}=${token}; Path=/; Max-Age=${sessionSeconds}; Secure; HttpOnly; SameSite=Strict`;
}
function clearCookie(){
  return `${cookieName}=; Path=/; Max-Age=0; Secure; HttpOnly; SameSite=Strict`;
}
export async function authenticatePasswordRequest(request:Request,config:Config):
  Promise<AuthenticatedPrincipal>{
  checkHost(request,config.host);
  const values=(request.headers.get('cookie')||'').split(';')
    .map(x=>x.trim()).filter(x=>x.startsWith(cookieName+'='));
  if(values.length!==1)throw new PrivateAuthError('password_auth_required',401);
  const token=values[0]!.slice(cookieName.length+1);
  if(token.length>2048||token.split('.').length!==3)
    throw new PrivateAuthError('password_auth_required',401);
  try{
    const {payload}=await jwtVerify(token,config.key,{algorithms:['HS256'],
      issuer:'job-watch-password',audience:config.host,
      requiredClaims:['sub','iss','aud','iat','exp','jti']});
    if(payload.sub!=='single-owner'||payload.type!=='password'||
       typeof payload.jti!=='string'||!payload.jti)
      throw Error('invalid_session');
  }catch{throw new PrivateAuthError('password_auth_required',401);}
  return {subject:'single-owner',issuer:'job-watch-password',audience:config.host,
    ownerId:config.ownerId,principalType:'interactive',
    capabilities:['catalog:read','personal:read']};
}
async function processLogin(request:Request,env:PasswordAuthEnv,config:Config){
  if(request.headers.get('origin')!==new URL(request.url).origin||
    request.headers.get('content-type')?.split(';')[0]?.toLowerCase()!=='application/x-www-form-urlencoded')
    return answer('invalid_request',403);
  const claimed=Number(request.headers.get('content-length')||'0');
  if(!Number.isSafeInteger(claimed)||claimed>1024)return answer('invalid_request',413);
  // Rate limiter must be provisioned and available. No permissive fallback.
  let permitted=false;
  try{
    const result=await env.PASSWORD_RATE_LIMITER!.limit({key:'single-owner-password'});
    permitted=result.success;
  }catch{return answer('auth_unavailable',503);}
  if(!permitted)return answer('too_many_attempts',429,{'Retry-After':'60'});
  const body=await readSmallBody(request);
  if(body===null)return answer('invalid_request',400);
  const fields=new URLSearchParams(body);
  if([...fields.keys()].length!==1||!fields.has('password'))
    return redirect('/login?error=1');
  const password=fields.get('password')!;
  if(!await checkPassword(password,config))return redirect('/login?error=1');
  const token=await sessionToken(config);
  return redirect('/',sessionCookie(token));
}
export async function handlePasswordWorker(request:Request,env:PasswordAuthEnv){
  try{
    const config=passwordConfig(env);
    checkHost(request,config.host);
    const url=new URL(request.url);
    if(url.pathname==='/login'){
      if(request.method==='GET'||request.method==='HEAD'){
        const page=loginPage(url.searchParams.get('error')==='1');
        return request.method==='HEAD'?new Response(null,{status:page.status,headers:page.headers}):page;
      }
      if(request.method==='POST')return await processLogin(request,env,config);
      return answer('method_not_allowed',405,{Allow:'GET, HEAD, POST'});
    }
    let principal:AuthenticatedPrincipal;
    try{principal=await authenticatePasswordRequest(request,config);}
    catch{
      if(request.method==='GET'||request.method==='HEAD'){
        if(url.pathname.startsWith('/api/'))return answer('auth_required',401);
        return redirect('/login');
      }
      return answer('auth_required',401);
    }
    if(url.pathname==='/logout'){
      if(request.method==='GET')return answer('<!doctype html><html lang="it"><meta charset="utf-8"><title>Esci da Job Watch</title><form action="/logout" method="post"><button>Esci</button></form></html>',200,{'Content-Type':'text/html; charset=utf-8'});
      if(request.method!=='POST')return answer('method_not_allowed',405,{Allow:'GET, POST'});
      if(request.headers.get('origin')!==url.origin)return answer('origin_required',403);
      return redirect('/login',clearCookie());
    }
    // All APP writes remain denied: privateWriteEnabled(APP_ENV=password) is false.
    // The service ingestion route is not exposed in this runtime.
    privateRequestPolicy(request,false);
    return await handlePrivateRuntime(request,env,principal);
  }catch(e){
    const status=e instanceof PrivateAuthError?e.status:503;
    const error=e instanceof PrivateAuthError?e.code:'password_runtime_unavailable';
    return answer(error,status);
  }
}
