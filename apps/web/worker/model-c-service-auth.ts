// M46: service-only identity verifier. DELIBERATELY NOT imported by worker/index.ts.
// Only an offline HTTP harness may call this until separately authorized Gate B.
import {createRemoteJWKSet,jwtVerify} from 'jose';
import type {JWTVerifyGetKey} from 'jose';

export type ServicePrincipal={principalType:'service';clientId:string;capabilities:readonly ['catalog:stage']};
export type ServiceAuthConfig={
  hostname:string;issuer:string;audience:string;allowedClientId:string;
};
export class ServiceAuthError extends Error {
  constructor(readonly code:string,readonly status:number=403){super(code);}
}
const hostnamePattern=/^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$/;
const audiencePattern=/^[a-zA-Z0-9_-]{16,128}$/;
const clientIdPattern=/^[A-Za-z0-9_-]{12,130}\.access$/;
export function validateServiceConfig(config:ServiceAuthConfig){
  let issuer:URL;
  try{issuer=new URL(config.issuer);}catch{throw new ServiceAuthError('service_config_invalid',503);}
  if(!hostnamePattern.test(config.hostname)||config.hostname.endsWith('.workers.dev')||
    config.hostname.endsWith('.invalid')===false && config.hostname==='localhost'||
    issuer.protocol!=='https:'||!issuer.hostname.endsWith('.cloudflareaccess.com')||
    issuer.username||issuer.password||issuer.port||issuer.search||issuer.hash||
    issuer.pathname!=='/'||!audiencePattern.test(config.audience)||
    !clientIdPattern.test(config.allowedClientId))
    throw new ServiceAuthError('service_config_invalid',503);
  return {issuer:issuer.origin};
}
const remoteKeys=new Map<string,JWTVerifyGetKey>();
function verifiedKeys(issuer:string):JWTVerifyGetKey {
  let keys=remoteKeys.get(issuer);
  if(!keys){
    keys=createRemoteJWKSet(new URL(issuer+'/cdn-cgi/access/certs'),{
      cooldownDuration:30_000,cacheMaxAge:300_000,timeoutDuration:3500,
    });
    remoteKeys.set(issuer,keys);
  }
  return keys;
}
export async function verifyServicePrincipal(request:Request,config:ServiceAuthConfig,
  keyResolver?:JWTVerifyGetKey):Promise<ServicePrincipal>{
  const {issuer}=validateServiceConfig(config);
  const url=new URL(request.url);
  if(url.protocol!=='https:'||url.hostname!==config.hostname||url.port||
    request.headers.has('x-forwarded-host')&&request.headers.get('x-forwarded-host')!==config.hostname ||
    request.headers.has('x-owner-id')||request.headers.has('x-user-id')||
    request.headers.has('x-job-watch-owner')||request.headers.has('x-actor-ref'))
    throw new ServiceAuthError('service_host_or_identity_forbidden');
  // Browsers are not ingestion clients. Tokens in Cookies or user-supplied client
  // secret headers are not proof for the Worker; only a signed Access JWT is.
  if(request.headers.has('origin')||request.headers.has('cookie')||
    request.headers.has('cf-access-client-id')||request.headers.has('cf-access-client-secret'))
    throw new ServiceAuthError('service_browser_context_forbidden');
  const raw=request.headers.get('cf-access-jwt-assertion');
  if(!raw||raw.length>8192||raw.split('.').length!==3)
    throw new ServiceAuthError('service_auth_required',401);
  let payload;
  try{
    ({payload}=await jwtVerify(raw,keyResolver??verifiedKeys(issuer),{
      algorithms:['RS256'],issuer,audience:config.audience,clockTolerance:5,
      requiredClaims:['sub','iss','aud','exp','iat'],
    }));
  }catch{throw new ServiceAuthError('service_auth_invalid',401);}
  // Cloudflare Access service application JWT: type app, empty sub and
  // common_name = service token client ID. Interactive tokens carry user sub/email.
  if(payload.type!=='app'||payload.sub!==''||
    payload.common_name!==config.allowedClientId||
    payload.email!==undefined||payload.user_uuid!==undefined||
    payload.service_token_status===false)
    throw new ServiceAuthError('service_principal_denied');
  return {principalType:'service',clientId:config.allowedClientId,capabilities:['catalog:stage']};
}
