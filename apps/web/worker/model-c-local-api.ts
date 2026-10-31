// Synthetic-only local HTTP adapter. Never enables remote access or authentication.
import { z } from 'zod';
import {readModelCOpportunities} from './data/model-c-opportunities';
import {executePersonalCommand,ModelCPersonalWriteError} from './data/model-c-personal-write';
import {
  getModelCCatalogJob, getModelCCatalogSnapshot, listModelCCatalogJobs,
  ModelCReadError, modelCCatalogQuerySchema,
} from './data/model-c-catalog';
import {
  getModelCPersonalJob, getModelCPersonalSummary, listModelCPersonalJobs,
  ModelCPersonalReadError,
} from './data/model-c-personal';

export interface ModelCLocalEnv {
  APP_ENV?: string;
  MODEL_C_LOCAL_API?: string;
  MODEL_C_LOCAL_WRITE?: string;
  MODEL_C_TEST_OWNER?: string;
  CATALOG?: D1Database;
  PERSONAL?: D1Database;
}

const localHosts = new Set(['localhost', '127.0.0.1', '[::1]']);
const detailId = z.string().regex(/^job:[a-f0-9]{64}$/);
const empty = z.strictObject({});
const detailRevision = z.strictObject({
  revision: z.string().regex(/^[1-9][0-9]{0,9}$/).transform(Number),
});
const personalPage = z.strictObject({
  limit: z.coerce.number().int().min(1).max(50).default(25),
  cursor: z.string().max(5000).optional(),
  q: z.string().trim().max(120).default(''),
  view: z.enum(['all','to_apply','applied','dismissed']).default('all'),
  decision: z.enum(['TO_REVIEW','INTERESTED','APPLIED','NOT_INTERESTED']).optional(),
  reference: z.enum(['SAVED','APPLICATION','DISMISSED']).optional(),
});
const syntheticOwner = /^synthetic-[a-z][a-z0-9-]{0,63}$/;

function response(body: unknown, status = 200, extra?: HeadersInit): Response {
  const headers = new Headers(extra);
  headers.set('Content-Type', 'application/json; charset=utf-8');
  headers.set('Cache-Control', 'no-store');
  headers.set('X-Content-Type-Options', 'nosniff');
  headers.set('Referrer-Policy', 'no-referrer');
  return new Response(JSON.stringify(body), {status, headers});
}
const error = (code: string, status: number, headers?: HeadersInit) =>
  response({error: code}, status, headers);

function checkedInput(url: URL): Record<string,string> {
  const pairs = [...url.searchParams.entries()];
  if (pairs.length > 12 || pairs.some(([key,value])=>key.length>64 || value.length>6000))
    throw new ModelCReadError('invalid_query',400);
  if (new Set(pairs.map(([key])=>key)).size !== pairs.length)
    throw new ModelCReadError('duplicate_query_parameter',400);
  return Object.fromEntries(pairs);
}

