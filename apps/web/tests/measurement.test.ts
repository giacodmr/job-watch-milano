import { describe,expect,it } from 'vitest';
import { canonical } from '../shared/canonical';
import type { SnapshotRow } from '../shared/snapshot';
import { compareRows } from '../tools/measure-rows';

const company: SnapshotRow = { kind:'company',id:'company:synthetic',name:'Synthetic Company',configId:'synthetic',
  tier:'A',priority:null,careerUrl:null,membership:'ACTIVE',sourcePath:'companies_job_watch_v2.json',sourceSha256:'a'.repeat(64) };
const review: SnapshotRow = { kind:'semantic',jobKey:'Synthetic Company::1',resultSha256:'b'.repeat(64),
  fingerprint:'synthetic',method:'chatgpt_semantic_full_jd',decision:null,fitScore:75,reportable:true,evidenceState:'FULL',
  analyzedAt:'2026-10-30T08:00:00Z',sourcePath:'job_memory_jw1.json',sourceSha256:'a'.repeat(64) };
const pack = (...rows: SnapshotRow[]) => ({chunks:[rows]});

describe('measurement classification',() => {
  it('does not invent additions for repeated event observations in identical inputs',() => {
    const input = pack(review,{...review});
    const result=compareRows(input,input,canonical).counts.semantic;
    expect(result).toMatchObject({before:2,after:2,exactUnchanged:2,added:0,removed:0,payloadChanged:0});
    expect(input.chunks[0]).toHaveLength(2);
  });
  it('distinguishes exact rows, provenance-only changes and changed payloads',() => {
    const provenance=compareRows(pack(company),pack({...company,sourceSha256:'c'.repeat(64)}),canonical);
    expect(provenance.counts.company).toMatchObject({exactUnchanged:0,provenanceOnlyChanged:1,payloadChanged:0});
    expect(provenance.classifications.get('company\0company:synthetic')).toBe('provenance-only');
    expect(compareRows(pack(company),pack({...company,tier:'B'}),canonical).counts.company).toMatchObject({payloadChanged:1,provenanceOnlyChanged:0});
  });
  it('counts a missing duplicate as one removal and keeps event timestamps significant',() => {
    expect(compareRows(pack(review,review),pack(review),canonical).counts.semantic).toMatchObject({exactUnchanged:1,removed:1});
    expect(compareRows(pack(review),pack({...review,analyzedAt:'2026-10-31T08:00:00Z'}),canonical).counts.semantic).toMatchObject({payloadChanged:1,provenanceOnlyChanged:0});
  });
});
