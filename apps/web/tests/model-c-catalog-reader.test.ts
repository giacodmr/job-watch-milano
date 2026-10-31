import { beforeAll, afterAll, describe, it, expect } from 'vitest';
import { Miniflare, convertV4MiniflareOptions } from 'miniflare';
import { applySchema } from '../tools/model-c-schema';
import { stageCatalog, publicationFixture, jobId, hash } from './helpers/model-c-fixtures';
import { canonical } from '../shared/canonical';
import { getModelCCatalogSnapshot, listModelCCatalogJobs, getModelCCatalogJob, ModelCReadError } from '../worker/data/model-c-catalog';

let runtime: Miniflare;
let sequence = 0;
beforeAll(() => {
  runtime = new Miniflare(convertV4MiniflareOptions({
    modules: true, script: 'export default {fetch(){return new Response("synthetic")}}',
    cf: false, compatibilityDate: '2026-10-29',
    d1Databases: Object.fromEntries(Array.from({length: 10}, (_, i) => ['DB' + i, 'model-c-reader-' + i])),
  }));
});
afterAll(async () => { await runtime?.dispose(); });
async function fresh(scope: 'catalog' | 'personal' = 'catalog') {
  const db = await runtime.getD1Database('DB' + sequence++);
  await applySchema(db, scope);
  return db;
}
const syntheticCursor = (revision: number, runId: string, filters: object, lastId = 'job:' + '0'.repeat(64)) =>
  btoa(JSON.stringify({revision, runId, lastId, filters: canonical(filters)}))
    .replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');

describe('inactive, read-only Model C catalog service', () => {
  it('hides staging and does not invent a published checkpoint', async () => {
    const db = await fresh();
    expect(await getModelCCatalogSnapshot(db)).toEqual({snapshot:null,productionAccess:false});
    await stageCatalog(db);
    expect((await listModelCCatalogJobs(db)).items).toEqual([]);
    await expect(getModelCCatalogJob(db,jobId,1)).rejects.toMatchObject({code:'NO_PUBLISHED_CATALOG'});
    expect(await db.prepare('SELECT count(*) AS n FROM catalog_head').first('n')).toBe(0);
  });
  it('reads the published head, stable job data, provenance and aliases without PERSONAL joins', async () => {
    const db = await fresh();
    await stageCatalog(db);
    await db.batch(publicationFixture(db,'run-one'));
    const snapshot = await getModelCCatalogSnapshot(db);
    expect(snapshot).toMatchObject({
      snapshot:{syncRevision:1,runId:'run-one',currentJobs:1,identityCount:1,mappingCount:2},
      productionAccess:false,
    });
    const list = await listModelCCatalogJobs(db,{limit:1});
    expect(list).toMatchObject({total:1,nextCursor:null,items:[{
      id:jobId,jobKey:'Synthetic Company::current',company:'Synthetic Company',
      needsAnalysis:false,workerEligible:null,originCommit:'b'.repeat(40),
      originPath:'current_jobs_jw1.json',originSha256:hash,
    }]});
    const detail = await getModelCCatalogJob(db,jobId,1);
    expect(detail.aliases).toEqual(['Synthetic Company::current','Synthetic Company::old']);
    expect(detail.aliasesTruncated).toBe(false);
    expect(detail.job.id).toBe(jobId);
    expect(await db.prepare('SELECT count(*) AS n FROM catalog_write_reservations').first('n')).toBe(0);
  });
  it('binds literal search, filters and cursors and rejects stale pagination after a new publication', async () => {
    const db = await fresh();
    await stageCatalog(db);
    await db.batch(publicationFixture(db,'run-one'));
    expect((await listModelCCatalogJobs(db,{q:'Synthetic',kind:'OPPORTUNITY'})).total).toBe(1);
    expect((await listModelCCatalogJobs(db,{q:'%_[]'})).total).toBe(0);
    expect((await listModelCCatalogJobs(db,{kind:'AI_QUEUE'})).items).toEqual([]);
    expect((await listModelCCatalogJobs(db,{companyId:'other'})).items).toEqual([]);
    const cursor = syntheticCursor(1,'run-one',{q:''});
    expect((await listModelCCatalogJobs(db,{limit:1,cursor})).items).toHaveLength(1);
    await expect(listModelCCatalogJobs(db,{cursor:'not-base64'})).rejects.toMatchObject({code:'INVALID_CURSOR'});
    await expect(listModelCCatalogJobs(db,{cursor,q:'other'})).rejects.toMatchObject({code:'CURSOR_FILTER_MISMATCH'});
    await stageCatalog(db,'run-two',1,2,'c'.repeat(64));
    await db.batch(publicationFixture(db,'run-two',1,2));
    await expect(listModelCCatalogJobs(db,{cursor})).rejects.toMatchObject({code:'CATALOG_CHANGED'});
    await expect(getModelCCatalogJob(db,jobId,1)).rejects.toMatchObject({code:'CATALOG_CHANGED'});
    expect((await getModelCCatalogJob(db,jobId,2)).snapshot?.syncRevision).toBe(2);
  });
  it('only marks companies as truncated when a 501st company exists', async () => {
    const readAt = async (count: number) => {
      const records = Array.from({length: count}, (_, i) => ({
        id: 'company:' + i, name: 'Synthetic ' + i, membership: 'ACTIVE',
      }));
      const head = {
        syncRevision: 1, contentRevision: 1, ledgerRevision: 1,
        runId: 'run-one', observedCommit: 'b'.repeat(40), state: 'PUBLISHED',
        contentDigest: hash, ledgerDigest: hash, contentOriginCommit: 'b'.repeat(40),
        identityCount: 1, mappingCount: 2,
      };
      const queryDb = {
        prepare(sql: string) {
          if (sql.includes('FROM catalog_visible_companies')) {
            expect(sql).toContain('LIMIT 501');
            return {all: async () => ({results: records})};
          }
          if (sql.includes('FROM model_c_schema')) return {first: async () => 5};
          if (sql.includes('FROM catalog_head h')) return {first: async () => head};
          if (sql.includes('count(*) AS total')) return {first: async () => 1};
          throw new Error('UNEXPECTED_READ');
        },
      } as unknown as D1Database;
      return getModelCCatalogSnapshot(queryDb);
    };
    const exact = await readAt(500);
    expect(exact.snapshot?.companies).toHaveLength(500);
    expect(exact.snapshot?.companiesTruncated).toBe(false);
    const extra = await readAt(501);
    expect(extra.snapshot?.companies).toHaveLength(500);
    expect(extra.snapshot?.companiesTruncated).toBe(true);
  });
  it('requires the CATALOG schema, strict inputs and current ID without silently exposing history', async () => {
    const personal = await fresh('personal');
    await expect(getModelCCatalogSnapshot(personal)).rejects.toMatchObject({code:'CATALOG_SCHEMA_MISMATCH'});
    const db = await fresh();
    await stageCatalog(db);
    await db.batch(publicationFixture(db,'run-one'));
    await expect(listModelCCatalogJobs(db,{limit:101})).rejects.toThrow();
    await expect(listModelCCatalogJobs(db,{unknown:'anything'} as never)).rejects.toThrow();
    await expect(getModelCCatalogJob(db,'bad-id',1)).rejects.toThrow();
    await expect(getModelCCatalogJob(db,'job:' + '2'.repeat(64),1)).rejects.toMatchObject({code:'JOB_NOT_CURRENT'});
    await expect(getModelCCatalogJob(db,jobId,0)).rejects.toMatchObject({code:'INVALID_REVISION'});
    expect(new ModelCReadError('EXPECTED',400).status).toBe(400);
  });
});
