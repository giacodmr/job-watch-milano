"""Contract regressions across the real entry point, collectors and durable stores."""
import contextlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import pipeline_state as ps
import job_watch, collector, reconcile_workday_target_paths as reconcile
import amazon_target_check as amazon
import daily_worklist, sync_analysis_state as sync, audit_job_watch as audit
import certify_job_watch as cert, enrich_semantic_jds as enrich, validate_job_watch_state as validate
import preflight_job_watch as preflight
from test_daily_pipeline import full_decision


class Fixture:
    def __init__(self, root):
        self.root = root
        source = Path(__file__).resolve().parent
        for f in source.glob('*.py'): (root/f.name).write_bytes(f.read_bytes())
        companies = [{'company':b.upper()} for b in ps.BATCHES]+[{'company':'Mastercard'}]
        self.put('job_watch_rules.json',{'run_certification_policy':{'enabled':True},'daily_worklist_policy':{'backlog_limit':0}})
        self.put('job_watch_batches.json',{'batches':{b.upper():{'companies':[b.upper()]+(['Mastercard'] if b=='jw1' else [])} for b in ps.BATCHES}})
        self.put('companies_job_watch_v2.json',{'companies':companies})
        self.put('watchlist_additions.json',{'companies':[]})
        self.put('discovery_candidates.json',{'records':{}})
        self.put('user_job_decisions.json',{'records':{}})
        self.put('amazon_target_check.json',{'checked_at':'2026-10-03T06:30:00Z','target_jobs':[],
            'locations':{city:{'coverage':'VERIFIED','inventory_count':0,'api_reported_hits_sum':0} for city in ['Milan','Rome','London','Luxembourg']}})
        for b in ps.BATCHES:
            members = [c for c in companies if c['company'] == b.upper() or b=='jw1' and c['company']=='Mastercard']
            self.put(f'ats_mapping_{b}.json',{'batch':b.upper(),'companies':members})
            self.put(f'current_jobs_{b}.json',{'batch':b.upper(),'generated_at':'2026-10-03T06:30:00Z','summary':{'VERIFIED':len(members),'PARTIAL':0,'FAILED':0,'NOT_CHECKED':0,'target_jobs_open':0},'companies':[{**c,'coverage':'VERIFIED','jobs':[]} for c in members]})
            for stem in ('analysis_results','semantic_decisions','surfaced_jobs','semantic_jd_cache'):
                self.put(f'{stem}_{b}.json',{'batch':b.upper(),'records':{}})
            self.put(f'semantic_queue_{b}.json',{'batch':b.upper(),'records':[],'pending_count':0})
        self.evidence()

    def put(self, name, obj): ps.atomic_json(self.root/name,{'version':'1.0',**obj})
    def get(self, name): return ps.load(name,root=self.root)
    def evidence(self):
        token = ps.snapshot(self.root)
        self.put('daily_activity.json',{'batches':{b.upper():{'snapshot':token,'searches':[{'query':'official fixture search','checked_at':'2026-10-03','source_url':'https://official.example','result':'No new vacancy'}],'discoveries':[]} for b in ps.BATCHES}})
    def run(self): return subprocess.run([sys.executable,str(self.root/'job_watch.py'),'sync'],capture_output=True,text=True)
    @contextlib.contextmanager
    def modules(self):
        with contextlib.ExitStack() as stack:
            for m in (ps,job_watch,collector,reconcile,daily_worklist,sync,audit,cert,enrich,validate): stack.enter_context(patch.object(m,'ROOT',self.root))
            stack.enter_context(patch.object(amazon,'OUTPUT',self.root/'amazon_target_check.json'))
            yield


