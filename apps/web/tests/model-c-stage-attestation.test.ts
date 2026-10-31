import {afterAll,beforeAll,describe,expect,it} from 'vitest';
import {Miniflare,convertV4MiniflareOptions} from 'miniflare';
import {applySchema} from '../tools/model-c-schema';
import {canonical,sha256} from '../shared/canonical';
import {prepareOfflineIngestPackets} from '../tools/model-c-ingest-offline-client';
import {auditReceivedIngestStage,StageAuditError} from '../tools/model-c-stage-attestation';
import {advanceCompleteIngestJournal,advanceIngestJournal,observeIngestJournal} from '../tools/model-c-publication-journal';

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

describe('M47 immutable D1 publication journal',()=>{
  it('backstops each M46 run with a durable RECEIVING event, then validates complete and verified evidence',async()=>{
    const p=await packets();
    await stageRun(p);
    let current=await observeIngestJournal(db,p.run.runId);
    expect(current).toMatchObject({phase:'RECEIVING',sequence:0});
    await expect(advanceCompleteIngestJournal(db,p.run.runId))
      .rejects.toMatchObject({code:'INCOMPLETE_CHUNKS'});
    await stageChunk(p,0);await stageChunk(p,1);
    current=await advanceCompleteIngestJournal(db,p.run.runId);
    expect(current).toMatchObject({phase:'COMPLETE',sequence:1});
    expect((await advanceCompleteIngestJournal(db,p.run.runId)).sequence).toBe(1);
    await expect(advanceIngestJournal(db,p.run.runId,'CATALOG_PUBLISHED','a'.repeat(64)))
      .rejects.toMatchObject({code:'JOURNAL_INVALID_TRANSITION'});
    current=await advanceIngestJournal(db,p.run.runId,'VERIFIED','b'.repeat(64));
    expect(current).toMatchObject({phase:'VERIFIED',sequence:2});
    await expect(advanceIngestJournal(db,p.run.runId,'VERIFIED','c'.repeat(64)))
      .rejects.toMatchObject({code:'JOURNAL_REPLAY_CONFLICT'});
    await expect(db.prepare("UPDATE catalog_ingest_journal SET phase='COMPLETED' WHERE run_id=?")
      .bind(p.run.runId).run()).rejects.toThrow('immutable_ingest_journal');
    await expect(db.prepare('DELETE FROM catalog_ingest_journal WHERE run_id=?')
      .bind(p.run.runId).run()).rejects.toThrow('retained_ingest_journal');
    expect((await observeIngestJournal(db,p.run.runId)).events.map(x=>x.phase))
      .toEqual(['RECEIVING','COMPLETE','VERIFIED']);
  });
  it('rejects a fabricated event digest or a forged sequence, using real SQLite constraints',async()=>{
    const p=await packets([company],1);
    await stageRun(p);await stageChunk(p,0);
    const current=await advanceCompleteIngestJournal(db,p.run.runId);
    const bad=db.prepare(`INSERT INTO catalog_ingest_journal
      (run_id,sequence,phase,proof_digest,previous_digest,event_digest)
      VALUES (?,?,?,?,?,?)`);
    await expect(bad.bind(p.run.runId,5,'VERIFIED',
      'b'.repeat(64),current.eventDigest,'e'.repeat(64)).run())
      .rejects.toThrow('journal_chain_conflict');
    await bad.bind(p.run.runId,2,'VERIFIED','b'.repeat(64),
      current.eventDigest,'e'.repeat(64)).run();
    await expect(observeIngestJournal(db,p.run.runId))
      .rejects.toMatchObject({code:'JOURNAL_DIGEST_MISMATCH'});
  });
});
