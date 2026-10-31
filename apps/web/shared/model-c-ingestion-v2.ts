// M47 v2: complete owner-neutral CATALOG inventory contract.
// It intentionally excludes source 'user'/'semantic' events, personal
// assessments and decisions: service principal catalog:stage must NOT have
// access to PERSONAL source data or apply those events to PERSONAL D1.
// Offline only; no Worker ingress, D1 stage or cloud authorization exists.
import {z} from 'zod';
import {canonical,sha256} from './canonical';
import {bundleSchema,validateBundle} from './snapshot';
import type {SnapshotBundle} from './snapshot';
import {identityLedgerSchema} from './model-c-selection';
import type {selectModelC} from './model-c-selection';
import {projectionProofSchema} from './projection-proof';
const sha=z.string().regex(/^[a-f0-9]{64}$/);
const gitSha=z.string().regex(/^[a-f0-9]{40}$/);
const text=z.string().max(2200);
const url=z.string().url().startsWith('https://').nullable();
const origin={sourcePath:z.string().max(240),sourceSha256:sha};
const company=z.strictObject({
 kind:z.literal('company'),id:text,name:text,configId:text.nullable(),
 tier:text.nullable(),priority:text.nullable(),careerUrl:url,
 membership:z.enum(['ACTIVE','CANDIDATE','HISTORICAL']),...origin,
});
const source=z.strictObject({
 kind:z.literal('source'),id:text,companyId:text,sourceKey:text,
 family:text,inventoryUrl:url,
 coverage:z.enum(['VERIFIED','PARTIAL','FAILED','NOT_CHECKED']).nullable(),
 generatedAt:text.nullable(),coveragePath:text,coverageSha256:sha,...origin,
});
const job=z.strictObject({
 kind:z.literal('job'),jobId:z.string().regex(/^job:[a-f0-9]{64}$/),
 companyId:text,sourceId:text.nullable(),jobKey:text,aliases:z.array(text),
 selectedKind:z.enum(['OPPORTUNITY','AI_QUEUE']).nullable(),
 batch:z.enum(['jw1','jw2','jw3','jw4']).nullable(),
 title:text.nullable(),location:text.nullable(),canonicalUrl:url,applyUrl:url,
 fingerprint:text.nullable(),lifecycle:z.enum(['NEW','STILL_OPEN','UPDATED','CLOSED','UNKNOWN']),
 firstSeenAt:text.nullable(),lastSeenAt:text.nullable(),
 workerEligible:z.boolean().nullable(),technicalStatus:text.nullable(),
 ...origin,
});
const identity=z.strictObject({
 kind:z.literal('identity'),jobId:z.string().regex(/^job:[a-f0-9]{64}$/),
 companyId:text,originJobKey:text,
});
const alias=z.strictObject({
 kind:z.literal('alias'),key:text,jobId:z.string().regex(/^job:[a-f0-9]{64}$/),
});
export const catalogV2Record=z.discriminatedUnion('kind',[company,source,job,identity,alias]);
export type CatalogV2Record=z.infer<typeof catalogV2Record>;
export const CATALOG_V2_CONTRACT='job-watch-model-c-ingestion/2' as const;
const meta=z.strictObject({
 commitSha:gitSha,manifestDigest:sha,projectionDigest:sha,
 ledgerDigest:sha,catalogContentDigest:sha,planDigest:sha,
 expectedRevision:z.number().int().nonnegative(),
 schemaVersion:z.literal(6),
});
const run=z.strictObject({
 contract:z.literal(CATALOG_V2_CONTRACT),scope:z.literal('CATALOG'),
 runId:z.string().regex(/^ingest-v2:[a-f0-9]{64}$/),
 ...meta.shape,totalChunks:z.number().int().positive().max(100000),
 recordCount:z.number().int().positive(),
 inventoryDigest:sha,
});
const chunk=z.strictObject({
 contract:z.literal(CATALOG_V2_CONTRACT),scope:z.literal('CATALOG'),
 runId:run.shape.runId,index:z.number().int().nonnegative(),
 count:z.number().int().positive().max(40),
 totalChunks:run.shape.totalChunks,digest:sha,idempotencyKey:sha,
 records:z.array(catalogV2Record).min(1).max(40),
});
export type CatalogV2Run=z.infer<typeof run>;
export type CatalogV2Chunk=z.infer<typeof chunk>;
type Selected=Awaited<ReturnType<typeof selectModelC>>;
const catalogRecordKey=(r:CatalogV2Record)=>
  r.kind==='alias'?'alias:'+r.key:
  r.kind==='identity'?'identity:'+r.jobId:
  r.kind==='job'?'job:'+r.jobId:r.kind+':'+r.id;
