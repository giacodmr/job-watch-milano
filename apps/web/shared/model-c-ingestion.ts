// Deterministic, strict ingestion wire contract; zero SQL, owner IDs or secrets.
import {z} from 'zod';
import {canonical,sha256} from './canonical';
export const INGESTION_CONTRACT='job-watch-model-c-ingestion/1' as const;
const sha=z.string().regex(/^[a-f0-9]{64}$/);
const commit=z.string().regex(/^[a-f0-9]{40}$/);
const entity=z.string().regex(/^[a-z0-9][a-z0-9:_-]{0,130}$/);
const jobId=z.string().regex(/^job:[a-f0-9]{64}$/);
const nullableUrl=z.string().url().max(1500).startsWith('https://').nullable();
const company=z.strictObject({kind:z.literal('company'),id:entity,
  name:z.string().min(1).max(300),careerUrl:nullableUrl});
const source=z.strictObject({kind:z.literal('source'),id:entity,companyId:entity,
  atsFamily:z.string().min(1).max(80),inventoryUrl:nullableUrl});
const job=z.strictObject({kind:z.literal('job'),id:jobId,companyId:entity,
  sourceId:entity.nullable(),title:z.string().min(1).max(500),
  location:z.string().max(300).nullable(),
  lifecycle:z.enum(['NEW','STILL_OPEN','UPDATED']),
  officialUrl:nullableUrl,fingerprint:sha.nullable()});
export const ingestRecord=z.discriminatedUnion('kind',[company,source,job]);
export type IngestRecord=z.infer<typeof ingestRecord>;
export const runInput=z.strictObject({
  contract:z.literal(INGESTION_CONTRACT),scope:z.literal('CATALOG'),
  runId:z.string().regex(/^ingest:[a-f0-9]{64}$/),
  commitSha:commit,manifestDigest:sha,projectionDigest:sha,planDigest:sha,
  expectedRevision:z.number().int().nonnegative().max(1e9),
  schemaVersion:z.literal(5),totalChunks:z.number().int().min(1).max(64),
});
export type IngestRunInput=z.infer<typeof runInput>;
export const chunkInput=z.strictObject({
  contract:z.literal(INGESTION_CONTRACT),scope:z.literal('CATALOG'),
  runId:runInput.shape.runId,chunkIndex:z.number().int().min(0).max(63),
  totalChunks:runInput.shape.totalChunks,chunkDigest:sha,idempotencyKey:sha,
  records:z.array(ingestRecord).min(1).max(16),
});
export type IngestChunkInput=z.infer<typeof chunkInput>;
export const MAX_INGEST_REQUEST_BYTES=12*1024;
export async function expectedRunId(input:Omit<IngestRunInput,'runId'>){
  return 'ingest:'+await sha256(canonical(input));
}
export async function expectedChunkDigest(records:IngestRecord[]){
  return sha256(canonical(records));
}
export async function expectedIdempotencyKey(runId:string,chunkIndex:number,chunkDigest:string){
  return sha256(canonical({runId,chunkIndex,chunkDigest}));
}
export async function validateRun(input:unknown){
  const run=runInput.parse(input);
  const {runId,...parts}=run;
  if(runId!==await expectedRunId(parts))throw Error('INGEST_RUN_DIGEST_INVALID');
  return run;
}
export async function validateChunk(input:unknown){
  const chunk=chunkInput.parse(input);
  if(chunk.chunkIndex>=chunk.totalChunks)throw Error('INGEST_CHUNK_INDEX_INVALID');
  if(chunk.chunkDigest!==await expectedChunkDigest(chunk.records)||
    chunk.idempotencyKey!==await expectedIdempotencyKey(chunk.runId,chunk.chunkIndex,chunk.chunkDigest))
    throw Error('INGEST_CHUNK_DIGEST_INVALID');
  return chunk;
}
