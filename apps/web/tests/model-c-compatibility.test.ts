import {beforeAll,afterAll,it,expect} from 'vitest';
import {Miniflare,convertV4MiniflareOptions} from 'miniflare';
import {applySchema,migrationSources} from '../tools/model-c-schema';
import {stageCatalog,publicationFixture,catalogFixtureValues,jobId,hash,commit} from './helpers/model-c-fixtures';
import {rowSchema,prepareBundle,requiredFiles} from '../shared/snapshot';
import {selectModelC} from '../shared/model-c-selection';
import {canonical,sha256} from '../shared/canonical';
let runtime:Miniflare,sequence=0;
beforeAll(()=>{runtime=new Miniflare(convertV4MiniflareOptions({modules:true,script:'export default {fetch(){return new Response("synthetic-only")}}',cf:false,compatibilityDate:'2026-10-29',d1Databases:Object.fromEntries(Array.from({length:15},(_,i)=>['DB'+i,'compatibility-'+i]))}));});
afterAll(async()=>{await runtime?.dispose();});
async function fresh(){const db=await runtime.getD1Database('DB'+sequence++);await applySchema(db,'catalog');return db;}
const stamp='2026-10-30T10:00:00Z';

it.each([null,'JD_UNAVAILABLE'])('keeps an OPPORTUNITY in the independent AI queue with technical status %s',async technicalStatus=>{
  const bundle=await prepareBundle({commitSha:commit,observedAt:stamp,
    files:requiredFiles.map(path=>({path,sha256:hash,bytes:1})),rows:[
      {kind:'company',id:'company:synthetic',name:'Synthetic Company',configId:null,tier:null,priority:null,membership:'ACTIVE',careerUrl:null,sourcePath:'companies_job_watch_v2.json',sourceSha256:hash},
      {kind:'job',jobKey:'Synthetic Company::current',aliases:['Synthetic Company::old'],companyId:'company:synthetic',sourceId:null,upstreamSourceId:'current',batch:'jw1',title:'Synthetic Analyst',location:null,canonicalUrl:null,applyUrl:null,fingerprint:null,lifecycle:'STILL_OPEN',firstSeenAt:null,lastSeenAt:null,analysisStatus:'PENDING',analysisMethod:null,needsAnalysis:true,workerEligible:false,hardExclusionReason:null,fitScore:null,reportable:true,effectiveDecision:null,technicalStatus,sortKey:'synthetic',sourcePath:'current_jobs_jw1.json',sourceSha256:hash},
      {kind:'pipeline',runId:null,healthStatus:null,collectionStatus:null,dailyComplete:null,fullSemanticComplete:null,generatedAt:null,sourcePath:'job_watch_healthcheck.json',sourceSha256:hash},
    ]});
  const ledger={identities:[{jobId,companyId:'company:synthetic',originJobKey:'Synthetic Company::current'}],mappings:['Synthetic Company::current','Synthetic Company::old'].map(key=>({key,jobId}))};
  const selection=await selectModelC(bundle,{identities:{mode:'confirmed-ledger',ledger,expectedDigest:await sha256(canonical(ledger))},personalReferences:[]});
  expect(selection.catalog).toEqual([{jobId,kind:'OPPORTUNITY'}]);expect(selection.aiQueue).toHaveLength(1);
  expect(selection.aiQueue[0]).toMatchObject({jobId,workerEligible:false,technicalStatus});
  const db=await fresh();await stageCatalog(db,'run-one',0,1,hash,true,false,{...catalogFixtureValues,needsAnalysis:true,workerEligible:false,technicalStatus});
  expect((await db.prepare('SELECT * FROM catalog_visible_vacancies').all()).results).toHaveLength(0);
  expect(await db.prepare('SELECT kind,needs_analysis,worker_eligible,technical_status FROM catalog_stage_vacancies').first()).toEqual({kind:'OPPORTUNITY',needs_analysis:1,worker_eligible:0,technical_status:technicalStatus});
  await db.batch(publicationFixture(db,'run-one'));
  const opportunities=(await db.prepare("SELECT job_id FROM catalog_visible_vacancies WHERE kind='OPPORTUNITY'").all()).results;
  const queue=(await db.prepare('SELECT job_id FROM catalog_visible_vacancies WHERE needs_analysis=1').all()).results;
  expect(opportunities).toEqual([{job_id:jobId}]);expect(queue).toEqual(opportunities);
  expect(await db.prepare('SELECT needs_analysis,worker_eligible,technical_status FROM catalog_visible_vacancies').first()).toEqual({needs_analysis:1,worker_eligible:0,technical_status:technicalStatus});
  await expect(db.prepare('UPDATE catalog_vacancy_current SET needs_analysis=2').run()).rejects.toThrow();
});