const sortRecords=(records:CatalogV2Record[])=>[...records].sort((a,b)=>
  catalogRecordKey(a).localeCompare(catalogRecordKey(b)));
/** FULL owner-neutral catalog records: no selection facts or PERSONAL payload. */
export function projectCatalogV2(bundle:SnapshotBundle,selected:Selected){
  const valid=bundleSchema.parse(bundle);
  const rows:CatalogV2Record[]=[];
  const byKey=new Map(selected.ledger.mappings.map(x=>[x.key,x.jobId]));
  const selectedKinds=new Map(selected.catalog.map(x=>[x.jobId,x.kind]));
  for(const row of valid.chunks.flat()){
    if(row.kind==='company'||row.kind==='source'){
      rows.push(catalogV2Record.parse(row));
    }else if(row.kind==='job'){
      const jobId=byKey.get(row.jobKey);
      if(!jobId)throw Error('V2_UNRESOLVED_JOB_ID');
      rows.push(catalogV2Record.parse({
        kind:'job',jobId,companyId:row.companyId,sourceId:row.sourceId,
        jobKey:row.jobKey,aliases:row.aliases,
        selectedKind:selectedKinds.get(jobId)??null,
        batch:row.batch,title:row.title,location:row.location,
        canonicalUrl:row.canonicalUrl,applyUrl:row.applyUrl,
        fingerprint:row.fingerprint,lifecycle:row.lifecycle,
        firstSeenAt:row.firstSeenAt,lastSeenAt:row.lastSeenAt,
        workerEligible:row.workerEligible,technicalStatus:row.technicalStatus,
        sourcePath:row.sourcePath,sourceSha256:row.sourceSha256,
      }));
    }
  }
  for(const x of selected.ledger.identities)rows.push(catalogV2Record.parse({kind:'identity',...x}));
  for(const x of selected.ledger.mappings)rows.push(catalogV2Record.parse({kind:'alias',...x}));
  const ordered=sortRecords(rows),keys=new Set<string>();
  for(const row of ordered){
    const key=canonical(row);
    if(keys.has(key))throw Error('V2_DUPLICATE_RECORD');
    keys.add(key);
  }
  return ordered;
}
/** Deterministic multipacket builder; the supplied proof is ONLY a claim
 * until the trusted Git adapter independently replays and verifies its bytes.
 * 48 KiB packet cap is conservative OFFLINE; remote Free limits unverified.
 */
