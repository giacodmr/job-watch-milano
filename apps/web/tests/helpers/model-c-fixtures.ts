// Synthetic SQL fixtures only. This is not a general importer/publication service.
export const hash='a'.repeat(64), commit='b'.repeat(40), jobId='job:'+'1'.repeat(64), owner='synthetic-owner';
export async function stageCatalog(db:D1Database, run='run-one', expected=0, contentRevision=1, contentDigest=hash, chunks=true, remove=false) {
  await db.prepare('INSERT INTO catalog_content_revisions VALUES (?,?,?,?) ON CONFLICT DO NOTHING').bind(contentRevision,contentDigest,commit,hash).run();
  await db.prepare('INSERT INTO catalog_ledger_checkpoints VALUES (1,?,1,2) ON CONFLICT DO NOTHING').bind(hash).run();
  await db.prepare('INSERT INTO catalog_runs(id,observed_commit,projection_digest,expected_revision,content_revision,ledger_revision,expected_chunks,expected_companies,expected_sources,expected_vacancies) VALUES (?,?,?,?,?,1,1,1,1,?)').bind(run,commit,hash,expected,contentRevision,remove?0:1).run();
  const origin='origin:'+run;
  await db.prepare('INSERT INTO catalog_origins VALUES (?,?,?,?,?)').bind(origin,run,commit,'current_jobs_jw1.json',hash).run();
  await db.prepare('INSERT INTO catalog_stage_companies VALUES (?,\'company:synthetic\',\'Synthetic Company\',NULL,?)').bind(run,origin).run();
  await db.prepare("INSERT INTO catalog_stage_sources VALUES (?,'source:synthetic','company:synthetic','synthetic-board','synthetic-ats','https://jobs.example.test','PARTIAL',NULL,?)").bind(run,origin).run();
  if(remove) await db.prepare("INSERT INTO catalog_stage_vacancies(run_id,job_id,company_id,origin_job_key,operation,origin_id) VALUES (?,?,'company:synthetic','Synthetic Company::current','REMOVE',?)").bind(run,jobId,origin).run();
  else await db.prepare("INSERT INTO catalog_stage_vacancies(run_id,job_id,company_id,origin_job_key,operation,kind,lifecycle,title,origin_id) VALUES (?,?,'company:synthetic','Synthetic Company::current','UPSERT','OPPORTUNITY','STILL_OPEN','Synthetic Analyst',?)").bind(run,jobId,origin).run();
  for(const key of ['Synthetic Company::current','Synthetic Company::old']) await db.prepare("INSERT INTO catalog_stage_aliases VALUES (?,?,?,'PYTHON_RESOLVED')").bind(run,key,jobId).run();
  if(chunks) {
    await db.prepare('INSERT INTO catalog_chunks VALUES (?,0,?,4)').bind(run,hash).run();
    await db.prepare("UPDATE catalog_runs SET state='READY' WHERE id=?").bind(run).run();
  }
  return {run,origin,expected,contentRevision};
}
export function publicationFixture(db:D1Database, run:string, expected=0, contentRevision=1) {
  const origin='origin:'+run;
  return [
    db.prepare('INSERT INTO catalog_cas_guard VALUES (?)').bind(expected),
    db.prepare("INSERT INTO catalog_company_identity VALUES ('company:synthetic') ON CONFLICT DO NOTHING"),
    db.prepare("INSERT INTO catalog_source_identity VALUES ('source:synthetic','company:synthetic','synthetic-board') ON CONFLICT DO NOTHING"),
    db.prepare("INSERT INTO catalog_vacancy_identity VALUES (?,'company:synthetic','Synthetic Company::current') ON CONFLICT DO NOTHING").bind(jobId),
    ...['Synthetic Company::current','Synthetic Company::old'].map(key=>db.prepare("INSERT INTO catalog_aliases VALUES (?,?,'PYTHON_RESOLVED') ON CONFLICT DO NOTHING").bind(key,jobId)),
    db.prepare("INSERT INTO catalog_company_current VALUES ('company:synthetic','Synthetic Company',NULL,?) ON CONFLICT(company_id) DO UPDATE SET origin_id=excluded.origin_id").bind(origin),
    db.prepare("INSERT INTO catalog_source_current VALUES ('source:synthetic','company:synthetic','synthetic-ats','https://jobs.example.test','PARTIAL',NULL,?) ON CONFLICT(source_id) DO UPDATE SET origin_id=excluded.origin_id").bind(origin),
    db.prepare("INSERT INTO catalog_vacancy_current(job_id,company_id,source_id,kind,lifecycle,title,origin_id) VALUES (?,'company:synthetic','source:synthetic','OPPORTUNITY','STILL_OPEN','Synthetic Analyst',?) ON CONFLICT(job_id) DO UPDATE SET origin_id=excluded.origin_id").bind(jobId,origin),
    expected===0 ? db.prepare("INSERT INTO catalog_head VALUES ('catalog',1,?,?,1)").bind(run,contentRevision)
      : db.prepare("UPDATE catalog_head SET sync_revision=?,run_id=?,content_revision=?,ledger_revision=1 WHERE scope='catalog'").bind(expected+1,run,contentRevision),
  ];
}
export async function seedPersonal(db:D1Database) {
  await db.prepare('INSERT INTO personal_owners VALUES (?)').bind(owner).run();
  await db.prepare("INSERT INTO personal_job_refs VALUES (?,?,'Synthetic archived role','https://jobs.example.test','CLOSED',?,'job_memory_jw1.json',?,1)").bind(owner,jobId,commit,hash).run();
  await db.prepare("INSERT INTO personal_reference_state VALUES (?,?,'DISMISSED',1,1)").bind(owner,jobId).run();
  await db.prepare("INSERT INTO personal_decision_events(owner_id,id,job_id,decision,fingerprint,decided_at,result_sha256,source_commit,source_path,source_sha256) VALUES (?,'decision:synthetic',?,'NOT_INTERESTED','opaque-fingerprint','2026-10-30T10:00:00Z',?,?,'job_memory_jw1.json',?)").bind(owner,jobId,hash,commit,hash).run();
  await db.prepare("INSERT INTO personal_decision_current VALUES (?,?,'decision:synthetic',1)").bind(owner,jobId).run();
  await db.prepare("INSERT INTO personal_assessment_events(owner_id,id,job_id,fingerprint,method,fit_score,reportable,summary,evidence_state,analyzed_at,result_sha256,source_commit,source_path,source_sha256) VALUES (?,'review:synthetic',?,'opaque-fingerprint','chatgpt_semantic_full_jd',75,1,'Synthetic bounded summary','FULL','2026-10-30T10:00:00Z',?,?,'job_memory_jw1.json',?)").bind(owner,jobId,hash,commit,hash).run();
  await db.prepare("INSERT INTO personal_assessment_current VALUES (?,?,'review:synthetic',1)").bind(owner,jobId).run();
  await db.prepare('INSERT INTO personal_heads VALUES (?,1,?,?)').bind(owner,hash,commit).run();
  await db.prepare("INSERT INTO personal_reconciliation VALUES (?,?,1,'PENDING',NULL,NULL)").bind(owner,jobId).run();
  await db.prepare("INSERT INTO personal_audit VALUES ('audit:synthetic',?,'SYNTHETIC_DECISION_CAPTURED',?)").bind(owner,hash).run();
}
export async function seedV1(db:D1Database) {
  await db.prepare("INSERT INTO sync_snapshots(id,repository,commit_sha,manifest_sha256,contract_version,expected_chunks,manifest_json) VALUES ('synthetic-v1','giacodmr/job-watch-milano',?,?,1,1,?)").bind(commit,hash,JSON.stringify({observedAt:'2026-10-30T10:00:00Z',files:[]})).run();
  await db.prepare("INSERT INTO sync_chunks(snapshot_id,chunk_index,content_sha256,row_count) VALUES ('synthetic-v1',0,?,1)").bind(hash).run();
  await db.prepare("UPDATE sync_snapshots SET state='CONFIRMED',confirmed_at='2026-10-30T10:00:00Z' WHERE id='synthetic-v1'").run();
  await db.prepare("INSERT INTO companies(id,canonical_name) VALUES ('company:synthetic','Synthetic Company')").run();
  await db.prepare("INSERT INTO jobs(id,company_id,origin_job_key) VALUES (?,'company:synthetic','Synthetic Company::current')").bind(jobId).run();
  await db.prepare("INSERT INTO job_aliases(alias_key,job_id,snapshot_id,resolution) VALUES ('Synthetic Company::old',?,'synthetic-v1','PYTHON_RESOLVED')").bind(jobId).run();
  await db.prepare("INSERT INTO user_decisions(id,job_id,snapshot_id,decision,decided_at,source_path,source_sha256,result_sha256) VALUES ('decision:synthetic',?,'synthetic-v1','NOT_INTERESTED','2026-10-30T10:00:00Z','job_memory_jw1.json',?,?)").bind(jobId,hash,hash).run();
  await db.prepare("INSERT INTO snapshot_user_decisions VALUES ('synthetic-v1','decision:synthetic')").run();
  await db.prepare("INSERT INTO sync_checkpoints VALUES ('main','synthetic-v1',1,'2026-10-30T10:00:00Z')").run();
}
