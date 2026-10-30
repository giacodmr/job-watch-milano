import { describe, expect, it } from 'vitest';
import { spawnSync } from 'node:child_process';
import { canonical, sha256 } from '../shared/canonical';
import { prepareBundle, requiredFiles } from '../shared/snapshot';
import type { SnapshotRow } from '../shared/snapshot';
import { selectModelC, selectionContract, selectionContextDigest } from '../shared/model-c-selection';
import { canReuseProjection, catalogObservation, createProjectionProof, projectionInputDigest, requiredImplementationPaths, requiredPythonPaths, verifyProjectionProof } from '../shared/projection-proof';
import type { ProjectionInputs } from '../shared/projection-proof';

const stamp = '2026-10-29T10:00:00Z', hash = 'a'.repeat(64);
const bootstrap = { identities: { mode: 'first-v1-bootstrap' as const }, personalReferences: [] };
const job: Extract<SnapshotRow,{kind:'job'}> = {
  kind:'job',jobKey:'Synthetic Company::1',aliases:[],companyId:'company:1',sourceId:null,
  upstreamSourceId:'1',batch:'jw1',title:'Synthetic Analyst',location:'Milan',canonicalUrl:'https://jobs.example.test/1',applyUrl:null,
  fingerprint:'opaque-python-fingerprint',lifecycle:'STILL_OPEN',firstSeenAt:stamp,lastSeenAt:stamp,
  analysisStatus:'ANALYZED',analysisMethod:'chatgpt_semantic_full_jd',needsAnalysis:false,workerEligible:false,
  hardExclusionReason:null,fitScore:80,reportable:true,effectiveDecision:null,technicalStatus:null,sortKey:'synthetic',
  sourcePath:'current_jobs_jw1.json',sourceSha256:hash,
};
async function fixture(jobs = [job], events: Record<string,unknown>[] = [], sha = 'a'.repeat(40)) {
  return prepareBundle({commitSha:sha,observedAt:stamp,
    files:requiredFiles.map(path=>({path,sha256:hash,bytes:1})).sort((a,b)=>a.path.localeCompare(b.path)),
    rows:[{kind:'company',id:'company:1',name:'Synthetic Company',configId:'1',tier:null,priority:null,careerUrl:null,membership:'ACTIVE',sourcePath:'companies_job_watch_v2.json',sourceSha256:hash},
      ...jobs,...events,{kind:'pipeline',runId:null,healthStatus:null,collectionStatus:null,dailyComplete:null,fullSemanticComplete:null,generatedAt:stamp,sourcePath:'job_watch_healthcheck.json',sourceSha256:hash}]});
}
const decision = (key = job.jobKey, choice = 'NOT_INTERESTED') => ({kind:'user',jobKey:key,fingerprint:'older-fingerprint',decision:choice,rejectionReason:null,decidedAt:stamp,hashInput:{decision:choice,decided_at:stamp},sourcePath:'job_memory_jw1.json',sourceSha256:hash});
async function inputs(bundle: Awaited<ReturnType<typeof fixture>>): Promise<ProjectionInputs> {
  const code = (path:string)=>({path,sha256:'b'.repeat(64),bytes:5});
  return {contract:selectionContract,selectionContextDigest:await selectionContextDigest(bootstrap),
    sourceFiles:[...bundle.manifest.files,...requiredPythonPaths.map(code)].sort((a,b)=>a.path<b.path?-1:1),
    implementationFiles:requiredImplementationPaths.map(code).sort((a,b)=>a.path<b.path?-1:1),
    runtime:{node:'synthetic-node',python:'synthetic-python'}};
}

