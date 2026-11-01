/**
 * M50: detached, operator-only Cloudflare D1 REST transport.
 * Cloudflare REST documents params:string[] (unlike Worker typed bindings).
 * Explicit CAST and literal NULL preserve D1 value types without guessing.
 * This module is NEVER reachable from a Worker/browser or staging service JWT.
 *
 * No network requests on construction. The caller must separately authorize
 * Gate B, attest account-wide Free quota, and supply an operator-owned D1 token.
 * Remote batch atomicity/typed SQL parity still require real Gate B proof.
 */
export type M50RestValue=string|number|null;
type WireQuery={sql:string;params:string[]};
type QueryResult={success:true;results:Record<string,unknown>[];
 meta:{rows_read:number;rows_written:number;duration:number}};
type HttpTransport=(request:Request)=>Promise<Response>;
type Config={
 accountId:string;catalogDatabaseId:string;personalDatabaseId:string;
 apiToken:string;gateBApproved:boolean;accountFreePlanVerified:boolean;
 operatorQuotaVerified:boolean;remainingWriteUnits:number;quotaDay:string;
 validUntil:string;
 transport?:HttpTransport;
};
const uuid=/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;
const account=/^[a-f0-9]{32}$/i;
const authorized=new WeakMap<object,{catalog:D1Database;personal:D1Database;
 remainingWriteUnits:number;quotaDay:string;expiresAt:number}>();
const fail=(code:string):never=>{throw Error(code);};
const flat=(value:unknown):value is Record<string,unknown>=>
 !!value&&typeof value==='object'&&!Array.isArray(value);

/** Tokenize SQLITE placeholders, ignoring strings, quoted identifiers and comments.
 * Null is SQL NULL and finite numbers use an explicit SQL CAST over REST TEXT.
 * The value never becomes an interpolated SQL literal. SQL comes only from
 * our trusted source-controlled importer, never from the HTTP caller.
 */
export function encodeM50RestQuery(sql:string,values:readonly M50RestValue[]=[]):WireQuery{
 if(typeof sql!=='string'||!sql.trim()||sql.length>65536||/\0/.test(sql))
   fail('M50_SQL_INVALID');
 let result='',state:'sql'|'single'|'double'|'backtick'|'bracket'|'line'|'block'='sql';
 let i=0,position=0;const params:string[]=[];
 while(i<sql.length){
  const c=sql[i]!,next=sql[i+1];
  if(state==='sql'){
   if(c==="'"||c==='"'||c==='`'||c==='['){
    state=c==="'"?'single':c==='"'?'double':c==='`'?'backtick':'bracket';
   }else if(c==='-'&&next==='-'){state='line';result+='--';i+=2;continue;}
   else if(c==='/'&&next==='*'){state='block';result+='/*';i+=2;continue;}
   else if(c===';')fail('M50_MULTI_STATEMENT_FORBIDDEN');
   else if(c==='?'){
    if(next&&/[0-9]/.test(next))fail('M50_NUMBERED_BIND_FORBIDDEN');
    if(position>=values.length)fail('M50_BIND_COUNT_MISMATCH');
    const v=values[position++];
    if(v===null){result+='NULL';i++;continue;}
    if(typeof v==='string'){if(v.length>120000)fail('M50_BIND_TOO_LONG');params.push(v);result+='?';i++;continue;}
    if(typeof v==='number'&&Number.isFinite(v)&&Number.isSafeInteger(v)){
     params.push(String(v));result+='CAST(? AS INTEGER)';i++;continue;
    }
    if(typeof v==='number'&&Number.isFinite(v)){
     params.push(String(v));result+='CAST(? AS REAL)';i++;continue;
    }
    fail('M50_UNSUPPORTED_BIND');
   }
  } else if(state==='line'&&c==='\n')state='sql';
  else if(state==='block'&&c==='*'&&next==='/'){result+='*/';i+=2;state='sql';continue;}
  else if(state==='single'&&c==="'"){
   if(next==="'"){result+="''";i+=2;continue;}state='sql';
  }else if(state==='double'&&c==='"'){
   if(next==='"'){result+='""';i+=2;continue;}state='sql';
  }else if(state==='backtick'&&c==='`')state='sql';
  else if(state==='bracket'&&c===']')state='sql';
  result+=c;i++;
 }
 if(position!==values.length)fail('M50_BIND_COUNT_MISMATCH');
 if(state==='single'||state==='double'||state==='backtick'||state==='bracket'||state==='block')
  fail('M50_SQL_UNTERMINATED');
 if(result.length>65536)fail('M50_SQL_TOO_LARGE');
 return {sql:result,params};
}
function validateResult(value:unknown):QueryResult{
 if(!flat(value)||value.success!==true||!Array.isArray(value.results)||
    !value.results.every(flat)||!flat(value.meta))
   throw Error('M50_REST_RESULT_UNVERIFIED');
 const m=value.meta;
 if(!Number.isSafeInteger(m.rows_written)||Number(m.rows_written)<0||
    !Number.isSafeInteger(m.rows_read)||Number(m.rows_read)<0)
   throw Error('M50_REST_META_UNVERIFIED');
 return {success:true,results:value.results as Record<string,unknown>[],
  meta:{rows_written:Number(m.rows_written),rows_read:Number(m.rows_read),
   duration:typeof m.duration==='number'&&Number.isFinite(m.duration)?m.duration:0}};
}
function createD1(config:Config,id:string):D1Database{
 const endpoint='https://api.cloudflare.com/client/v4/accounts/'+config.accountId+
    '/d1/database/'+id+'/query';
 const send=async(queries:WireQuery[]):Promise<QueryResult[]>=>{
  if(queries.length<1||queries.length>8000)fail('M50_BATCH_LIMIT');
  // Every batch is ONE HTTP request. No per-statement fallback or retry.
  const request=new Request(endpoint,{method:'POST',headers:{
   authorization:'Bearer '+config.apiToken,'content-type':'application/json',
  },body:JSON.stringify({batch:queries})});
  let response:Response;
  try{response=await (config.transport??fetch)(request);}
  catch{throw Error('M50_REST_OUTCOME_UNKNOWN');}
  if(!response.ok)fail('M50_REST_OUTCOME_UNKNOWN');
  let json:unknown;
  try{json=await response.json();}catch{throw Error('M50_REST_RESPONSE_INVALID');}
  if(!flat(json)||json.success!==true||!Array.isArray(json.result)||
     json.result.length!==queries.length)
   throw Error('M50_REST_BATCH_NOT_CONFIRMED');
  return json.result.map(validateResult);
 };
 type Prepared={sql:string;params:M50RestValue[]};
 const statements=new WeakMap<object,Prepared>();
 const prepare=(sql:string,values:M50RestValue[]=[]):D1PreparedStatement=>{
  const s={
   // Prepared SQL may contain unbound placeholders: only encode on execution.
   bind:(...args:M50RestValue[])=>prepare(sql,args),
   all:async<T=Record<string,unknown>>()=>(await send([encodeM50RestQuery(sql,values)]))[0] as D1Result<T>,
   run:async<T=Record<string,unknown>>()=>(await send([encodeM50RestQuery(sql,values)]))[0] as D1Result<T>,
   first:async<T=Record<string,unknown>>(column?:string)=>{
    const row=(await send([encodeM50RestQuery(sql,values)]))[0]!.results[0];
    if(!row)return null;
    if(column!==undefined){
     if(!(column in row))fail('M50_REST_COLUMN_MISSING');
     return row[column] as T;
    }
    return row as T;
   },
   raw:async()=>fail('M50_REST_RAW_UNSUPPORTED'),
  } as unknown as D1PreparedStatement;
  statements.set(s,{sql,params:values});
  return s;
 };
 const batch=async<T=Record<string,unknown>>(items:D1PreparedStatement[])=>{
  if(!Array.isArray(items)||!items.length)fail('M50_BATCH_EMPTY');
  const wire=items.map(item=>{
   const value=statements.get(item);
   if(!value)throw Error('M50_FOREIGN_PREPARED_STATEMENT');
   return encodeM50RestQuery(value.sql,value.params);
  });
  return await send(wire) as D1Result<T>[];
 };
 return {prepare,batch} as unknown as D1Database;
}
/** Inaccessible to HTTP clients; remote invocation requires separately approved
 * operator credentials, account evidence, two distinct D1 IDs and a short
 * quota attestation. No token is stored in the returned object/commit logs.
 */
