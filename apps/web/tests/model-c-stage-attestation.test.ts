import {afterAll,beforeAll,describe,expect,it} from 'vitest';
import {Miniflare,convertV4MiniflareOptions} from 'miniflare';
import {applySchema} from '../tools/model-c-schema';
import {canonical,sha256} from '../shared/canonical';
import {prepareOfflineIngestPackets} from '../tools/model-c-ingest-offline-client';
import {auditReceivedIngestStage,StageAuditError} from '../tools/model-c-stage-attestation';

let runtime:Miniflare,db:D1Database,sequence=0;
const company={kind:'company' as const,id:'company:test',name:'Synthetic Company',
  careerUrl:'https://example.test/careers'};
const source={kind:'source' as const,id:'source:test',companyId:'company:test',
  atsFamily:'synthetic',inventoryUrl:'https://example.test/jobs'};
const job={kind:'job' as const,id:'job:'+'a'.repeat(64),companyId:'company:test',
  sourceId:'source:test',title:'Analyst',location:'Milano',
  lifecycle:'NEW' as const,officialUrl:'https://example.test/job',fingerprint:null};
const packets=async(records:unknown[]=[company,source,job],chunkSize=2)=>
  prepareOfflineIngestPackets({commitSha:'a'.repeat(40),
    manifestDigest:'b'.repeat(64),projectionDigest:'c'.repeat(64),
    planDigest:(++sequence).toString(16).padStart(64,'0'),
    expectedRevision:0},records,chunkSize);
type Packet=Awaited<ReturnType<typeof packets>>;
async function stageRun(p:Packet){
  await db.prepare(`INSERT INTO catalog_ingest_runs
    (id,commit_sha,manifest_digest,projection_digest,plan_digest,expected_revision,
    total_chunks,principal_digest,run_digest)
    VALUES (?,?,?,?,?,?,?,?,?)`).bind(
      p.run.runId,p.run.commitSha,p.run.manifestDigest,p.run.projectionDigest,
      p.run.planDigest,p.run.expectedRevision,p.run.totalChunks,
      'd'.repeat(64),await sha256(canonical(p.run))).run();
}
async function stageChunk(p:Packet,index:number,overrides:Record<string,unknown>={}){
  const c=p.chunks[index]!;
  await db.prepare(`INSERT INTO catalog_ingest_chunks
    (run_id,chunk_index,chunk_digest,idempotency_key,record_count,records_json)
    VALUES (?,?,?,?,?,?)`).bind(
      c.runId,c.chunkIndex,c.chunkDigest,c.idempotencyKey,
      overrides.count??c.records.length,overrides.json??canonical(c.records)).run();
}
beforeAll(async()=>{
  runtime=new Miniflare(convertV4MiniflareOptions({
    modules:true,cf:false,compatibilityDate:'2026-10-29',
    script:'export default {fetch(){return new Response("offline")}}',
    d1Databases:{CATALOG:'m47-stage-audit'},
  }));
  db=await runtime.getD1Database('CATALOG');
  expect((await applySchema(db,'catalog')).applied).toBe(6);
});
afterAll(async()=>{await runtime?.dispose();});
const rejected=async(p:Packet,code:string)=>
  expect(auditReceivedIngestStage(db,p.run.runId))
    .rejects.toMatchObject({code} satisfies Partial<StageAuditError>);
describe('M47 durable staging receipt integrity (still NOT publication)',()=>{
  it('verifies canonical persisted payload and checksum without changing the catalog head',async()=>{
    const p=await packets();
    await stageRun(p);
    await stageChunk(p,0);await stageChunk(p,1);
    const audit=await auditReceivedIngestStage(db,p.run.runId);
    expect(audit).toMatchObject({status:'PACKET_INTEGRITY_VERIFIED_ONLY',
      receivedChunks:2,recordCount:3,gitProvenanceVerified:false,
      fullCatalogProjectionVerified:false,publicationAuthorized:false});
    expect(await db.prepare('SELECT count(*) AS n FROM catalog_head').first('n')).toBe(0);
    expect(await db.prepare('SELECT count(*) AS n FROM catalog_vacancy_current').first('n')).toBe(0);
    expect(await auditReceivedIngestStage(db,p.run.runId)).toEqual(audit);
  });
  it('refuses missing chunks and never infers completion from receiving state',async()=>{
    const p=await packets();
    await stageRun(p);await stageChunk(p,0);
    await rejected(p,'INCOMPLETE_CHUNKS');
  });
  it('refuses a poisoned persisted JSON payload even if the stored digest looks valid',async()=>{
    const p=await packets([company,source,job],3);
    await stageRun(p);
    await stageChunk(p,0,{json:canonical([company,source,{...job,title:'Tampered'}])});
    await rejected(p,'CHUNK_RECEIPT_INVALID');
  });
  it('refuses repeated identities across otherwise valid chunks',async()=>{
    const p=await packets([company,source,{...job},{...job}],2);
    await stageRun(p);await stageChunk(p,0);await stageChunk(p,1);
    await rejected(p,'DUPLICATE_RECORD');
  });
  it('refuses orphan jobs and sources even when their individual packet digests pass',async()=>{
    const p=await packets([job],1);
    await stageRun(p);await stageChunk(p,0);
    await rejected(p,'UNKNOWN_JOB_SOURCE');
  });
  it('does not report a nonexistent run as verified',async()=>{
    await expect(auditReceivedIngestStage(db,'ingest:'+'f'.repeat(64)))
      .rejects.toMatchObject({code:'RUN_NOT_FOUND'});
  });
});
