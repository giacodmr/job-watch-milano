// M46 offline packet builder. No network transport, Cloudflare token or URL input.
import {canonical,sha256} from '../shared/canonical';
import {INGESTION_CONTRACT,ingestRecord,runInput,chunkInput,
  expectedRunId,expectedChunkDigest,expectedIdempotencyKey} from '../shared/model-c-ingestion';
import type {IngestRecord,IngestRunInput,IngestChunkInput} from '../shared/model-c-ingestion';
import {z} from 'zod';
const sha=z.string().regex(/^[a-f0-9]{64}$/);
const metadata=z.strictObject({
  commitSha:z.string().regex(/^[a-f0-9]{40}$/),
  manifestDigest:sha,projectionDigest:sha,planDigest:sha,
  expectedRevision:z.number().int().nonnegative().max(1e9),
});
export async function prepareOfflineIngestPackets(meta:unknown,records:unknown,
  chunkSize=8){
  const m=metadata.parse(meta);
  if(!Number.isSafeInteger(chunkSize)||chunkSize<1||chunkSize>16)
    throw Error('INVALID_CHUNK_SIZE');
  const valid=z.array(ingestRecord).min(1).max(1024).parse(records);
  const chunks:IngestRecord[][]=[];
  for(let i=0;i<valid.length;i+=chunkSize)chunks.push(valid.slice(i,i+chunkSize));
  if(chunks.length>64)throw Error('TOO_MANY_CHUNKS');
  // Do not assume a source digest independently proves Git provenance.
  const parts={
    contract:INGESTION_CONTRACT,scope:'CATALOG' as const,
    ...m,schemaVersion:5 as const,totalChunks:chunks.length,
  };
  const run=runInput.parse({...parts,runId:await expectedRunId(parts)});
  const packets:IngestChunkInput[]=[];
  for(const [chunkIndex,items] of chunks.entries()){
    const chunkDigest=await expectedChunkDigest(items);
    packets.push(chunkInput.parse({
      contract:INGESTION_CONTRACT,scope:'CATALOG',runId:run.runId,
      chunkIndex,totalChunks:run.totalChunks,chunkDigest,
      idempotencyKey:await expectedIdempotencyKey(run.runId,chunkIndex,chunkDigest),
      records:items,
    }));
  }
  // Test transport consumes these packets. No fetch(), endpoint or auth header
  // is constructed by this module; a real client requires separate Gate B.
  return {run:run as IngestRunInput,chunks:packets,
    packetDigest:await sha256(canonical({run,chunkDigests:packets.map(p=>p.chunkDigest)}))};
}
export type OfflineHttpDispatcher=(request:Request)=>Promise<Response>;
export async function submitOfflinePackets(
  packets:Awaited<ReturnType<typeof prepareOfflineIngestPackets>>,
  dispatch:OfflineHttpDispatcher,token:string,
){
  const base='https://sync.synthetic.invalid/api/model-c/sync/runs';
  const headers={'cf-access-jwt-assertion':token,'content-type':'application/json'};
  const send=(path:string,method:string,body?:unknown)=>dispatch(new Request(path,{
    method,headers:body===undefined?{'cf-access-jwt-assertion':token}:headers,
    ...(body===undefined?{}:{body:canonical(body)}),
  }));
  const first=await send(base,'POST',packets.run);
  if(![200,201].includes(first.status))return {status:'BLOCKED',code:first.status};
  for(const chunk of packets.chunks){
    const url=base+'/'+packets.run.runId+'/chunks';
    let result:Response;
    try{result=await send(url,'POST',chunk);}
    catch{return {status:'OUTCOME_UNKNOWN',next:'INSPECT_RECEIPTS'};}
    if(![200,201].includes(result.status)){
      // No blind resubmission: read the durable receipt and compare its digest.
      const check=await send(base+'/'+packets.run.runId+'/status','GET');
      if(check.status!==200)return {status:'OUTCOME_UNKNOWN',next:'INSPECT_RECEIPTS'};
      const observed=await check.json() as {receipts:Array<{chunk_index:number;chunk_digest:string}>};
      if(!observed.receipts.some(c=>c.chunk_index===chunk.chunkIndex&&
        c.chunk_digest===chunk.chunkDigest))
        return {status:'BLOCKED',code:result.status};
    }
  }
  const final=await send(base+'/'+packets.run.runId+'/status','GET');
  if(final.status!==200)return {status:'OUTCOME_UNKNOWN',next:'INSPECT_RECEIPTS'};
  const state=await final.json() as {complete:boolean};
  return {status:state.complete?'STAGED_NOT_PUBLISHED':'INCOMPLETE',runId:packets.run.runId};
}