describe('model C selection contract (synthetic data only)',()=>{
  it('leaves the v1 envelope unchanged',async()=>{const b=await fixture(), before=canonical(b);await selectModelC(b,bootstrap);expect(canonical(b)).toBe(before);});
  it('preserves all identities/aliases while excluding useless automatic payloads',async()=>{
    const excluded={...job,jobKey:'Synthetic Company::2',upstreamSourceId:'2',aliases:['Synthetic Company::legacy'],reportable:false,hardExclusionReason:'SYNTHETIC_RULE'};
    const selected=await selectModelC(await fixture([job,excluded]),bootstrap);
    expect(selected.ledger.identities).toHaveLength(2);expect(selected.ledger.mappings).toHaveLength(3);
    expect(selected.catalog).toHaveLength(1);expect(selected.subjects).toHaveLength(1);
  });
  it('preserves every decision observation, deduplicates events and suppresses manual rejects across fingerprints',async()=>{
    const rejected={...job,effectiveDecision:'NOT_INTERESTED' as const,aliases:['Synthetic Company::old']};
    const selected=await selectModelC(await fixture([rejected],[decision(),decision('Synthetic Company::old')]),bootstrap);
    expect(selected.catalog).toHaveLength(0);expect(selected.decisions).toHaveLength(1);
    expect(selected.decisions[0]!.observations).toHaveLength(2);expect(selected.subjects[0]!.exclusion).toBe('MANUAL');
    expect(selected.decisions[0]!.observations[0]!.fingerprint).toBe('older-fingerprint');
    expect(selected.decisions[0]!.eventId).toBe('decision:'+await sha256(selected.subjects[0]!.jobId+'\0'+selected.decisions[0]!.observations[0]!.resultSha256));
  });
  it('uses Python effective precedence instead of sorting historical decisions in JS',async()=>{
    const effective={...job,effectiveDecision:'INTERESTED' as const};
    const selected=await selectModelC(await fixture([effective],[decision(),decision(job.jobKey,'INTERESTED')]),bootstrap);
    expect(selected.decisions).toHaveLength(2);expect(selected.catalog).toHaveLength(1);
    const unresolved=await selectModelC(await fixture([job],[decision()]),bootstrap);
    expect(unresolved.catalog).toHaveLength(0);expect(unresolved.subjects[0]!.exclusion).toBe('UNRESOLVED_PERSONAL');
  });
  it.each(['CLOSED','UNKNOWN'] as const)('preserves personal %s without making it an open opportunity',async lifecycle=>{
    const selected=await selectModelC(await fixture([{...job,lifecycle,effectiveDecision:'INTERESTED'}],[decision(job.jobKey,'INTERESTED')]),bootstrap);
    expect(selected.catalog).toHaveLength(0);expect(selected.subjects[0]!.lifecycle).toBe(lifecycle);
  });
  it('keeps blocked AI as a minimal queue record without inventing a rejection',async()=>{
    const selected=await selectModelC(await fixture([{...job,reportable:null,needsAnalysis:true,workerEligible:false,technicalStatus:'JD_UNAVAILABLE'}]),bootstrap);
    expect(selected.catalog[0]!.kind).toBe('AI_QUEUE');expect(selected.aiQueue[0]!.workerEligible).toBe(false);
    expect(selected.aiQueue[0]).not.toHaveProperty('fitScore');expect(selected.aiQueue[0]).not.toHaveProperty('hardExclusionReason');
  });
  it('carries the complete confirmed ledger through aliases, reopening and absent subjects',async()=>{
    const first=await selectModelC(await fixture([{...job,lifecycle:'CLOSED',effectiveDecision:'NOT_INTERESTED'}],[decision()]),bootstrap);
    const next={...job,jobKey:'Synthetic Company::new',aliases:[job.jobKey],fingerprint:'new-opaque',effectiveDecision:'NOT_INTERESTED' as const};
    const second=await selectModelC(await fixture([next],[decision(job.jobKey)]),{identities:{mode:'confirmed-ledger',ledger:first.ledger,expectedDigest:first.ledgerDigest},personalReferences:[]});
    expect(second.ledger.identities).toEqual(first.ledger.identities);expect(second.ledger.mappings).toHaveLength(2);expect(second.catalog).toHaveLength(0);
    const absent=await selectModelC(await fixture([]),{identities:{mode:'confirmed-ledger',ledger:second.ledger,expectedDigest:second.ledgerDigest},personalReferences:[{jobId:first.ledger.identities[0]!.jobId,kind:'DISMISSED'}]});
    expect(absent.ledger).toEqual(second.ledger);expect(absent.subjects[0]!.lifecycle).toBeNull();expect(absent.catalog).toHaveLength(0);
  });
  it('applies UNRESOLVED_PERSONAL to retained decision presence without inventing an effective choice',async()=>{
    const b=await fixture(), first=await selectModelC(b,bootstrap), jobId=first.ledger.identities[0]!.jobId;
    const context={...bootstrap,personalDecisionJobIds:[jobId]};
    const unresolved=await selectModelC(b,context);
    expect(unresolved.catalog).toHaveLength(0);expect(unresolved.subjects[0]).toMatchObject({personal:true,exclusion:'UNRESOLVED_PERSONAL',lifecycle:'STILL_OPEN'});
    expect(unresolved.decisions).toHaveLength(0);
    const effective=await selectModelC(await fixture([{...job,effectiveDecision:'INTERESTED'}]),context);
    expect(effective.catalog).toHaveLength(1);expect(effective.subjects[0]!.exclusion).toBeNull();
    expect(await selectionContextDigest(context)).not.toBe(await selectionContextDigest(bootstrap));
    await expect(selectModelC(b,{...bootstrap,personalDecisionJobIds:['job:'+'f'.repeat(64)]})).rejects.toThrow('UNRESOLVED_PERSONAL_REFERENCE');
    const absent=await selectModelC(await fixture([]),{identities:{mode:'confirmed-ledger',ledger:first.ledger,expectedDigest:first.ledgerDigest},personalReferences:[],personalDecisionJobIds:[jobId]});
    expect(absent.subjects[0]).toMatchObject({personal:true,exclusion:'UNRESOLVED_PERSONAL',lifecycle:null});
  });
  it('rejects an incomplete ledger against its trusted checkpoint digest',async()=>{
    const first=await selectModelC(await fixture(),bootstrap);
    await expect(selectModelC(await fixture(),{identities:{mode:'confirmed-ledger',ledger:{identities:[],mappings:[]},expectedDigest:first.ledgerDigest},personalReferences:[]})).rejects.toThrow('LEDGER_DIGEST_MISMATCH');
  });
  it('rejects contradictory facts with an identical immutable event hash',async()=>{
    await expect(selectModelC(await fixture([{...job,effectiveDecision:'NOT_INTERESTED'}],[decision(),{...decision(),decision:'INTERESTED'}]),bootstrap)).rejects.toThrow('CONFLICTING_EVENT_FACTS');
  });
  it('protects active personal references independently of an older Python projection',async()=>{
    const bundle=await fixture();const first=await selectModelC(bundle,bootstrap);const jobId=first.ledger.identities[0]!.jobId;
    const selected=await selectModelC(bundle,{identities:{mode:'confirmed-ledger',ledger:first.ledger,expectedDigest:first.ledgerDigest},personalReferences:[{jobId,kind:'DISMISSED'}]});
    expect(selected.catalog).toHaveLength(0);expect(selected.subjects[0]!.exclusion).toBe('MANUAL');
    await expect(selectModelC(bundle,{...bootstrap,personalReferences:[{jobId:'job:'+'f'.repeat(64),kind:'SAVED'}]})).rejects.toThrow('UNRESOLVED_PERSONAL_REFERENCE');
  });
  it('rejects ambiguous or cross-company mappings instead of inventing identity equivalence',async()=>{
    const a=await selectModelC(await fixture([job,{...job,jobKey:'Synthetic Company::2',upstreamSourceId:'2'}]),bootstrap);
    await expect(selectModelC(await fixture([{...job,aliases:['Synthetic Company::2']}]),{identities:{mode:'confirmed-ledger',ledger:a.ledger,expectedDigest:a.ledgerDigest},personalReferences:[]})).rejects.toThrow('AMBIGUOUS_LEDGER_IDENTITY');
    const ledger=structuredClone(a.ledger);ledger.identities[0]!.companyId='company:another';
    await expect(selectModelC(await fixture([job,{...job,jobKey:'Synthetic Company::2',upstreamSourceId:'2'}]),{identities:{mode:'confirmed-ledger',ledger,expectedDigest:await sha256(canonical(ledger))},personalReferences:[]})).rejects.toThrow('CROSS_COMPANY_IDENTITY');
  });
});

