// M49 detached trusted coordinator HTTP client: NEVER imported by the Worker.
// This module stages independently generated v2 packets; it does NOT grant
// provenance, promotion, PERSONAL access, or remote execution authorization.
// Nothing invokes it until Gate B is separately approved.
import {canonical,sha256} from '../shared/canonical';
import {validateCatalogV2Run,validateCatalogV2Chunk}
 from '../shared/model-c-ingestion-v2';
import type {CatalogV2Run,CatalogV2Chunk} from '../shared/model-c-ingestion-v2';

type Transport=(request:Request)=>Promise<Response>;
type Options={
 endpoint:string;serviceJwt:string;transport:Transport;
 gateBApproved:boolean;
};
type Packet={run:CatalogV2Run;chunks:CatalogV2Chunk[]};
type Receipt={chunk_index:number;chunk_digest:string;idempotency_key:string;record_count:number};
type Status={status:string;complete?:boolean;received?:number;expected?:number;
  receipts?:Receipt[];receiptsTruncated?:boolean;missing?:number[];missingTruncated?:boolean};
const missing=(code:string):never=>{throw Error(code);};
function origin(input:string){
 let url:URL;
 try{url=new URL(input);}catch{return missing('M49_INVALID_TARGET');}
 if(url.protocol!=='https:'||!url.hostname.includes('.')||url.hostname.endsWith('.workers.dev')||
   url.username||url.password||url.port||url.pathname!=='/'||url.search||url.hash)
   return missing('M49_INVALID_TARGET');
 return url.origin;
}
async function packetProof(packet:Packet){
 const run=await validateCatalogV2Run(packet.run);
 if(run.totalChunks>512||run.recordCount>20000||
    packet.chunks.length!==run.totalChunks)return missing('M49_INVALID_PACKET_COUNT');
 const checked=await Promise.all(packet.chunks.map(validateCatalogV2Chunk));
 checked.sort((a,b)=>a.index-b.index);
 if(checked.some((c,i)=>c.index!==i||c.runId!==run.runId||
    c.totalChunks!==run.totalChunks))
   return missing('M49_INVALID_CHUNK_INDEX');
 const records=checked.flatMap(c=>c.records);
 if(records.length!==run.recordCount||
    await sha256(canonical(records))!==run.inventoryDigest)
   return missing('M49_INVENTORY_DIGEST_MISMATCH');
 return {run,chunks:checked};
}
/** No retry loop: uncertain writes are read back using durable receipts.
 * Staging does not promote/verify provenance; only the trusted Git importer can.
 */
export async function stageCheckedV2Packets(packet:Packet,opts:Options){
 if(opts.gateBApproved!==true)return missing('M49_GATE_B_CLOSED');
 const target=origin(opts.endpoint);
 if(!opts.serviceJwt||opts.serviceJwt.length>8192||opts.serviceJwt.split('.').length!==3)
   return missing('M49_SERVICE_TOKEN_REQUIRED');
 const {run,chunks}=await packetProof(packet);
 const base=target+'/api/model-c/sync/v2/runs';
 async function send(path:string,method:'GET'|'POST',body?:unknown){
  let result:Response;
  try{
   result=await opts.transport(new Request(path,{
    method,headers:{
     'cf-access-jwt-assertion':opts.serviceJwt,
     ...(body===undefined?{}:{'content-type':'application/json'}),
    },...(body===undefined?{}:{body:JSON.stringify(body)}),
   }));
  }catch{return missing('M49_TRANSPORT_OUTCOME_UNKNOWN');}
  let data:Status;
  try{data=await result.json() as Status;}
  catch{return missing('M49_INVALID_RECEIPT');}
  return {code:result.status,data};
 }
 const path=base+'/'+run.runId;
 const fetchState=async()=>{
  const result=await send(path+'/status','GET');
  if(result.code!==200)return missing('M49_STATUS_READBACK_FAILED');
  if(result.data.expected!==run.totalChunks||
     !Array.isArray(result.data.receipts)||
     result.data.receiptsTruncated===true)
    return missing('M49_UNVERIFIED_STATUS');
  const byIndex=new Map<number,Receipt>();
  for(const r of result.data.receipts){
   if(!Number.isInteger(r.chunk_index)||r.chunk_index<0||r.chunk_index>=run.totalChunks||
      byIndex.has(r.chunk_index))return missing('M49_INVALID_RECEIPT');
   const expected=chunks[r.chunk_index]!;
   if(r.chunk_digest!==expected.digest||r.idempotency_key!==expected.idempotencyKey||
      r.record_count!==expected.count)return missing('M49_RECEIPT_CONFLICT');
   byIndex.set(r.chunk_index,r);
  }
  return {state:result.data,byIndex};
 };
 const create=await send(base,'POST',run);
 if(create.code!==200&&create.code!==201){
  if(create.code!==503)return missing('M49_RUN_REFUSED');
  // A failed/lost acknowledgement is NOT a signal to resubmit the write.
  await fetchState();
 }
 let state=await fetchState();
 for(const chunk of chunks){
  if(state.byIndex.has(chunk.index))continue;
  const result=await send(path+'/chunks','POST',chunk);
  if(result.code!==200&&result.code!==201){
   if(result.code!==503)return missing('M49_CHUNK_REFUSED');
   // A 503 may have committed: only durable readback can prove it.
   state=await fetchState();
   if(!state.byIndex.has(chunk.index))return missing('M49_CHUNK_OUTCOME_UNKNOWN');
  }else{
   state=await fetchState();
   if(!state.byIndex.has(chunk.index))return missing('M49_CHUNK_RECEIPT_MISSING');
  }
 }
 state=await fetchState();
 if(!state.state.complete||state.byIndex.size!==run.totalChunks||
    state.state.received!==run.totalChunks)return missing('M49_INCOMPLETE');
 return {status:'STAGED_NOT_PUBLISHED' as const,runId:run.runId,
  received:run.totalChunks,publicationAuthorized:false as const};
}
