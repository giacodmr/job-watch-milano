import {expect,it} from 'vitest';
import {Miniflare,convertV4MiniflareOptions} from 'miniflare';
import {encodeM50RestQuery,createM50RemoteOperatorPair,
 isM50AuthorizedRemotePair} from '../tools/model-c-m50-d1-rest';
import {importModelC} from '../tools/model-c-importer';
const catalogId='11111111-1111-4111-8111-111111111111';
const personalId='22222222-2222-4222-8222-222222222222';
const accountId='a'.repeat(32);
const config=(transport:(request:Request)=>Promise<Response>)=>({
 accountId,catalogDatabaseId:catalogId,personalDatabaseId:personalId,
 apiToken:'SYNTHETIC_OPERATOR_TEST_TOKEN_0000',gateBApproved:true,
 accountFreePlanVerified:true,operatorQuotaVerified:true,
 remainingWriteUnits:30000,quotaDay:new Date().toISOString().slice(0,10),
 validUntil:new Date(Date.now()+120000).toISOString(),transport,
});
it('uses explicit type casts and NULL without SQL/text parameter interpolation',()=>{
 expect(encodeM50RestQuery("SELECT ? AS txt, ? AS n, ? AS nil, ? AS frac, '?' AS literal",
   ["x'; DROP TABLE catalog_head; --",42,null,0.25])).toEqual({
    sql:"SELECT ? AS txt, CAST(? AS INTEGER) AS n, NULL AS nil, CAST(? AS REAL) AS frac, '?' AS literal",
    params:["x'; DROP TABLE catalog_head; --","42","0.25"]});
 expect(encodeM50RestQuery('SELECT "?" AS identifier, ? AS value',[0]).sql)
  .toBe('SELECT "?" AS identifier, CAST(? AS INTEGER) AS value');
 for(const [sql,params] of [
  ['SELECT ?',[1,2]],['SELECT ?1',[7]],['SELECT ?; SELECT 2',[1]],
  ["SELECT 'unclosed",[1]],['SELECT ?',[NaN]],['SELECT ?',[Infinity]],
  ['SELECT ?',[true]],['SELECT ?',[undefined]]
 ] as [string,unknown[]][])expect(()=>encodeM50RestQuery(sql,
    params as (string|number|null)[])).toThrow();
});
it('denies unknown operator authority without issuing any HTTP request',async()=>{
 let calls=0;const transport=async()=>{calls++;return Response.json({success:true,result:[]});};
 const good=config(transport);
 for(const bad of [
  {...good,gateBApproved:false},
  {...good,accountFreePlanVerified:false},
  {...good,operatorQuotaVerified:false},
  {...good,validUntil:new Date(Date.now()-1000).toISOString()},
  {...good,catalogDatabaseId:good.personalDatabaseId},
  {...good,remainingWriteUnits:-1},
  {...good,quotaDay:'2000-01-01'},
 ]){
  expect(()=>createM50RemoteOperatorPair(bad)).toThrow('M50_REMOTE_OPERATOR_GATE_CLOSED');
 }
 expect(calls).toBe(0);
 const pair=createM50RemoteOperatorPair(good);
 expect(isM50AuthorizedRemotePair(pair.capability,pair.catalog,pair.personal)).toBe(true);
 expect(isM50AuthorizedRemotePair({},pair.catalog,pair.personal)).toBe(false);
 expect(isM50AuthorizedRemotePair(pair.capability,pair.personal,pair.catalog)).toBe(false);
 expect(isM50AuthorizedRemotePair(pair.capability,pair.catalog,pair.personal,
   {availableRows:30001,day:new Date().toISOString().slice(0,10)})).toBe(false);
 expect(isM50AuthorizedRemotePair(pair.capability,pair.catalog,pair.personal,
   {availableRows:30000,day:new Date().toISOString().slice(0,10)})).toBe(true);
 await expect(importModelC(pair.catalog,pair.personal,{
  source:{repo:'.',commit:'a'.repeat(40)},owner:'synthetic-owner',
  budget:{day:new Date().toISOString().slice(0,10),availableRows:30000},
  executionTarget:'remote',bootstrap:'empty-target',
 })).rejects.toThrow('REMOTE_IMPORT_NOT_AUTHORIZED');
 expect(calls).toBe(0);
});
it('executes typed/null readback through real local D1 and fails closed on one atomic bad batch',async()=>{
 const mf=new Miniflare(convertV4MiniflareOptions({
  modules:true,cf:false,script:'export default {fetch(){return new Response("synthetic")}}',
  compatibilityDate:'2026-10-29',d1Databases:{CATALOG:'m50-rest-cat',PERSONAL:'m50-rest-pers'},
 }));
 try{
  const c=await mf.getD1Database('CATALOG');
  const p=await mf.getD1Database('PERSONAL');
  await c.prepare('CREATE TABLE typed(id INTEGER PRIMARY KEY, name TEXT, nullable TEXT, fraction REAL)').run();
  const calls:{path:string;method:string;payload:unknown}[]=[];
  const transport=async(req:Request)=>{
   const path=new URL(req.url).pathname;
   const db=path.includes(catalogId)?c:path.includes(personalId)?p:null;
   const payload=await req.json() as {batch:{sql:string;params:string[]}[]};
   calls.push({path,method:req.method,payload});
   if(!db)return Response.json({success:false,result:[]},{status:404});
   try{
    return Response.json({success:true,result:await db.batch(payload.batch.map(q=>
     db.prepare(q.sql).bind(...q.params)))});
   }catch{
    return Response.json({success:false,result:[]},{status:400});
   }
  };
  const pair=createM50RemoteOperatorPair(config(transport));
  expect((await pair.catalog.prepare("SELECT ? AS n, ? AS nil, '?' AS text")
   .bind(9,null).first<{n:number;nil:null;text:string}>()))
   .toEqual({n:9,nil:null,text:'?'});
  const values=await pair.catalog.batch([
   pair.catalog.prepare('INSERT INTO typed(id,name,nullable,fraction) VALUES (?,?,?,?)')
    .bind(1,'trusted',null,1.25),
   pair.catalog.prepare('SELECT typeof(id) AS a,typeof(nullable) AS b,typeof(fraction) AS c FROM typed WHERE id=?').bind(1),
  ]);
  expect(values).toHaveLength(2);
  expect(values[1]!.results).toEqual([{a:'integer',b:'null',c:'real'}]);
  expect((await pair.catalog.prepare('SELECT name FROM typed WHERE id=?').bind(1).first<string>('name')))
   .toBe('trusted');
  // Journal COMPLETE uses prepared.run() (not batch or all). Compare exactly
  // the bound six-placeholder SQL through direct D1 and synthetic REST.
  await c.prepare('CREATE TABLE journal_probe (run_id TEXT, sequence INTEGER, phase TEXT, proof_digest TEXT, previous_digest TEXT, event_digest TEXT)').run();
  const journalSql='INSERT INTO journal_probe (run_id,sequence,phase,proof_digest,previous_digest,event_digest) VALUES (?,?,?,?,?,?)';
  const journalValues=['ingest-v2:synthetic',1,'COMPLETE','a'.repeat(64),'b'.repeat(64),'c'.repeat(64)] as const;
  await c.prepare(journalSql).bind(...journalValues).run();
  const viaRest=await pair.catalog.prepare(journalSql).bind(
    'ingest-v2:synthetic-rest',...journalValues.slice(1)).run();
  expect(viaRest.success).toBe(true);
  const restCall=calls[calls.length-1]!.payload as {batch:{sql:string;params:string[]}[]};
  expect(restCall.batch).toEqual([encodeM50RestQuery(journalSql,
    ['ingest-v2:synthetic-rest',...journalValues.slice(1)])]);
  expect((await c.prepare('SELECT sequence,phase,proof_digest,previous_digest,event_digest FROM journal_probe WHERE run_id=?')
   .bind('ingest-v2:synthetic-rest').first())).toEqual(
   await c.prepare('SELECT sequence,phase,proof_digest,previous_digest,event_digest FROM journal_probe WHERE run_id=?')
    .bind('ingest-v2:synthetic').first());
  await expect(pair.catalog.batch([
   pair.catalog.prepare('INSERT INTO typed(id,name) VALUES (?,?)').bind(2,'rolled-back'),
   pair.catalog.prepare('INSERT INTO typed(id,name) VALUES (?,?)').bind(1,'unique-conflict'),
  ])).rejects.toThrow('M50_REST_OUTCOME_UNKNOWN');
  expect(await c.prepare('SELECT name FROM typed WHERE id=2').first()).toBeNull();
  expect(calls.every(x=>x.method==='POST'&&x.path.includes(accountId))).toBe(true);
  // No second request should be sent on ambiguous responses or rollback.
  const before=calls.length;
  const errorTransport=async()=>{throw Error('SYNTHETIC_LOST_ACK');};
  const denied=createM50RemoteOperatorPair(config(errorTransport));
  await expect(denied.catalog.prepare('SELECT 1').all()).rejects.toThrow('M50_REST_OUTCOME_UNKNOWN');
  expect(calls.length).toBe(before);
  // Database instance identity prevents cross-scope prepared statement reuse.
  await expect(pair.personal.batch([pair.catalog.prepare('SELECT 1')]))
   .rejects.toThrow('M50_FOREIGN_PREPARED_STATEMENT');
 }finally{await mf.dispose();}
});