it('preserves nullable V1 queue/eligibility flags as unknown rather than false',async()=>{
  const db=await fresh();await stageCatalog(db,'run-one',0,1,hash,true,false,{...catalogFixtureValues,needsAnalysis:null,workerEligible:null});await db.batch(publicationFixture(db,'run-one'));
  expect(await db.prepare('SELECT needs_analysis,worker_eligible FROM catalog_visible_vacancies').first()).toEqual({needs_analysis:null,worker_eligible:null});
  expect((await db.prepare('SELECT job_id FROM catalog_visible_vacancies WHERE needs_analysis=1').all()).results).toHaveLength(0);
});

it.each([
  {configId:'synthetic-config',tier:'2',priority:'synthetic-priority',membership:'ACTIVE' as const},
  {configId:null,tier:null,priority:null,membership:'CANDIDATE' as const},
  {configId:null,tier:null,priority:null,membership:'HISTORICAL' as const},
])('round-trips V1 company metadata for $membership including permitted nulls',async values=>{
  const company=rowSchema.parse({kind:'company',id:'company:synthetic',name:'Synthetic Company',...values,careerUrl:null,sourcePath:'companies_job_watch_v2.json',sourceSha256:'e'.repeat(64)});
  expect(company.kind).toBe('company');
  const db=await fresh();await stageCatalog(db,'run-one',0,1,hash,true,false,{...catalogFixtureValues,...values});
  const expected={config_id:values.configId,tier:values.tier,priority:values.priority,membership:values.membership};
  expect(await db.prepare('SELECT config_id,tier,priority,membership FROM catalog_stage_companies').first()).toEqual(expected);
  await db.batch(publicationFixture(db,'run-one'));
  expect(await db.prepare('SELECT config_id,tier,priority,membership FROM catalog_visible_companies').first()).toEqual(expected);
  await expect(db.prepare("UPDATE catalog_company_current SET membership='UNKNOWN'").run()).rejects.toThrow();
  await expect(db.prepare('UPDATE catalog_company_current SET membership=NULL').run()).rejects.toThrow('company_membership_required');
});

