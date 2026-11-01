// PRIVATE_CLOUDFLARE remains read-only by default. Writes require two explicit Gate B flags.
// This handler is reachable ONLY after authenticatePrivateRequest validates Access JWT.
import {z} from 'zod';
import {privateWriteEnabled} from './private-access';
import type {AuthenticatedPrincipal,PrivateAccessEnv} from './private-access';
import {executePrivatePersonalCommand,ModelCPersonalWriteError} from './data/model-c-personal-write';
import {ModelCReadError,modelCCatalogQuerySchema,getModelCCatalogSnapshot,
  getModelCCatalogJob,listModelCCatalogJobs} from './data/model-c-catalog';
import {ModelCPersonalReadError,getModelCPersonalSummary,getModelCPersonalJob,
  listModelCPersonalJobs} from './data/model-c-personal';
import {readModelCOpportunities} from './data/model-c-opportunities';

const empty=z.strictObject({});
const jobId=z.string().regex(/^job:[a-f0-9]{64}$/);
const revision=z.strictObject({revision:z.string().regex(/^[1-9][0-9]{0,9}$/).transform(Number)});
const personalPage=z.strictObject({
  limit:z.coerce.number().int().min(1).max(50).default(25),
  cursor:z.string().max(5000).optional(),
  q:z.string().trim().max(120).default(''),
  view:z.enum(['all','to_apply','applied','dismissed']).default('all'),
  decision:z.enum(['TO_REVIEW','INTERESTED','APPLIED','NOT_INTERESTED']).optional(),
  reference:z.enum(['SAVED','APPLICATION','DISMISSED']).optional(),
});
function json(value:unknown,status=200){
  return new Response(JSON.stringify(value),{status,headers:{
    'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store',
    'X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer',
  }});
}
// Cloudflare D1 Free limit exceptions are enforced account-wide (since 2026-09-01).
// Match only the documented stable error prefix; never expose exception text,
// SQL, account details, or add a paid-tier/retry fallback.
export function privateD1ErrorCode(error:unknown):'cloudflare_quota_exceeded'|'database_unavailable' {
  if(error instanceof Error &&
    /Your account has exceeded D1's free tier daily row (read|write) limit\./.test(error.message))
    return 'cloudflare_quota_exceeded';
  return 'database_unavailable';
}
/** Command transport is deliberately unavailable in the committed template.
 * A verified Access identity, same-origin browser request, two server-owned Gate B
 * settings and an atomic D1 write are ALL required for a successful response. */
async function privateCommand(request:Request,env:PrivateAccessEnv,
 principal:AuthenticatedPrincipal,kind:'decision'|'saved'):Promise<Response>{
  // Preserve legacy read-only API surface: hidden command GETs return 404.
  if(!privateWriteEnabled(env))return request.method==='GET'||request.method==='HEAD'?
    json({error:'not_found'},404):json({error:'method_not_allowed'},405);
  if(request.method!=='POST')return json({error:'method_not_allowed'},405);
  const url=new URL(request.url);
  if(url.search)return json({error:'invalid_query'},400);
  if(request.headers.get('origin')!==url.origin)return json({error:'origin_required'},403);
  if(['x-owner-id','x-user-id','x-job-watch-owner','x-actor-ref'].some(h=>request.headers.has(h)))
    return json({error:'owner_override_forbidden'},403);
  if(request.headers.get('content-type')?.split(';')[0]?.trim().toLowerCase()!=='application/json')
    return json({error:'invalid_content_type'},415);
  const declared=Number(request.headers.get('content-length')??0);
  if(!Number.isSafeInteger(declared)||declared>2048)return json({error:'body_too_large'},413);
  if(!env.CATALOG||!env.PERSONAL||env.CATALOG===env.PERSONAL)
    return json({error:'database_unavailable'},503);
  const reader=request.body?.getReader();
  if(!reader)return json({error:'invalid_body'},400);
  let size=0;const chunks:Uint8Array[]=[];
  try{
    while(true){
      const part=await reader.read();
      if(part.done)break;
      size+=part.value.byteLength;
      if(size>2048){await reader.cancel();return json({error:'body_too_large'},413);}
      chunks.push(part.value);
    }
    const bytes=new Uint8Array(size);let offset=0;
    for(const chunk of chunks){bytes.set(chunk,offset);offset+=chunk.byteLength;}
    let payload:unknown;
    try{payload=JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(bytes));}
    catch{return json({error:'invalid_json'},400);}
    if(!payload||typeof payload!=='object'||Array.isArray(payload))
      return json({error:'invalid_payload'},400);
    if((payload as Record<string,unknown>).kind!==(kind==='decision'?'DECISION':'SAVED'))
      return json({error:'invalid_payload'},400);
    return json(await executePrivatePersonalCommand(env.CATALOG,env.PERSONAL,principal,payload));
  }catch(e){
    if(e instanceof z.ZodError)return json({error:'invalid_payload'},400);
    if(e instanceof ModelCPersonalWriteError||e instanceof ModelCReadError)
      return json({error:e.code},e.status);
    return json({error:privateD1ErrorCode(e)},503);
  }
}
function input(url:URL){
  const pairs=[...url.searchParams.entries()];
  if(pairs.length>12||pairs.some(([k,v])=>k.length>64||v.length>6000)||
     new Set(pairs.map(([k])=>k)).size!==pairs.length)
    throw new ModelCReadError('invalid_query',400);
  return Object.fromEntries(pairs);
}
export async function handlePrivateRuntime(
  request:Request,env:PrivateAccessEnv,principal:AuthenticatedPrincipal,
):Promise<Response>{
  const url=new URL(request.url),path=url.pathname;
  const catalogPrefix='/api/model-c/catalog/';
  const personalPrefix='/api/model-c/personal/';
  const opportunityPrefix='/api/model-c/opportunities/';
  const commandPrefix='/api/model-c/personal/commands/';
  if(path.startsWith(commandPrefix)){
    const suffix=path.slice(commandPrefix.length);
    if(suffix!=='decision'&&suffix!=='saved')return json({error:'not_found'},404);
    return privateCommand(request,env,principal,suffix);
  }
  // The private APP handler is independent of the synthetic local Write Engine.
  if(path==='/api'||path.startsWith('/api/')){
    if(request.method!=='GET')return json({error:'method_not_allowed'},405);
    if(path==='/api/model-c/private/status'){
      if(url.search)return json({error:'invalid_query'},400);
      // Only an already-validated interactive Access principal can reach here.
      // No subject, email, owner ID, token or account detail in the response.
      return json({accessVerified:true,readOnly:!privateWriteEnabled(env),environment:'private'});
    }
    if(!path.startsWith(catalogPrefix)&&!path.startsWith(personalPrefix)&&
       !path.startsWith(opportunityPrefix))
      return json({error:'not_found'},404);
    if(!env.CATALOG||!env.PERSONAL||env.CATALOG===env.PERSONAL)
      return json({error:'database_unavailable'},503);
    try{
      const query=input(url);
      const owner={ownerId:principal.ownerId};
      if(path.startsWith(opportunityPrefix))
        return json(await readModelCOpportunities(env,path.slice(opportunityPrefix.length),query,owner));
      if(path.startsWith(catalogPrefix)){
        const suffix=path.slice(catalogPrefix.length);
        if(suffix==='snapshot'){empty.parse(query);return json(await getModelCCatalogSnapshot(env.CATALOG));}
        if(suffix==='jobs')return json(await listModelCCatalogJobs(env.CATALOG,modelCCatalogQuerySchema.parse(query)));
        if(!suffix.startsWith('jobs/'))return json({error:'not_found'},404);
        const id=jobId.parse(suffix.slice('jobs/'.length));
        return json(await getModelCCatalogJob(env.CATALOG,id,revision.parse(query).revision));
      }
      const suffix=path.slice(personalPrefix.length);
      if(suffix==='capabilities'){
        empty.parse(query);
        return json({writeEnabled:privateWriteEnabled(env),productionAccess:false});
      }
      if(suffix==='summary'){
        empty.parse(query);return json(await getModelCPersonalSummary(env.CATALOG,env.PERSONAL,owner));
      }
      if(suffix==='jobs')
        return json(await listModelCPersonalJobs(env.CATALOG,env.PERSONAL,owner,personalPage.parse(query)));
      if(!suffix.startsWith('jobs/'))return json({error:'not_found'},404);
      const id=jobId.parse(suffix.slice('jobs/'.length));
      empty.parse(query);
      return json(await getModelCPersonalJob(env.CATALOG,env.PERSONAL,owner,id));
    }catch(e){
      if(e instanceof z.ZodError)return json({error:'invalid_query'},400);
      if(e instanceof ModelCReadError||e instanceof ModelCPersonalReadError)
        return json({error:e.code},e.status);
      return json({error:privateD1ErrorCode(e)},503);
    }
  }
  if(!['GET','HEAD'].includes(request.method))return json({error:'method_not_allowed'},405);
  if(!env.ASSETS)return json({error:'assets_unavailable'},503);
  // Assumes assets.run_worker_first=true on every request. Verified in config tests.
  const asset=await env.ASSETS.fetch(request);
  const headers=new Headers(asset.headers);
  headers.set('Cache-Control','private, no-store');
  headers.set('X-Content-Type-Options','nosniff');
  headers.set('Referrer-Policy','no-referrer');
  headers.set('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'");
  return new Response(asset.body,{status:asset.status,headers});
}