describe('projection input proof and revision semantics',()=>{
  it('invalidates JSON-identical inputs when Python, exporter, rules, contract or runtime changes',async()=>{
    const b=await fixture(), proof=await createProjectionProof(b,await inputs(b),bootstrap);
    const observation=catalogObservation(proof,(await selectModelC(b,bootstrap)).catalogContentDigest);
    for(const mutate of [(x:ProjectionInputs)=>{x.sourceFiles.find(f=>f.path==='sync_analysis_state.py')!.sha256='c'.repeat(64);},
      (x:ProjectionInputs)=>{x.implementationFiles.find(f=>f.path==='tools/export_snapshot.py')!.sha256='c'.repeat(64);},
      (x:ProjectionInputs)=>{x.implementationFiles.find(f=>f.path==='shared/model-c-selection.ts')!.sha256='c'.repeat(64);},
      (x:ProjectionInputs)=>{x.sourceFiles.find(f=>f.path==='job_watch_rules.json')!.sha256='c'.repeat(64);},
      (x:ProjectionInputs)=>{x.runtime.python='synthetic-python-new';},
      (x:ProjectionInputs)=>{x.selectionContextDigest='d'.repeat(64);}]){
      const changed=structuredClone(proof.inputs);mutate(changed);
      expect(canReuseProjection(observation,await projectionInputDigest(changed))).toBe(false);
    }
    expect(canReuseProjection(observation,proof.projectionInputDigest)).toBe(true);
  });
  it('binds proof claims to manifest, requires code coverage and rejects tampering',async()=>{
    const b=await fixture(), source=await inputs(b), proof=await createProjectionProof(b,source,bootstrap);
    expect(await verifyProjectionProof(b,proof,bootstrap)).toEqual(proof);
    await expect(verifyProjectionProof(b,{...proof,projectionInputDigest:'f'.repeat(64)},bootstrap)).rejects.toThrow('PROJECTION_PROOF_MISMATCH');
    await expect(createProjectionProof(b,{...source,implementationFiles:source.implementationFiles.slice(1)},bootstrap)).rejects.toThrow();
    await expect(createProjectionProof(b,{...source,sourceFiles:source.sourceFiles.filter(f=>f.path!=='current_jobs_jw1.json')},bootstrap)).rejects.toThrow('UNBOUND_DATA_PROOF');
  });
  it('separates observed commit, content origin and catalog revision',async()=>{
    const b=await fixture(), p=await createProjectionProof(b,await inputs(b),bootstrap);const selected=await selectModelC(b,bootstrap);
    const first=catalogObservation(p,selected.catalogContentDigest);
    const next=await fixture([job],[],'b'.repeat(40)), p2=await createProjectionProof(next,await inputs(next),bootstrap);
    const second=catalogObservation(p2,(await selectModelC(next,bootstrap)).catalogContentDigest,first);
    expect(second.observedGitCommit).not.toBe(first.observedGitCommit);expect(second.contentOrigin).toEqual(first.contentOrigin);expect(second.catalogRevision).toBe(1);
    const changed=await selectModelC(await fixture([{...job,title:'Changed synthetic title'}]),bootstrap);
    expect(catalogObservation(p2,changed.catalogContentDigest,second).catalogRevision).toBe(2);
  });
});

it('agrees with the unchanged Python projection on isolated synthetic cases',async()=>{
  const result=spawnSync(process.env.JOB_WATCH_PYTHON||'python3',['tools/model_c_fixture.py'],{encoding:'utf8',env:{...process.env,PYTHONDONTWRITEBYTECODE:'1'}});
  expect(result.status).toBe(0);
  const results=new Map<string,Awaited<ReturnType<typeof selectModelC>>>();
  for(const item of JSON.parse(result.stdout) as {scenario:string;extracted:unknown}[]) results.set(item.scenario,await selectModelC(await prepareBundle(item.extracted),bootstrap));
  expect(results.get('pending_partial')!.catalog).toHaveLength(1);
  expect(results.get('manual_alias_reopened')!.catalog).toHaveLength(0);expect(results.get('manual_alias_reopened')!.ledger.mappings).toHaveLength(2);
  expect(results.get('automatic')!.catalog).toHaveLength(0);
  expect(results.get('unknown_personal')!.subjects[0]!.lifecycle).toBe('UNKNOWN');
  expect(results.get('closed_personal')!.subjects[0]!.lifecycle).toBe('CLOSED');
  expect(results.get('blocked_ai')!.aiQueue[0]!.workerEligible).toBe(false);
});
