// Offline transport contract. NOT an HTTP adapter, Worker route, D1 REST client
// or permission to write Cloudflare. The only executable adapter is local-ephemeral.
export type SqlValue=string|number|null;
export type SqlStep={sql:string;values:readonly SqlValue[]};
export type TransportScope='CATALOG'|'PERSONAL';
export type TransportTarget='local-ephemeral'|'remote';
const MAX_PARAMS=80,MAX_SQL_BYTES=64*1024,MAX_BATCH_BYTES=8*1024*1024,MAX_STEPS=8000;
const bytes=(s:string)=>Buffer.byteLength(s,'utf8');

export function inspectOfflineBatch(steps:readonly SqlStep[]){
  if(!Array.isArray(steps)||steps.length===0||steps.length>MAX_STEPS)
    throw Error('BATCH_CONTRACT_INVALID');
  let totalBytes=0,maxSqlBytes=0,totalParameters=0;
  for(const step of steps){
    if(typeof step.sql!=='string'||!Array.isArray(step.values)||
      step.values.length>MAX_PARAMS||step.values.some((v:SqlValue)=>v!==null&&
        (typeof v!=='string'&&typeof v!=='number'||typeof v==='number'&&!Number.isFinite(v))))
      throw Error('BATCH_CONTRACT_INVALID');
    const size=bytes(step.sql);
    if(!size||size>MAX_SQL_BYTES)throw Error('D1_SQL_LIMIT');
    maxSqlBytes=Math.max(maxSqlBytes,size);totalParameters+=step.values.length;
    totalBytes+=size+bytes(JSON.stringify(step.values));
    if(totalBytes>MAX_BATCH_BYTES)throw Error('D1_BATCH_REVIEW_LIMIT');
  }
  return {statements:steps.length,bytes:totalBytes,totalParameters,maxSqlBytes,
    maxParameters:Math.max(...steps.map(s=>s.values.length))};
}

/** Remote writes fail *before* touching bindings or attempting a network call. */
export function rejectRemoteTransport(target:TransportTarget):void{
  if(target!=='local-ephemeral')throw Error('REMOTE_EXECUTION_NOT_AUTHORIZED');
}
export async function executeEphemeralAtomicBatch(
  db:D1Database,scope:TransportScope,target:TransportTarget,steps:readonly SqlStep[],
){
  rejectRemoteTransport(target);
  inspectOfflineBatch(steps);
  const version=scope==='CATALOG'?7:3;
  const observed=await db.prepare('SELECT version FROM model_c_schema WHERE scope=?')
    .bind(scope).first<number>('version');
  if(observed!==version)throw Error('WRONG_DATABASE_SCOPE');
  // Cloudflare documents D1Database.batch as one SQLite transaction for ONE DB.
  // This call makes no guarantees across CATALOG and PERSONAL.
  try{
    return await db.batch(steps.map(s=>db.prepare(s.sql).bind(...s.values)));
  }catch{
    // A lost response can follow a committed batch: do NOT blindly retry.
    throw Error('TRANSPORT_OUTCOME_REQUIRES_CHECKPOINT_INSPECTION');
  }
}
export function classifyUncertainDelivery(ack:'ACKNOWLEDGED'|'FAILED'|'UNKNOWN'){
  if(ack==='UNKNOWN')return 'INSPECT_CHECKPOINT_AND_RECEIPT_BEFORE_RETRY' as const;
  return ack==='FAILED'?'VERIFY_ABORT_OR_COMMIT_BEFORE_RETRY' as const:'VERIFY_RECEIPT' as const;
}