it('publishes distinguishable source-config and ATS-coverage proof references',async()=>{
  const source=rowSchema.parse({kind:'source',id:'source:synthetic',companyId:'company:synthetic',sourceKey:'synthetic-board',family:'synthetic-ats',inventoryUrl:'https://jobs.example.test',coverage:'PARTIAL',generatedAt:null,sourcePath:'ats_mapping_jw1.json',sourceSha256:'c'.repeat(64),coveragePath:'current_jobs_jw1.json',coverageSha256:hash});
  if(source.kind!=='source')throw Error('SYNTHETIC_SOURCE_REQUIRED');
  const db=await fresh();await stageCatalog(db);
  const stage=await db.prepare('SELECT origin_id,coverage_origin_id FROM catalog_stage_sources').first<{origin_id:string;coverage_origin_id:string}>();
  expect(stage!.origin_id).not.toBe(stage!.coverage_origin_id);
  await db.batch(publicationFixture(db,'run-one'));
  expect(await db.prepare(`SELECT s.coverage,s.origin_id,s.coverage_origin_id,
    config.commit_sha AS config_commit,config.source_path AS config_path,config.source_sha256 AS config_hash,
    evidence.commit_sha AS coverage_commit,evidence.source_path AS coverage_path,evidence.source_sha256 AS coverage_hash
    FROM catalog_visible_sources s JOIN catalog_origins config ON config.id=s.origin_id JOIN catalog_origins evidence ON evidence.id=s.coverage_origin_id`).first()).toEqual({coverage:'PARTIAL',...stage,config_commit:commit,config_path:source.sourcePath,config_hash:source.sourceSha256,coverage_commit:commit,coverage_path:source.coveragePath,coverage_hash:source.coverageSha256});
  await expect(db.prepare("UPDATE catalog_source_current SET coverage_origin_id='missing'").run()).rejects.toThrow();
  const staging=await fresh();await stageCatalog(staging,'first',0,1,hash,false);await stageCatalog(staging,'other',0,1,hash,false);
  await expect(staging.prepare("INSERT INTO catalog_stage_sources(run_id,source_id,company_id,source_key,ats_family,origin_id,coverage_origin_id) VALUES ('first','invalid','company:synthetic','invalid','synthetic-ats','source-config:first','origin:other')").run()).rejects.toThrow('coverage_origin_must_match_run');
});

it('upgrades 0001 without guessing missing metadata or rewriting its migration',async()=>{
  const db=await runtime.getD1Database('DB'+sequence++), first=(await migrationSources('catalog'))[0]!;
  await db.batch([db.prepare('CREATE TABLE model_c_migrations (name TEXT PRIMARY KEY NOT NULL,sha256 TEXT NOT NULL CHECK(length(sha256)=64))'),...first.statements.map(s=>db.prepare(s)),db.prepare('INSERT INTO model_c_migrations VALUES (?,?)').bind(first.name,first.sha256)]);
  await db.prepare('INSERT INTO catalog_content_revisions VALUES (1,?,?,?)').bind(hash,commit,hash).run();
  await db.prepare('INSERT INTO catalog_ledger_checkpoints VALUES (1,?,0,0)').bind(hash).run();
  await db.prepare("INSERT INTO catalog_runs(id,observed_commit,projection_digest,expected_revision,content_revision,ledger_revision,expected_chunks,expected_companies,expected_sources,expected_vacancies) VALUES ('legacy',?,?,0,1,1,1,1,1,0)").bind(commit,hash).run();
  await db.prepare("INSERT INTO catalog_origins VALUES ('legacy-origin','legacy',?,'ats_mapping_jw1.json',?)").bind(commit,hash).run();
  await db.prepare("INSERT INTO catalog_company_identity VALUES ('legacy-company')").run();
  await db.prepare("INSERT INTO catalog_company_current VALUES ('legacy-company','Synthetic Legacy',NULL,'legacy-origin')").run();
  await db.prepare("INSERT INTO catalog_source_identity VALUES ('legacy-source','legacy-company','legacy-board')").run();
  await db.prepare("INSERT INTO catalog_source_current VALUES ('legacy-source','legacy-company','synthetic-ats',NULL,'PARTIAL',NULL,'legacy-origin')").run();
  expect(await applySchema(db,'catalog')).toMatchObject({applied:6});
  expect(await db.prepare('SELECT company_id,config_id,tier,priority,membership FROM catalog_company_current').first()).toEqual({company_id:'legacy-company',config_id:null,tier:null,priority:null,membership:null});
  expect(await db.prepare('SELECT source_id,origin_id,coverage_origin_id FROM catalog_source_current').first()).toEqual({source_id:'legacy-source',origin_id:'legacy-origin',coverage_origin_id:null});
  await expect(db.prepare("INSERT INTO catalog_head VALUES ('catalog',1,'legacy',1,1)").run()).rejects.toThrow('catalog_metadata_incomplete');
  expect(await db.prepare('SELECT sha256 FROM model_c_migrations WHERE name=?').bind(first.name).first('sha256')).toBe(first.sha256);
  expect(await applySchema(db,'catalog')).toMatchObject({applied:0,rowsWritten:0});
});