export function createM50RemoteOperatorPair(config:Config){
 if(config.gateBApproved!==true||config.accountFreePlanVerified!==true||
    config.operatorQuotaVerified!==true||!account.test(config.accountId)||
    !uuid.test(config.catalogDatabaseId)||!uuid.test(config.personalDatabaseId)||
    config.catalogDatabaseId===config.personalDatabaseId||
    !Number.isSafeInteger(config.remainingWriteUnits)||
    config.remainingWriteUnits<0||config.remainingWriteUnits>30000||
    config.quotaDay!==new Date().toISOString().slice(0,10)||
    !config.apiToken||config.apiToken.length<20||config.apiToken.length>2048||
    !Number.isFinite(Date.parse(config.validUntil))||
    Date.parse(config.validUntil)<=Date.now()||
    Date.parse(config.validUntil)>Date.now()+300000)
   fail('M50_REMOTE_OPERATOR_GATE_CLOSED');
 const catalog=createD1(config,config.catalogDatabaseId);
 const personal=createD1(config,config.personalDatabaseId);
 const capability=Object.freeze({});
 authorized.set(capability,{catalog,personal,
  remainingWriteUnits:config.remainingWriteUnits,quotaDay:config.quotaDay,
  expiresAt:Date.parse(config.validUntil)});
 return {catalog,personal,capability,remoteExecutionAuthorized:true as const};
}
/** Runtime-only capability tied to the EXACT two D1 transport instances. */
export function isM50AuthorizedRemotePair(capability:object|undefined,
 catalog:D1Database,personal:D1Database,budget?:{availableRows:number;day:string}){
 if(!capability)return false;
 const refs=authorized.get(capability);
 return !!refs&&refs.catalog===catalog&&refs.personal===personal&&
   refs.expiresAt>Date.now()&&
   refs.quotaDay===new Date().toISOString().slice(0,10)&&
   (!budget||(budget.day===refs.quotaDay&&
     Number.isSafeInteger(budget.availableRows)&&budget.availableRows>=0&&
     budget.availableRows<=refs.remainingWriteUnits));
}