class Resilience(unittest.TestCase):
    def setUp(self): self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.f=Fixture(self.root)
    def tearDown(self): self.tmp.cleanup()

    def test_absent_persisted_euronext_role_is_local_and_all_stages_continue(self):
        mapped={'company':'Euronext','ats':{'family':'Workday','inventory_url':'https://euronext.wd3.myworkdayjobs.com/Careers','career_site':'https://www.euronext.com/careers'}}
        data=self.f.get('current_jobs_jw1.json');data['companies'].append({'company':'Euronext','coverage':'VERIFIED','jobs':[]});data['summary']['VERIFIED']+=1;self.f.put('current_jobs_jw1.json',data)
        self.f.put('ats_mapping_jw1.json',{'batch':'JW1','companies':[mapped]})
        self.f.put('user_job_decisions.json',{'records':{'Euronext::R27644':{'decision':'TO_REVIEW','decided_at':'2026-10-01'}}})
        self.f.put('externally_validated_roles.json',{'records':{'Euronext::R27644':{'validation_method':reconcile.CORPORATE_LISTING_METHOD,'title':'Business Analyst','location':'Milan','canonical_url':'https://euronext.wd3.myworkdayjobs.com/Careers/job/Milan/Business-Analyst_R27644','official_listing_url':'https://www.euronext.com/careers'}}})
        called=[]
        def collect(b): called.append(b);return self.f.get(f'current_jobs_{b}.json')
        with self.f.modules(), patch.object(collector,'collect_batch',side_effect=collect), patch.object(reconcile,'enumerate_workday',return_value=([],'euronext.wd3.myworkdayjobs.com','Careers','https://official.example')), patch.object(reconcile,'targeted_workday_search',return_value=([],'euronext.wd3.myworkdayjobs.com','Careers',None)), patch.object(reconcile,'get_html',return_value=('<html>Vacancy no longer listed</html>','https://www.euronext.com/careers')), patch.object(amazon,'main') as amz:
            with ps.writer_lock(self.root): self.assertTrue(job_watch.stage('collect'))
        self.assertEqual(called,list(ps.BATCHES));amz.assert_called_once()
        row=self.f.get('current_jobs_jw1.json')['companies'][-1]['jobs'][0]
        self.assertEqual(row['status'],'UNKNOWN');self.assertEqual(row['reconciliation_state'],'UNRESOLVED')
        errors=self.f.get('job_watch_healthcheck.json')['errors']
        self.assertTrue(any(e['scope']=='record' and e.get('job_key')=='Euronext::R27644' for e in errors))
        self.assertFalse(any(e['scope']=='global' for e in errors))
        self.assertEqual(self.f.get('user_job_decisions.json')['records']['Euronext::R27644']['decision'],'TO_REVIEW')

    def test_static_integrity_rejects_missing_script_test_and_invalid_enum(self):
        workflows=self.root/'.github/workflows';workflows.mkdir(parents=True)
        (workflows/'broken.yml').write_text('run: |\n  python reconcile_external_lifecycle.py\n  python -m unittest test_removed.Test\n  status = "INVENTED"\n')
        errors=preflight.validate(self.root)
        self.assertTrue(any('reconcile_external_lifecycle.py' in e for e in errors));self.assertTrue(any('test_removed' in e for e in errors))
        self.f.put('pipeline_contract.json',{'states':['INVALID']});self.assertTrue(any('invalid states' in e for e in preflight.validate(self.root)))
        (self.root/'collector.py').unlink();self.assertTrue(any('missing entrypoint collector.py' in e for e in preflight.validate(self.root)))

    def test_failed_source_preserves_unknown_and_collects_other_sources(self):
        members=[{'company':'Broken'},{'company':'Healthy'}]
        self.f.put('ats_mapping_jw3.json',{'batch':'JW3','companies':members})
        old={'source_id':'1','title':'Analyst','location':'Milan','status':'STILL_OPEN','fingerprint':'abc','canonical_url':'https://official.example/1'}
        self.f.put('current_jobs_jw3.json',{'batch':'JW3','companies':[{'company':'Broken','jobs':[old]}]})
        def adapter(c):
            if c['company']=='Broken': raise ConnectionError('ATS down')
            return {'coverage':'VERIFIED','collector':'mock','inventory_count':0,'jobs':[]}
        with self.f.modules(), patch.object(collector,'choose',return_value=adapter): payload=collector.collect_batch('jw3')
        self.assertEqual([c['coverage'] for c in payload['companies']],['FAILED','VERIFIED'])
        self.assertEqual(payload['companies'][0]['jobs'][0]['status'],'UNKNOWN')
        self.assertTrue((self.root/'current_jobs_jw3.json').exists())
        self.f.evidence();result=self.f.run();self.assertEqual(result.returncode,0,result.stderr)
        health=self.f.get('job_watch_healthcheck.json');self.assertEqual(health['batches']['JW3']['status'],'COMPLETE_WITH_WARNINGS')
        self.assertEqual(health['error_counts']['global'],0)

    def test_partial_priority_certifies_with_warning_and_backlog_does_not_block(self):
        current=self.f.get('current_jobs_jw1.json');current['companies'][-1]['coverage']='PARTIAL';current['summary'].update(VERIFIED=1,PARTIAL=1);self.f.put('current_jobs_jw1.json',current)
        current=self.f.get('current_jobs_jw3.json');current['companies'][0]['jobs']=[{'source_id':'old','title':'Business Analyst','location':'Milan','fingerprint':'abc','status':'STILL_OPEN','canonical_url':'https://official.example/old'}];current['summary']['target_jobs_open']=1;self.f.put('current_jobs_jw3.json',current)
        self.f.put('analysis_results_jw3.json',{'batch':'JW3','records':{'JW3::old':{'company':'JW3','source_id':'old','fingerprint':'abc','current_open':True,'current_status':'STILL_OPEN','needs_analysis':True,'first_seen_at':'2025-01-01'}}})
        self.f.evidence();result=self.f.run();self.assertEqual(result.returncode,0,result.stderr)
        health=self.f.get('job_watch_healthcheck.json')
        self.assertTrue(health['DAILY_COMPLETE']);self.assertFalse(health['FULL_SEMANTIC_COMPLETE']);self.assertEqual(health['historical_backlog_remaining'],1)
        self.assertEqual(health['daily_actionable_remaining'],0);self.assertEqual(health['priority_checks']['Mastercard'],'PARTIAL')
        self.assertEqual(health['status'],'COMPLETE_WITH_WARNINGS')

    def test_snapshot_change_at_commit_reloads_without_any_stale_write(self):
        current=self.f.get('current_jobs_jw3.json');current['companies'][0]['jobs']=[{'source_id':'1','title':'Business Analyst','location':'Milan','fingerprint':'abc','status':'NEW','canonical_url':'https://official.example/1'}];current['summary']['target_jobs_open']=1;self.f.put('current_jobs_jw3.json',current)
        self.f.run()
        token=self.f.get('daily_worklist.json')['snapshot']
        self.f.put('daily_updates.json',{'snapshot':token,'semantic_decisions':{'jw3':{'JW3::1':full_decision()}}})
        before=(self.root/'semantic_decisions_jw3.json').read_bytes()
        original=ps.transaction
        def race(*args,**kwargs):
            self.f.put('job_watch_rules.json',{'run_certification_policy':{'enabled':True},'changed':True})
            return original(*args,**kwargs)
        with self.f.modules(),patch.object(ps,'transaction',side_effect=race):
            with self.assertRaises(SystemExit): job_watch.apply_updates()
        self.assertEqual(before,(self.root/'semantic_decisions_jw3.json').read_bytes());self.assertTrue((self.root/'daily_updates.json').exists())
        result=self.f.run();self.assertEqual(result.returncode,0,result.stderr)
        self.assertNotEqual(token,self.f.get('daily_worklist.json')['snapshot'])
        self.assertFalse(self.f.get('job_watch_healthcheck.json')['DAILY_COMPLETE'])

    def test_two_real_sync_processes_merge_once_and_are_idempotent(self):
        self.f.run();token=self.f.get('daily_worklist.json')['snapshot']
        self.f.put('daily_updates.json',{'snapshot':token,'activity':{b.upper():{'searches':[{'query':'second search','checked_at':'2026-10-03','source_url':'https://official.example','result':'none'}],'discoveries':[]} for b in ps.BATCHES}})
        procs=[subprocess.Popen([sys.executable,str(self.root/'job_watch.py'),'sync'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True) for _ in range(2)]
        for proc in procs:
            out,err=proc.communicate(timeout=30);self.assertEqual(proc.returncode,0,out+err)
        self.assertFalse((self.root/'daily_updates.json').exists())
        self.assertTrue(self.f.get('job_watch_healthcheck.json')['DAILY_COMPLETE'])
        before={p.name:p.read_bytes() for p in self.root.glob('*.json')}
        self.assertEqual(self.f.run().returncode,0)
        after={p.name:p.read_bytes() for p in self.root.glob('*.json')}
        self.assertEqual([k for k in before if before[k] != after.get(k)],[],[(k,json.loads(before[k]),json.loads(after[k])) for k in before if before[k] != after.get(k)])

    def test_missing_reconcile_runtime_does_not_discard_collection_or_skip_amazon(self):
        # Import failure is scoped to that stage, while CI separately rejects it.
        called=[];original=job_watch.invoke
        def invoke(module,function,*args):
            if module=='reconcile_workday_target_paths': raise ModuleNotFoundError('removed')
            if module=='collector': called.append(args[0]);return {}
            if module=='amazon_target_check': called.append('Amazon');return None
            return original(module,function,*args)
        with self.f.modules(),patch.object(job_watch,'invoke',side_effect=invoke):
            with ps.writer_lock(self.root): self.assertTrue(job_watch.stage('collect'))
        self.assertEqual(called,[*ps.BATCHES,'Amazon'])
        self.assertEqual(self.f.get('job_watch_healthcheck.json')['error_counts']['batch'],4,(self.f.get('job_watch_healthcheck.json')['errors'],self.f.get('analysis_results_jw1.json').get('summary')))
        self.assertTrue(all((self.root/f'current_jobs_{b}.json').exists() for b in ps.BATCHES))

    def test_replayed_consumed_patch_cannot_overwrite_newer_user_choice(self):
        current=self.f.get('current_jobs_jw3.json');current['companies'][0]['jobs']=[{'source_id':'1','title':'Business Analyst','location':'Milan','fingerprint':'abc','status':'NEW','canonical_url':'https://official.example/1'}];current['summary']['target_jobs_open']=1;self.f.put('current_jobs_jw3.json',current)
        self.f.run();token=self.f.get('daily_worklist.json')['snapshot']
        command={'snapshot':token,'user_decisions':{'JW3::1':{'decision':'TO_REVIEW','fingerprint':'abc','decided_at':'2026-10-03T07:00:00Z'}}}
        self.f.put('daily_updates.json',command);self.assertEqual(self.f.run().returncode,0)
        users=self.f.get('user_job_decisions.json');users['records']['JW3::1'].update(decision='INTERESTED',decided_at='2026-10-03T08:00:00Z');self.f.put('user_job_decisions.json',users)
        # A second queued checkout still carries the original command.
        self.f.put('daily_updates.json',command);result=self.f.run();self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(self.f.get('user_job_decisions.json')['records']['JW3::1']['decision'],'INTERESTED')
        self.assertEqual(len(self.f.get('daily_activity.json')['applied_update_ids']),1)

    def test_global_rules_corruption_blocks_truth_without_mutating_sources(self):
        before=(self.root/'current_jobs_jw3.json').read_bytes()
        (self.root/'job_watch_rules.json').write_text('{invalid')
        result=self.f.run();self.assertNotEqual(result.returncode,0)
        health=self.f.get('job_watch_healthcheck.json')
        self.assertEqual(health['status'],'BLOCKED_GLOBAL');self.assertEqual(set(health['batches']),{'JW1','JW2','JW3','JW4'})
        self.assertEqual(before,(self.root/'current_jobs_jw3.json').read_bytes())
        self.assertIn('job_watch_rules.json',(self.root/'job_watch_summary.txt').read_text())

    def test_malformed_ats_row_keeps_jobs_before_and_after_it(self):
        mapped={'company':'JW3','ats':{'family':'Workday','inventory_url':'https://test.wd3.myworkdayjobs.com/Careers'}}
        page={'total':3,'jobPostings':[{'externalPath':'/job/Milan/Analyst_R10001','title':'Analyst','locationsText':'Milan'},None,{'externalPath':'/job/Milan/Analyst_R10002','title':'Analyst','locationsText':'Milan'}]}
        with self.f.modules(),patch.object(collector,'post_json',return_value=page),patch.object(collector,'choose',return_value=collector.collect_workday):
            result,_=collector.collect_company(mapped)
        self.assertEqual(result['coverage'],'PARTIAL');self.assertEqual([j['source_id'] for j in result['jobs']],['R10001','R10002'])
        self.assertEqual(len(result['record_errors']),1)

    def test_adapter_failure_after_valid_job_preserves_observed_progress(self):
        def adapter(company):
            collector.compact_job(company['company'],'1',title='Business Analyst',location='Milan',canonical='https://official.example/1')
            raise ConnectionError('Later detail endpoint failed')
        with self.f.modules(),patch.object(collector,'choose',return_value=adapter): result,_=collector.collect_company({'company':'JW3'})
        self.assertEqual(result['coverage'],'PARTIAL');self.assertEqual(len(result['jobs']),1)

    def test_batch_failure_does_not_skip_other_collections_or_priority(self):
        calls=[]
        def collect(b):
            calls.append(b)
            if b=='jw1': raise ValueError('JW1 mapping unavailable')
            return self.f.get(f'current_jobs_{b}.json')
        with self.f.modules(),patch.object(collector,'collect_batch',side_effect=collect),patch.object(amazon,'main') as amz:
            with ps.writer_lock(self.root): self.assertTrue(job_watch.stage('collect'))
        self.assertEqual(calls,list(ps.BATCHES));amz.assert_called_once()
        health=self.f.get('job_watch_healthcheck.json')
        self.assertEqual(health['batches']['JW1']['status'],'NEEDS_REVIEW')
        self.assertFalse(any(t['action']=='REPAIR_BATCH_STATE' for t in health['batches']['JW3']['remaining_work']))
        self.assertEqual(health['error_counts']['global'],0)

    def test_migration_and_crash_recovery_are_idempotent_preserve_claim_history(self):
        old={'run_id':'legacy','batches':{'JW1':{'semantic_delta_complete':False}},'source_generated_at':{},'priority_checks':{'Amazon':False}}
        self.f.put('job_watch_run_state.json',old)
        ps.refresh_run_state(self.root);first=(self.root/'daily_activity.json').read_bytes();ps.refresh_run_state(self.root)
        self.assertEqual(first,(self.root/'daily_activity.json').read_bytes());self.assertEqual(self.f.get('daily_activity.json')['legacy_run_state']['run_id'],'legacy')
        ps.atomic_json(self.root/'.job_watch.transaction.json',{'writes':{'new.json':{'records':{'kept':1}}},'remove':[]})
        with ps.writer_lock(self.root): pass
        self.assertEqual(self.f.get('new.json'),{'records':{'kept':1}})

    def test_invalid_single_semantic_patch_keeps_valid_other_updates(self):
        self.f.run();token=self.f.get('daily_worklist.json')['snapshot']
        self.f.put('daily_updates.json',{'snapshot':token,'semantic_decisions':{'jw3':{'JW3::dirty':{'fingerprint':'bad'}}},'activity':{'JW3':{'searches':[{'query':'real test','checked_at':'2026-10-03','source_url':'https://official.example','result':'none'}],'discoveries':[]}}})
        result=self.f.run();self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(self.f.get('daily_activity.json')['batches']['JW3']['searches'][0]['query'],'real test')
        self.assertTrue((self.root/'rejected_daily_updates.json').exists());self.assertEqual(self.f.get('semantic_decisions_jw3.json')['records'],{})


if __name__=='__main__': unittest.main()
