// Private Cloudflare runtime: verify the Access JWT for EVERY request, including static assets.
// ctx.access is intentionally not used: Workers Static Assets router omits it for the user Worker.
// Server configuration is necessary but NEVER sufficient to authenticate a request.
import {createRemoteJWKSet,jwtVerify} from 'jose';
import type {JWTVerifyGetKey} from 'jose';
import {z} from 'zod';

export interface PrivateAccessEnv {
  APP_ENV?:string;
  PRIVATE_HOSTNAME?:string;
  PRIVATE_ACCESS_ISSUER?:string;
  PRIVATE_ACCESS_AUD?:string;
  PRIVATE_ALLOWED_SUB?:string;
  PRIVATE_OWNER_ID?:string;
  // Never set in an unapproved template. Gate B must independently verify account quota.
  PRIVATE_APP_WRITE_GATE?:string;
  PRIVATE_QUOTA_ATTESTED?:string;
  CATALOG?:D1Database;
  PERSONAL?:D1Database;
  ASSETS?:Fetcher;
}
export type AuthenticatedPrincipal={
  subject:string;issuer:string;audience:string;ownerId:string;
  principalType:'interactive';capabilities:readonly ['catalog:read','personal:read'];
};
export class PrivateAuthError extends Error {
  constructor(readonly code:string,readonly status:number=403){super(code);}
}
const asciiLabel=/^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/;
const subject=z.string().min(8).max(256);
const ownerId=z.string().min(1).max(200).regex(/^[a-z][a-z0-9:_-]*$/);
export type PrivateAccessConfig={
  host:string;issuer:string;audience:string;allowlistedSubject:string;ownerId:string;
};
export function privateAccessConfig(env:PrivateAccessEnv):PrivateAccessConfig{
  if(env.APP_ENV!=='private')throw new PrivateAuthError('private_runtime_disabled');
  const host=env.PRIVATE_HOSTNAME;
  const rawIssuer=env.PRIVATE_ACCESS_ISSUER;
  const aud=env.PRIVATE_ACCESS_AUD;
  if(!host||!rawIssuer||!aud||!env.PRIVATE_ALLOWED_SUB||!env.PRIVATE_OWNER_ID)
    throw new PrivateAuthError('private_config_missing',503);
  if(host.length>253||host!==host.toLowerCase()||host.includes(':')||
      !host.split('.').every(label=>asciiLabel.test(label))||host.split('.').length<2||
      host.endsWith('.workers.dev')||host==='localhost'||/^\\d{1,3}(?:\\.\\d{1,3}){3}$/.test(host))
    throw new PrivateAuthError('private_config_invalid',503);
  let issuer:URL;
  try{issuer=new URL(rawIssuer);}catch{throw new PrivateAuthError('private_config_invalid',503);}
  if(issuer.protocol!=='https:'||issuer.username||issuer.password||issuer.port||
     issuer.pathname!=='/'||issuer.search||issuer.hash||
     !issuer.hostname.endsWith('.cloudflareaccess.com')||
     issuer.hostname==='cloudflareaccess.com')
    throw new PrivateAuthError('private_config_invalid',503);
  if(!/^[a-zA-Z0-9_-]{16,128}$/.test(aud))
    throw new PrivateAuthError('private_config_invalid',503);
  if(!subject.safeParse(env.PRIVATE_ALLOWED_SUB).success||
     !ownerId.safeParse(env.PRIVATE_OWNER_ID).success||
     env.PRIVATE_OWNER_ID.startsWith('synthetic-')||
     env.PRIVATE_ALLOWED_SUB===env.PRIVATE_OWNER_ID)
    throw new PrivateAuthError('private_config_invalid',503);
  return {host,issuer:issuer.origin,audience:aud,
    allowlistedSubject:env.PRIVATE_ALLOWED_SUB,ownerId:env.PRIVATE_OWNER_ID};
}
const remoteKeys=new Map<string,JWTVerifyGetKey>();
function keySet(issuer:string):JWTVerifyGetKey{
  let key=remoteKeys.get(issuer);
  if(!key){
    key=createRemoteJWKSet(new URL(issuer+'/cdn-cgi/access/certs'),{
      cooldownDuration:30_000,cacheMaxAge:5*60_000,timeoutDuration:3500,
    });
    remoteKeys.set(issuer,key);
  }
  return key;
}
/** keyResolver is a pure test seam. No caller-controlled HTTP field can select it. */
export async function authenticatePrivateRequest(
  request:Request,env:PrivateAccessEnv,testKeyResolver?:JWTVerifyGetKey,
):Promise<AuthenticatedPrincipal>{
  const config=privateAccessConfig(env);
  const url=new URL(request.url);
  if(url.protocol!=='https:'||url.hostname!==config.host||url.port||
      request.headers.get('x-forwarded-host') && request.headers.get('x-forwarded-host')!==config.host)
    throw new PrivateAuthError('private_hostname_forbidden');
  if(!env.CATALOG||!env.PERSONAL||env.CATALOG===env.PERSONAL)
    throw new PrivateAuthError('private_databases_unavailable',503);
  const raw=request.headers.get('cf-access-jwt-assertion');
  if(!raw||raw.length>8192||raw.split('.').length!==3)
    throw new PrivateAuthError('private_auth_required',401);
  let payload;
  try{
    ({payload}=await jwtVerify(raw,testKeyResolver??keySet(config.issuer),{
      algorithms:['RS256'],issuer:config.issuer,audience:config.audience,
      clockTolerance:5,requiredClaims:['sub','iss','aud','exp','iat'],
    }));
  }catch{
    throw new PrivateAuthError('private_auth_invalid',401);
  }
  if(typeof payload.sub!=='string'||payload.sub!==config.allowlistedSubject||
      // Cloudflare application JWT: type=app for user AND service tokens.
      // Real user token includes an IdP email; service token has common_name and
      // empty sub. Never use email as the owner key or expose it to callers.
      payload.type!=='app'||typeof payload.email!=='string'||!payload.email||
      payload.common_name!==undefined||payload.service_token_id!==undefined||
      payload.service_token_status===true)
    throw new PrivateAuthError('private_access_denied');
  // No email, cookies, IP or request-supplied owner IDs are used in the mapping.
  return {subject:payload.sub,issuer:config.issuer,audience:config.audience,
    ownerId:config.ownerId,principalType:'interactive',
    capabilities:['catalog:read','personal:read']};
}
/** Both server-owned Gate B flags must be deliberately configured.
 * Neither an API client nor a service JWT may select a write permission. */
export function privateWriteEnabled(env:PrivateAccessEnv){
  return env.APP_ENV==='private' && env.PRIVATE_APP_WRITE_GATE==='gate-b-approved' &&
    env.PRIVATE_QUOTA_ATTESTED==='verified-under-budget';
}
export function privateRequestPolicy(request:Request,writeEnabled=false){
  const url=new URL(request.url);
  // POST is permitted only for the two owner-bound APP command routes after Gate B.
  const isApprovedCommand=writeEnabled && request.method==='POST' &&
    /^\/api\/model-c\/personal\/commands\/(?:decision|saved)$/.test(url.pathname);
  if(!isApprovedCommand&&request.method!=='GET'&&request.method!=='HEAD')
    throw new PrivateAuthError('method_not_allowed',405);
  if(isApprovedCommand&&request.headers.get('origin')!==url.origin)
    throw new PrivateAuthError('origin_required',403);
  const origin=request.headers.get('origin');
  if(origin && origin!==url.origin)throw new PrivateAuthError('cross_origin_forbidden');
  if(['x-owner-id','x-user-id','x-job-watch-owner','x-actor-ref'].some(h=>request.headers.has(h)))
    throw new PrivateAuthError('owner_override_forbidden');
}