/** This function is only dispatched after the existing Worker localhost guard. */
export async function handleModelCLocalApi(
  request: Request, url: URL, env: ModelCLocalEnv,
): Promise<Response> {
  // Defense in depth: this gate is not browser authentication or a deploy permit.
  if (env.APP_ENV !== 'local' || !localHosts.has(url.hostname))
    return error('remote_runtime_disabled',403);
  if (env.MODEL_C_LOCAL_API !== 'synthetic-only')
    return error('not_found',404);
  const commandPrefix='/api/model-c/personal/commands/';
  const commandRoute=url.pathname.startsWith(commandPrefix);
  if(commandRoute && request.method!=='POST')
    return error('method_not_allowed',405,{'Allow':'POST'});
  if(!commandRoute && request.method!=='GET')
    return error('method_not_allowed',405,{'Allow':'GET'});
  if (['x-owner-id','x-user-id','x-job-watch-owner','x-actor-ref'].some(k=>request.headers.has(k)))
    return error('owner_override_forbidden',403);
  const origin = request.headers.get('origin');
  if (origin && origin !== url.origin) return error('cross_origin_forbidden',403);
  if(commandRoute){
    if(env.MODEL_C_LOCAL_WRITE!=='synthetic-only')return error('not_found',404);
    if(origin!==url.origin)return error('origin_required',403);
    if(request.headers.get('content-type')?.split(';')[0]?.trim().toLowerCase()!=='application/json')
      return error('invalid_content_type',415);
    if(url.search)return error('invalid_query',400);
    if(!env.CATALOG||!env.PERSONAL)return error('database_unavailable',503);
    if(!env.MODEL_C_TEST_OWNER||!syntheticOwner.test(env.MODEL_C_TEST_OWNER))
      return error('synthetic_owner_unavailable',403);
    const command=url.pathname.slice(commandPrefix.length);
    if(!['decision','saved'].includes(command))return error('not_found',404);
    try{
      const declared=Number(request.headers.get('content-length')??0);
      if(!Number.isSafeInteger(declared)||declared>2048)return error('body_too_large',413);
      // Bound streamed and Content-Length-free requests before parsing JSON.
      const reader=request.body?.getReader();
      if(!reader)return error('invalid_body',400);
      let size=0;
      const chunks:Uint8Array[]=[];
      while(true){
        const part=await reader.read();
        if(part.done)break;
        size+=part.value.byteLength;
        if(size>2048){await reader.cancel();return error('body_too_large',413);}
        chunks.push(part.value);
      }
      const bytes=new Uint8Array(size);
      let offset=0;
      for(const part of chunks){bytes.set(part,offset);offset+=part.length;}
      let payload:unknown;
      try{payload=JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(bytes));}
      catch{return error('invalid_json',400);}
      if(!payload||typeof payload!=='object'||Array.isArray(payload))return error('invalid_payload',400);
      // Command type is taken from the route, never trusted from the request body alone.
      const body=payload as Record<string,unknown>;
      if(body.kind!==(command==='decision'?'DECISION':'SAVED'))return error('invalid_payload',400);
      return response(await executePersonalCommand(env.CATALOG,env.PERSONAL,
        {ownerId:env.MODEL_C_TEST_OWNER},body));
    }catch(e){
      if(e instanceof z.ZodError)return error('invalid_payload',400);
      if(e instanceof ModelCPersonalWriteError||e instanceof ModelCReadError||
        e instanceof ModelCPersonalReadError)return error(e.code,e.status);
      return error('write_unavailable',503);
    }
  }

  const path = url.pathname;
  const catalogPrefix = '/api/model-c/catalog/';
  const personalPrefix = '/api/model-c/personal/';
  const opportunitiesPrefix='/api/model-c/opportunities/';
  if (!path.startsWith(catalogPrefix) && !path.startsWith(personalPrefix) && !path.startsWith(opportunitiesPrefix))
    return error('not_found',404);
  try {
    const input = checkedInput(url);
    if(path.startsWith(opportunitiesPrefix))
      return response(await readModelCOpportunities(env,path.slice(opportunitiesPrefix.length),input));
    const catalogPath = path.startsWith(catalogPrefix);
    const suffix = path.slice(catalogPath ? catalogPrefix.length : personalPrefix.length);
    if (!catalogPath && !['summary','jobs','capabilities'].includes(suffix) && !suffix.startsWith('jobs/'))
      return error('not_found',404);
    if (catalogPath && !['snapshot','jobs'].includes(suffix) && !suffix.startsWith('jobs/'))
      return error('not_found',404);

    if (!env.CATALOG) return error('database_unavailable',503);
    if (catalogPath) {
      if (suffix === 'snapshot') {
        empty.parse(input);
        return response(await getModelCCatalogSnapshot(env.CATALOG));
      }
      if (suffix === 'jobs')
        return response(await listModelCCatalogJobs(env.CATALOG,modelCCatalogQuerySchema.parse(input)));
      const id = detailId.parse(suffix.slice('jobs/'.length));
      const {revision} = detailRevision.parse(input);
      return response(await getModelCCatalogJob(env.CATALOG,id,revision));
    }

    if (!env.PERSONAL) return error('database_unavailable',503);
    // Only a test-owned, server-provided synthetic identity can reach PERSONAL.
    // A client-provided query/header/cookie can never choose this owner.
    if (!env.MODEL_C_TEST_OWNER || !syntheticOwner.test(env.MODEL_C_TEST_OWNER))
      return error('synthetic_owner_unavailable',403);
    const trusted = {ownerId:env.MODEL_C_TEST_OWNER};
    if(suffix==='capabilities'){
      empty.parse(input);
      return response({writeEnabled:env.MODEL_C_LOCAL_WRITE==='synthetic-only',productionAccess:false});
    }
    if (suffix === 'summary') {
      empty.parse(input);
      return response(await getModelCPersonalSummary(env.CATALOG,env.PERSONAL,trusted));
    }
    if (suffix === 'jobs')
      return response(await listModelCPersonalJobs(env.CATALOG,env.PERSONAL,trusted,personalPage.parse(input)));
    const id = detailId.parse(suffix.slice('jobs/'.length));
    empty.parse(input);
    return response(await getModelCPersonalJob(env.CATALOG,env.PERSONAL,trusted,id));
  } catch (e) {
    if (e instanceof z.ZodError) return error('invalid_query',400);
    if (e instanceof ModelCReadError || e instanceof ModelCPersonalReadError)
      return error(e.code,e.status);
    // Never log or echo SQL, DB schema, credentials, private facts or request inputs.
    return error('database_unavailable',503);
  }
}
