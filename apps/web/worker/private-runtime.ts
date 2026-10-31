// PRIVATE_CLOUDFLARE is read-only until a separately reviewed remote write milestone.
// This handler is reachable ONLY after authenticatePrivateRequest validates Access JWT.
import {z} from 'zod';
import type {AuthenticatedPrincipal,PrivateAccessEnv} from './private-access';
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
  // PRIVATE never dispatches POST to the local-only Write Engine.
  if(path==='/api'||path.startsWith('/api/')){
    if(request.method!=='GET')return json({error:'method_not_allowed'},405);
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
        return json({writeEnabled:false,productionAccess:false});
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