export async function prepareCatalogV2Packets(
  bundle:SnapshotBundle,selected:Selected,claimedProof:unknown,planDigest:string,
  expectedRevision:number,
){
  await validateBundle(bundle);
  const proof=projectionProofSchema.parse(claimedProof);
  if(!sha.safeParse(planDigest).success||!Number.isSafeInteger(expectedRevision)||
    expectedRevision<0)throw Error('V2_INVALID_PLAN');
  if(proof.observedGitCommit!==bundle.manifest.commitSha||
     proof.sourceManifestDigest!==await sha256(canonical(bundle.manifest))||
     selected.ledgerDigest!==await sha256(canonical(identityLedgerSchema.parse(selected.ledger))))
    throw Error('V2_PROOF_OR_LEDGER_MISMATCH');
  const records=projectCatalogV2(bundle,selected);
  const inventoryDigest=await sha256(canonical(records));
  const pieces:CatalogV2Record[][]=[];let current:CatalogV2Record[]=[];
  for(const item of records){
    if(new TextEncoder().encode(canonical([item])).byteLength>48*1024)
      throw Error('V2_SINGLE_RECORD_TOO_LARGE');
    if(current.length>=40||
      new TextEncoder().encode(canonical([...current,item])).byteLength>48*1024){
      pieces.push(current);current=[];
    }
    current.push(item);
  }
  if(current.length)pieces.push(current);
  if(pieces.length===0||pieces.length>100000)throw Error('V2_PACKET_COUNT_UNSUPPORTED');
  const base={contract:CATALOG_V2_CONTRACT,scope:'CATALOG' as const,
    commitSha:proof.observedGitCommit,manifestDigest:proof.sourceManifestDigest,
    projectionDigest:proof.projectionInputDigest,
    ledgerDigest:selected.ledgerDigest,catalogContentDigest:selected.catalogContentDigest,
    planDigest,expectedRevision,schemaVersion:6 as const,
    totalChunks:pieces.length,recordCount:records.length,inventoryDigest};
  const runId='ingest-v2:'+await sha256(canonical(base));
  const descriptor=run.parse({...base,runId});
  const chunks:CatalogV2Chunk[]=[];
  for(let i=0;i<pieces.length;i++){
    const items=pieces[i]!,digest=await sha256(canonical(items));
    const idempotencyKey=await sha256(canonical({runId,index:i,digest}));
    chunks.push(chunk.parse({contract:CATALOG_V2_CONTRACT,scope:'CATALOG',
      runId,index:i,count:items.length,totalChunks:pieces.length,
      digest,idempotencyKey,records:items}));
  }
  return {run:descriptor,chunks,packetDigest:await sha256(canonical({
    run:descriptor,chunkDigests:chunks.map(c=>c.digest)})),
    remoteExecutionAuthorized:false as const};
}
/** Received v2 packets are untrusted. A trusted caller must independently
 * verify Git ancestry, selection and plan first; this compares against that
 * FULL independently computed catalog inventory, NOT client digest claims.
 */
export async function verifyCatalogV2AgainstTrusted(
  supplied:unknown,expected:Awaited<ReturnType<typeof prepareCatalogV2Packets>>,
){
  if(!supplied||typeof supplied!=='object')throw Error('V2_INVALID_INVENTORY');
  const data=supplied as Record<string,unknown>;
  const observedRun=run.parse(data.run);
  const observedChunks=z.array(chunk).parse(data.chunks);
  if(observedChunks.length!==observedRun.totalChunks||
     observedChunks.reduce((n,c)=>n+c.records.length,0)!==observedRun.recordCount)
    throw Error('V2_INCOMPLETE_CHUNKS');
  const indexes=new Set<number>();
  for(const p of observedChunks){
    if(indexes.has(p.index)||p.index>=observedRun.totalChunks||p.totalChunks!==observedRun.totalChunks||
       p.runId!==observedRun.runId||p.count!==p.records.length||
       p.digest!==await sha256(canonical(p.records))||
       p.idempotencyKey!==await sha256(canonical({runId:p.runId,index:p.index,digest:p.digest})))
      throw Error('V2_CHUNK_PROOF_MISMATCH');
    indexes.add(p.index);
  }
  const ordered=[...observedChunks].sort((a,b)=>a.index-b.index);
  const inventory=ordered.flatMap(p=>p.records);
  if(await sha256(canonical(inventory))!==observedRun.inventoryDigest)
    throw Error('V2_INVENTORY_DIGEST_MISMATCH');
  if(canonical({run:observedRun,chunks:ordered})!==canonical({
    run:expected.run,chunks:expected.chunks}))
    throw Error('V2_TRUSTED_PROJECTION_MISMATCH');
  return {status:'V2_TRUSTED_INVENTORY_MATCH' as const,
    inventoryDigest:observedRun.inventoryDigest,
    fullCatalogProjectionVerified:true as const,
    personalDataTransmitted:false as const,
    publicationAuthorized:false as const};
}
