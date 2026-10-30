"""Synthetic source fixtures only. Production JSON is never opened by these tests."""
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
spec = importlib.util.spec_from_file_location('web_exporter', HERE/'export_snapshot.py')
exporter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(exporter)
STAMP = '2026-10-29T10:00:00Z'


class ExporterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='web-export-fixture-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for module in ['pipeline_state','job_memory','sync_analysis_state','harden_job_watch_state','daily_worklist','location_policy','jd_retry']:
            shutil.copyfile(REPO/(module+'.py'), self.root/(module+'.py'))
        self.put('companies_job_watch_v2.json', {'companies':[{'id':1,'company':'Amazon','allowed_locations':['Milan']}]})
        self.put('company_candidates.json', {'records':{}})
        self.put('job_watch_rules.json', {'reporting_thresholds_by_geography':{'Milan':70}})
        self.put('job_watch_batches.json', {'batches':{b.upper():{'companies':['Amazon'] if b=='jw2' else []} for b in exporter.BATCHES}})
        self.put('amazon_target_check.json', {'checked_at':STAMP})
        self.job = {'company':'Amazon','source_id':'123456','title':'Strategy Analyst','location':'Milan',
                    'canonical_url':'https://www.amazon.jobs/en/jobs/123456/role','fingerprint':'b'*16,
                    'status':'STILL_OPEN','first_seen_at':STAMP,'last_seen_at':STAMP}
        for b in exporter.BATCHES:
            self.put(f'current_jobs_{b}.json', {'generated_at':STAMP,'companies':[{'company':'Amazon','coverage':'PARTIAL','jobs':[self.job]}] if b=='jw2' else []})
            self.put(f'job_memory_{b}.json', {'batch':b.upper(),'records':{}})
            self.put(f'ats_mapping_{b}.json', {'companies':[{'company':'Amazon','ats':{'family':'official','tenant':'amazon'}}] if b=='jw2' else []})
        for name in ['pipeline_execution.json','daily_activity.json','daily_worklist.json']:
            self.put(name, {'records':[]})
        sys.path.insert(0,str(self.root))
        self.addCleanup(lambda: sys.path.remove(str(self.root)))
        self.coherent()

    def put(self, name, value):
        (self.root/name).write_text(json.dumps(value))

    def coherent(self):
        import pipeline_state
        token = pipeline_state.snapshot(self.root)
        self.put('job_watch_run_state.json', {'version':'2.0',**token})
        self.put('job_watch_healthcheck.json', {'snapshot':token,'run_id':token['run_id'],'generated_at':STAMP,
                    'status':'NEEDS_REVIEW','collection_status':'COMPLETE_WITH_WARNINGS','DAILY_COMPLETE':False,'FULL_SEMANTIC_COMPLETE':False})

    def extract(self):
        return exporter.extract(self.root,'a'*40,STAMP)

    def test_joins_inventory_memory_archive_instead_of_daily(self):
        self.put('job_memory_jw2.json', {'batch':'JW2','records':{'Amazon::missing':{'identity':{**self.job,'source_id':'missing','canonical_url':'https://www.amazon.jobs/en/jobs/654321/missing'}}}})
        (self.root/'archive').mkdir()
        (self.root/'archive/vacancies_2026_10.jsonl').write_text(json.dumps({**self.job,'company':'Historical Company','source_id':'old','job_key':'Historical Company::old'})+'\n')
        rows = self.extract()['rows']
        jobs = {row['jobKey']:row for row in rows if row['kind']=='job'}
        self.assertEqual(len(jobs),3)
        self.assertEqual(jobs['Amazon::missing']['lifecycle'],'UNKNOWN')
        self.assertEqual(jobs['Historical Company::old']['lifecycle'],'CLOSED')
        self.assertIsNone(jobs['Historical Company::old']['batch'])
        source = next(row for row in rows if row['kind']=='source')
        self.assertEqual(source['coverage'],'PARTIAL')

    def test_amazon_alias_preserves_applied_across_fingerprint(self):
        self.put('job_memory_jw2.json', {'batch':'JW2','records':{'Amazon::old-uuid':{
            'identity':{**self.job,'source_id':'old-uuid'},
            'user':{'decision':'APPLIED','fingerprint':'a'*16,'decided_at':STAMP}}}})
        jobs = [row for row in self.extract()['rows'] if row['kind']=='job']
        self.assertEqual(len(jobs),1)
        self.assertEqual(jobs[0]['aliases'],['Amazon::old-uuid'])
        self.assertEqual(jobs[0]['effectiveDecision'],'APPLIED')
        self.assertFalse(jobs[0]['needsAnalysis'])

    def test_missing_identity_keeps_explicit_user_choice(self):
        self.put('job_memory_jw2.json', {'batch':'JW2','records':{'Amazon::missing':{
            'identity':{**self.job,'source_id':'missing','canonical_url':'https://www.amazon.jobs/en/jobs/654321/missing'},'user':{'decision':'NOT_INTERESTED','decided_at':STAMP}}}})
        job = next(row for row in self.extract()['rows'] if row.get('jobKey')=='Amazon::missing' and row['kind']=='job')
        self.assertEqual(job['effectiveDecision'],'NOT_INTERESTED')
        self.assertEqual(job['lifecycle'],'UNKNOWN')

    def test_verified_evidence_expands_in_private_hash_input_only(self):
        evidence = 'Synthetic review evidence, used only as a hash preimage.'
        key = hashlib.sha256(evidence.encode()).hexdigest()[:20]
        semantic = {'fingerprint':'b'*16,'analysis_method':'chatgpt_semantic_triage','analysis_status':'ANALYZED',
                    'decision':'REJECT','reason':'WRONG_FUNCTION','rationale':{'$e':key},'analyzed_at':STAMP}
        self.put('job_memory_jw2.json', {'batch':'JW2','records':{'Amazon::123456':{'identity':self.job,'semantic':semantic}},
                    'evidence_encoding':'sha256-text-v1','semantic_evidence':{key:evidence}})
        result = self.extract()
        review = next(row for row in result['rows'] if row['kind']=='semantic')
        self.assertEqual(review['hashInput']['rationale'],evidence)
        self.assertNotIn('rationale',review)
        data = json.loads((self.root/'job_memory_jw2.json').read_text())
        data['semantic_evidence'][key]='Corrupted synthetic evidence'
        self.put('job_memory_jw2.json',data)
        with self.assertRaises(ValueError): self.extract()

    def test_incoherent_snapshot_is_rejected(self):
        self.put('amazon_target_check.json',{'checked_at':'2026-10-28T10:00:00Z'})
        with self.assertRaisesRegex(ValueError,'INCOHERENT'): self.extract()

    def test_ambiguous_current_url_does_not_merge_identities(self):
        current=json.loads((self.root/'current_jobs_jw2.json').read_text())
        current['companies'][0]['jobs'].append({**self.job,'source_id':'another-current-id'})
        self.put('current_jobs_jw2.json',current)
        self.put('job_memory_jw2.json', {'batch':'JW2','records':{'Amazon::old-uuid':{'identity':self.job,
                    'user':{'decision':'APPLIED','decided_at':STAMP}}}})
        self.coherent()
        jobs=[row for row in self.extract()['rows'] if row['kind']=='job']
        self.assertEqual(len(jobs),3)
        self.assertTrue(all(not row['aliases'] for row in jobs))

    def test_historical_shortened_review_requires_new_analysis(self):
        semantic={'fingerprint':'b'*16,'analysis_method':'chatgpt_semantic_full_jd','analyzed_at':STAMP,
                  'historical_evidence':{'version':1,'source_sha256':'c'*64}}
        self.put('job_memory_jw2.json', {'batch':'JW2','records':{'Amazon::123456':{'identity':self.job,'semantic':semantic}}})
        rows=self.extract()['rows']
        job=next(row for row in rows if row['kind']=='job')
        self.assertTrue(job['needsAnalysis'])
        self.assertIsNone(job['fitScore'])
        self.assertEqual(next(row for row in rows if row['kind']=='semantic')['evidenceState'],'HISTORICAL_SHORTENED')

    def test_terminal_jd_retry_is_not_a_semantic_rejection(self):
        state={'evidence':{'fingerprint':'b'*16,'source_url':self.job['canonical_url']},'attempts':4,
               'last_failure_at':STAMP,'retry_from':None,'status':'JD_UNAVAILABLE'}
        self.put('job_memory_jw2.json', {'batch':'JW2','records':{'Amazon::123456':{'identity':self.job,'jd_fetch':state}}})
        job=next(row for row in self.extract()['rows'] if row['kind']=='job')
        self.assertTrue(job['needsAnalysis']);self.assertFalse(job['workerEligible'])
        self.assertEqual(job['technicalStatus'],'JD_UNAVAILABLE');self.assertIsNone(job['effectiveDecision'])

    def test_cli_reads_pinned_git_bytes_and_rejects_tampered_manifest_before_d1(self):
        def git(*args):
            return subprocess.check_output(['git','-C',str(self.root),*args],stderr=subprocess.DEVNULL,text=True).strip()
        git('init','-q','-b','main');git('remote','add','origin','https://github.com/giacodmr/job-watch-milano.git')
        git('add','.');git('-c','user.name=Fixture','-c','user.email=fixture@example.test','commit','-qm','Synthetic fixture')
        sha=git('rev-parse','HEAD');git('update-ref','refs/remotes/origin/main',sha)
        dirty=(self.root/'current_jobs_jw2.json').read_text().replace('Strategy Analyst','DIRTY_UNCOMMITTED_VALUE')
        (self.root/'current_jobs_jw2.json').write_text(dirty)
        output=self.root/'output.json'
        command=['node',str(HERE/'local-sync.mjs')]
        result=subprocess.run([*command,'export','--repo',str(self.root),'--commit',sha,'--file',str(output)],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        data=json.loads(output.read_text())
        self.assertEqual(data['manifest']['commitSha'],sha)
        self.assertNotIn('DIRTY_UNCOMMITTED_VALUE',output.read_text())
        self.assertEqual((self.root/'current_jobs_jw2.json').read_text(),dirty)
        data['manifest']['files'][0]['bytes']+=1;output.write_text(json.dumps(data))
        rejected=subprocess.run([*command,'import','--repo',str(self.root),'--file',str(output)],capture_output=True,text=True)
        self.assertEqual(rejected.returncode,1)
        self.assertIn('SOURCE_HASH_MISMATCH',rejected.stderr)

    def test_export_does_not_write_source_or_recompute_fingerprint(self):
        before = {p.name:p.read_bytes() for p in self.root.glob('*.json')}
        result = self.extract()
        self.assertEqual(before,{p.name:p.read_bytes() for p in self.root.glob('*.json')})
        job = next(row for row in result['rows'] if row['kind']=='job')
        self.assertEqual(job['fingerprint'],'b'*16)
        self.assertEqual(exporter.safe_url('https://jobs.example.test/path?token=secret&id=42#fragment'),'https://jobs.example.test/path?id=42')


if __name__ == '__main__':
    unittest.main()
