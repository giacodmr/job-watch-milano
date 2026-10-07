"""Failure-mode regressions: real sync persistence and mocked official ATS contracts."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import collector
import daily_worklist
import harden_job_watch_state as harden
import preflight_job_watch as preflight
import sync_analysis_state as sync
import job_watch
from rejection_reasons import infer_rejection_reason, reason_is_vague
import test_job_watch_guardrails as guardrails


def full_decision(fp='abc'):
    row = guardrails.GuardrailTests().base_decision()
    row.update(fingerprint=fp, analysis_method='chatgpt_semantic_full_jd', mandatory_years_experience=5,
               preferred_years_experience=7, experience_required='5 mandatory; 7 preferred', salary='Undisclosed')
    return row


class RulesAndATS(unittest.TestCase):
    def test_m_and_a_only_in_title_and_never_generic_seniority(self):
        for title in ['M&A Analyst', 'Strategy M & A Manager', 'm&amp;a consulting']:
            self.assertEqual(sync.hard_exclusion_reason(title), 'm_and_a_title_user_exclusion')
        for title in ['Manager Business Analysis', 'Senior Strategy Analyst', 'Lead Business Operations', 'Finance Business Partner']:
            self.assertIsNone(sync.hard_exclusion_reason(title))
        self.assertEqual(sync.hard_exclusion_reason('Finance Internship'), 'internship')

    def test_documented_salary_cap_only(self):
        evidence={'fixed_base_max_eur':32999,'fixed_base_documented':True,'fixed_base_source_url':'https://official.example/job'}
        self.assertTrue(sync.salary_below_floor(evidence))
        for change in [{'fixed_base_max_eur':33000},{'fixed_base_max_eur':None},{'fixed_base_documented':False},{'fixed_base_source_url':None}]:
            self.assertFalse(sync.salary_below_floor({**evidence, **change}))
        self.assertFalse(sync.salary_below_floor({'salary':'€31,100 minimum with higher pay possible'}))

    def test_full_review_allows_five_mandatory_seven_preferred(self):
        for title in ['Manager Business Analysis','Senior Analyst','Lead Strategy']:
            self.assertTrue(harden.semantic_decision_valid(full_decision(),{'title':title,'fingerprint':'abc'})[0])

    def test_priority_and_protected_guards(self):
        for status in ['PREFERRED','INVITED','AMBIGUOUS','REQUIRED','RESERVED']:
            row=full_decision();row.update(l68_status=status,ordinary_twin_found=False,reportable=status not in {'REQUIRED','RESERVED'})
            self.assertTrue(harden.semantic_decision_valid(row,{'title':'Business Analyst','fingerprint':'abc'})[0])
            row['analysis_method']='chatgpt_semantic_title_metadata'
            self.assertFalse(harden.semantic_decision_valid(row,{'title':'Business Analyst','fingerprint':'abc'})[0])
        for title in ['Manager','Senior Analyst','Lead Analyst','Protected Categories Analyst']:
            self.assertFalse(sync.decision_valid(guardrails.GuardrailTests().base_decision(),'abc',title=title))
        self.assertFalse(sync.decision_valid(guardrails.GuardrailTests().base_decision(),'abc',title='Business Analyst',priority_company=True))

    def test_lightweight_triage_is_narrow_and_validators_agree(self):
        row={'analysis_method':'chatgpt_semantic_triage','fingerprint':'abc','analysis_status':'ANALYZED',
             'decision':'REJECT','reason':'TOO_TECHNICAL','rationale':'Backend software implementation is the core function.', 'analyzed_at':'2026-10-03T07:00:00Z'}
        self.assertTrue(sync.decision_valid(row,'abc',title='Backend Developer'))
        for title in ['Senior Developer','Protected Categories Developer']:
            self.assertFalse(sync.decision_valid(row,'abc',title=title))
        self.assertFalse(sync.decision_valid(row,'changed',title='Backend Developer'))
        self.assertFalse(sync.decision_valid({**row,'reason':'TOO_SENIOR'},'abc',title='Analyst'))

    def test_geography_and_priority_luxembourg(self):
        for loc in ['London, KY','London, Ontario','London, Canada','Milan, TN, US','Rome, GA, USA','Paris']:
            self.assertFalse(collector.location_matches(loc))
        self.assertTrue(collector.location_matches('London, United Kingdom'))
        self.assertTrue(collector.location_matches('Luxembourg','Mastercard'))
        self.assertFalse(collector.location_matches('Luxembourg','Ordinary Co'))

    def test_workday_pagination_and_canonical_id(self):
        mapped={'company':'Test','ats':{'inventory_url':'https://test.wd3.myworkdayjobs.com/Careers'}}
        pages=[{'total':2,'jobPostings':[{'externalPath':'/job/Milan/Analyst_R12345','title':'Analyst','locationsText':'Milan'}]},
               {'total':2,'jobPostings':[{'externalPath':'/job/London/Analyst_R12346','title':'Analyst','locationsText':'London'}]}]
        with patch.object(collector,'post_json',side_effect=pages) as req:
            result=collector.collect_workday(mapped)
        self.assertEqual(result['coverage'],'VERIFIED');self.assertEqual({j['source_id'] for j in result['jobs']},{'R12345','R12346'})
        self.assertEqual([c.args[1]['offset'] for c in req.call_args_list],[0,1])
        self.assertEqual(result['jobs'][0]['canonical_url'],'https://test.wd3.myworkdayjobs.com/Careers/job/Milan/Analyst_R12345')
        with patch.object(collector,'post_json',side_effect=[pages[0],{'total':2,'jobPostings':[]}]*2):
            result=collector.collect_workday(mapped)
            self.assertEqual(result['coverage'],'PARTIAL');self.assertEqual(len(result['jobs']),1)

    def test_unknown_survives_repeated_partial_and_closes_only_when_verified(self):
        old=collector.compact_job('Test','1',title='Analyst',location='Milan',canonical='https://official.example/1')
        old['status']='UNKNOWN'
        company={'company':'Test'};result={'coverage':'PARTIAL','jobs':[],'collector':'mock','inventory_count':None}
        current,_=collector.reconcile_company(company,result,{'Test::1':old})
        self.assertEqual(current['jobs'][0]['status'],'UNKNOWN')
        current,_=collector.reconcile_company(company,{**result,'coverage':'VERIFIED'},{'Test::1':old})
        self.assertEqual(current['jobs'][0]['status'],'CLOSED')

    def test_rejection_feedback_is_not_a_filter(self):
        self.assertEqual(infer_rejection_reason('Troppo senior per me'),'TOO_SENIOR')
        self.assertEqual(infer_rejection_reason('Contratto a tempo determinato'),'FIXED_TERM')
        for phrase in ['scarta','no','togli','non mi interessa']:
            self.assertTrue(reason_is_vague(phrase));self.assertIsNone(infer_rejection_reason(phrase))
        self.assertIsNone(sync.hard_exclusion_reason('Senior Business Analyst'))


class PersistedDelta(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.patches=[patch.object(m,'ROOT',self.root) for m in (sync,daily_worklist,job_watch)]
        for p in self.patches:p.start()
        self.put('job_watch_rules.json',{'daily_worklist_policy':{'backlog_limit':1}})
        self.put('job_watch_run_state.json',{'run_id':'run','source_generated_at':{'JW3':'2026-10-03T06:30:00Z'}})
        for b in daily_worklist.BATCHES:
            self.put(f'analysis_results_{b}.json',{'records':{}})
            self.put(f'semantic_jd_cache_{b}.json',{'records':{}})
        self.put('semantic_decisions_jw3.json',{'records':{}});self.put('surfaced_jobs_jw3.json',{'records':{}})
        self.put('user_job_decisions.json',{'records':{}})
        self.job={'source_id':'1','title':'Business Analyst','location':'Milan','fingerprint':'abc','status':'NEW','canonical_url':'https://official.example/1'}
        self.snapshot()

    def tearDown(self):
        for p in reversed(self.patches):p.stop()
        self.tmp.cleanup()

    def put(self,name,data): (self.root/name).write_text(json.dumps(data))
    def get(self,name): return json.loads((self.root/name).read_text())
    def snapshot(self): self.put('current_jobs_jw3.json',{'generated_at':'2026-10-03T06:30:00Z','companies':[{'company':'Test','jobs':[self.job]}]})
    def sync(self):
        sync.sync_batch('jw3')
        return self.get('analysis_results_jw3.json')['records']['Test::1']

    def test_delta_survives_rollover_and_decision_reuse(self):
        self.assertTrue(self.sync()['needs_analysis'])
        self.job['status']='STILL_OPEN';self.snapshot()
        self.assertTrue(self.sync()['delta_pending'])
        self.put('semantic_decisions_jw3.json',{'records':{'Test::1':full_decision()}})
        self.put('surfaced_jobs_jw3.json',{'records':{'Test::1':{'fingerprint':'abc','surfaced_at':'2026-10-03T08:00:00Z','surfaced_status':'NEW'}}})
        row=self.sync();self.assertFalse(row['needs_analysis']);self.assertIsNone(daily_worklist.action_reason(row))
        self.put('semantic_jd_cache_jw3.json',{'records':{'Test::1':{'status':'OK','fingerprint':'old','text':'stale'}}})
        self.assertEqual(daily_worklist.build_worklist()['records'],[])
        self.job['fingerprint']='changed';self.snapshot();self.assertTrue(self.sync()['needs_analysis'])
        self.assertEqual(daily_worklist.build_worklist()['summary']['daily_semantic_pending'],1)

    def test_user_states_persist_and_not_interested_reopens_on_material_change(self):
        for status in ['TO_REVIEW','INTERESTED','APPLIED','NOT_INTERESTED']:
            self.put('user_job_decisions.json',{'records':{'Test::1':{'decision':status,'fingerprint':'abc','reason':'Explicit choice','decided_at':'2026-10-03T07:00:00Z'}}})
            self.job.update(fingerprint='abc',status='STILL_OPEN');self.snapshot();row=self.sync()
            self.assertEqual(row['user_decision'],status)
            self.assertEqual(bool(daily_worklist.action_reason(row)),status in {'TO_REVIEW','INTERESTED'})
        self.job['fingerprint']='changed';self.snapshot();row=self.sync()
        self.assertTrue(row['user_decision_stale']);self.assertTrue(row['needs_analysis'])
        self.assertEqual(self.get('user_job_decisions.json')['records']['Test::1']['decision'],'NOT_INTERESTED')

    def test_applied_material_change_stays_actionable_until_reported(self):
        self.put('user_job_decisions.json',{'records':{'Test::1':{'decision':'APPLIED','fingerprint':'abc','decided_at':'2026-10-03T07:00:00Z'}}})
        self.sync();self.job.update(fingerprint='changed',status='UPDATED');self.snapshot()
        self.assertTrue(self.sync()['needs_analysis'])
        self.job['status']='STILL_OPEN';self.snapshot();row=self.sync()
        self.assertEqual(daily_worklist.action_reason(row),'APPLIED_UPDATE')
        self.put('semantic_decisions_jw3.json',{'records':{'Test::1':full_decision('changed')}})
        self.assertFalse(self.sync()['needs_analysis'])
        self.assertEqual(daily_worklist.build_worklist()['records'][0]['action'],'APPLIED_UPDATE')
        self.put('surfaced_jobs_jw3.json',{'records':{'Test::1':{'fingerprint':'changed','surfaced_at':'today','surfaced_status':'UPDATED'}}})
        self.assertIsNone(daily_worklist.action_reason(self.sync()))

    def test_backlog_is_bounded_stable_and_cache_fingerprint_checked(self):
        rows={f'Test::{i}':{'company':'Test','current_open':True,'current_status':'STILL_OPEN','needs_analysis':True,'fingerprint':str(i),'first_seen_at':str(i)} for i in range(3)}
        self.put('analysis_results_jw3.json',{'records':rows})
        self.put('semantic_jd_cache_jw3.json',{'records':{'Test::0':{'fingerprint':'wrong','status':'OK','text':'stale'}}})
        work=daily_worklist.build_worklist();self.assertEqual(len(work['records']),1);self.assertNotIn('jd',work['records'][0]);self.assertEqual(work['summary']['daily_semantic_pending'],0)
        self.put('daily_worklist.json',work);rows['Test::0'].update(needs_analysis=False,reportable=False);self.put('analysis_results_jw3.json',{'records':rows})
        next_work=daily_worklist.build_worklist();self.assertEqual(len(next_work['records']),1);self.assertEqual(next_work['records'][0]['job_key'],'Test::1');self.assertEqual(next_work['backlog_assignment'],['Test::1'])

    def test_lifecycle_notice_is_not_repeated_after_reporting(self):
        self.put('user_job_decisions.json',{'records':{'Test::1':{'decision':'APPLIED','fingerprint':'abc','decided_at':'today'}}})
        self.sync();self.job['status']='CLOSED';self.snapshot();self.sync()
        self.assertEqual(len(daily_worklist.build_worklist()['lifecycle_updates']),1)
        self.put('surfaced_jobs_jw3.json',{'records':{'Test::1':{'fingerprint':'abc','surfaced_status':'CLOSED','surfaced_at':'today'}}})
        self.assertEqual(daily_worklist.build_worklist()['lifecycle_updates'],[])

    def test_small_patch_merges_history_and_rejects_stale_snapshot(self):
        self.sync()
        # Fill unrelated batch registries required by the merge protocol.
        for b in daily_worklist.BATCHES:
            if b != 'jw3':
                self.put(f'current_jobs_{b}.json',{'generated_at':None})
                self.put(f'semantic_decisions_{b}.json',{'records':{}})
                self.put(f'surfaced_jobs_{b}.json',{'records':{}})
        self.put('amazon_target_check.json',{'checked_at':None})
        self.put('semantic_decisions_jw3.json',{'records':{'Historical::0':full_decision('old')}})
        work=daily_worklist.build_worklist()
        update={'version':'1.0','snapshot':work['snapshot'], 'semantic_decisions':{'jw3':{'Test::1':full_decision()}},
                'user_decisions':{'Test::1':{'decision':'NOT_INTERESTED','fingerprint':'abc','reason':'Troppo senior','decided_at':'2026-10-03T08:00:00Z'}}}
        # Exact source map is required even for batches with no jobs.
        manifest=self.get('job_watch_run_state.json');manifest['source_generated_at'].update(JW1=None,JW2=None,JW4=None)
        self.put('job_watch_run_state.json',manifest)
        update['snapshot']=daily_worklist.build_worklist()['snapshot']
        self.put('daily_updates.json',{**update,'snapshot':{}})
        before=(self.root/'semantic_decisions_jw3.json').read_bytes()
        with self.assertRaises(SystemExit):job_watch.apply_updates()
        self.assertEqual(before,(self.root/'semantic_decisions_jw3.json').read_bytes())
        self.put('daily_updates.json',update);self.assertTrue(job_watch.apply_updates())
        self.assertFalse((self.root/'daily_updates.json').exists())
        self.assertEqual(set(self.get('semantic_decisions_jw3.json')['records']),{'Historical::0','Test::1'})
        self.assertEqual(self.get('user_job_decisions.json')['records']['Test::1']['rejection_reason'],'TOO_SENIOR')


class RealPipeline(unittest.TestCase):
    def test_persisted_certification_and_preflight_fail_closed(self):
        # Small complete fixture executes the actual entry point, validators and persistence.
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=Path(__file__).resolve().parent
            for path in source.glob('*.py'):(root/path.name).write_bytes(path.read_bytes())
            def put(name,data):(root/name).write_text(json.dumps({"version":"1.0", **data}))
            companies=[{'company':b.upper()} for b in daily_worklist.BATCHES]
            put('companies_job_watch_v2.json',{'companies':companies})
            put('company_candidates.json',{'records':{},'promoted_history':{},'monitored_reviews':[]})
            put('job_watch_rules.json',{'run_certification_policy':{'enabled':True},'daily_worklist_policy':{'backlog_limit':0}})
            put('job_watch_batches.json',{'batches':{b.upper():{'companies':[b.upper()]} for b in daily_worklist.BATCHES}})
            put('user_job_decisions.json',{'records':{}})
            stamps={b.upper():'2026-10-03T06:30:00Z' for b in daily_worklist.BATCHES}
            manifest={'run_id':'fixture','completed_at':'2026-10-03T08:00:00Z','source_generated_at':stamps,
                      'priority_snapshot_at':{'Amazon':'2026-10-03T06:31:00Z'},'priority_checks':{'Amazon':True,'Mastercard':True},'blocking_errors':[],
                      'batches':{b.upper():{'semantic_delta_complete':True,'autonomous_search_complete':True,'priority_check_complete':True,
                      'autonomous_search_evidence':['fixture official search'],'priority_check_evidence':['fixture verified priority'],
                      'autonomous_delta_count':0,'autonomous_validated_count':0,'errors':[]} for b in daily_worklist.BATCHES}}
            put('job_watch_run_state.json',manifest)
            put('amazon_target_check.json',{'checked_at':manifest['priority_snapshot_at']['Amazon'],'target_jobs':[],
                'locations':{city:{'coverage':'VERIFIED','inventory_count':0,'api_reported_hits_sum':0} for city in ['Milan','Rome','London','Luxembourg']}})
            for b in daily_worklist.BATCHES:
                put(f'ats_mapping_{b}.json',{'batch':b.upper(),'companies':[{'company':b.upper()}]})
                job={'source_id':'1','title':'Business Analyst','location':'Milan','fingerprint':'abc','status':'NEW','canonical_url':f'https://official.example/{b}/1'}
                put(f'current_jobs_{b}.json',{'batch':b.upper(),'generated_at':stamps[b.upper()], 'summary':{'target_jobs_open':1,'VERIFIED':1},'companies':[{'company':b.upper(),'jobs':[job]}]+([{'company':'Mastercard','coverage':'VERIFIED','jobs':[]}] if b=='jw1' else [])})
                for stem in ['analysis_results','semantic_decisions','surfaced_jobs','semantic_jd_cache']:
                    records={f'{b.upper()}::1':full_decision()} if stem=='semantic_decisions' else {f'{b.upper()}::1':{'fingerprint':'abc','surfaced_at':'2026-10-03T08:00:00Z','surfaced_status':'NEW'}} if stem=='surfaced_jobs' else {}
                    put(f'{stem}_{b}.json',{'batch':b.upper(),'records':records})
                put(f'semantic_queue_{b}.json',{'batch':b.upper(),'records':[]})
            def run():return subprocess.run([sys.executable,str(root/'job_watch.py'),'sync'],capture_output=True,text=True)
            result=run();self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertTrue(json.loads((root/'job_watch_healthcheck.json').read_text())['DAILY_COMPLETE'])
            first=(root/'daily_worklist.json').read_bytes();self.assertEqual(run().returncode,0);self.assertEqual(first,(root/'daily_worklist.json').read_bytes())
            # Even a falsely-complete manifest cannot hide an invalid current fingerprint.
            decision=json.loads((root/'semantic_decisions_jw3.json').read_text());decision['records']['JW3::1']['fingerprint']='wrong';put('semantic_decisions_jw3.json',decision)
            self.assertEqual(run().returncode,0)
            self.assertFalse(json.loads((root/'job_watch_healthcheck.json').read_text())['DAILY_COMPLETE'])
            # A previous report is not proof that a materially updated vacancy was surfaced.
            current=json.loads((root/'current_jobs_jw3.json').read_text());current['companies'][0]['jobs'][0].update(fingerprint='changed',status='UPDATED');put('current_jobs_jw3.json',current)
            put('semantic_decisions_jw3.json',{'batch':'JW3','records':{'JW3::1':full_decision('changed')}})
            self.assertEqual(run().returncode,0)
            audit=json.loads((root/'job_watch_audit.json').read_text())['batches']['JW3']
            self.assertFalse(audit['checks']['actionable_reporting_reconciliation'])
            put('surfaced_jobs_jw3.json',{'batch':'JW3','records':{'JW3::1':{'fingerprint':'changed','surfaced_at':'2026-10-03T08:01:00Z','surfaced_status':'UPDATED'}}})
            from pipeline_state import snapshot
            put('daily_activity.json',{'batches':{b.upper():{'snapshot':snapshot(root),'searches':[{'query':'fixture','checked_at':'2026-10-03','source_url':'https://official.example','result':'none'}],'discoveries':[]} for b in daily_worklist.BATCHES}})
            result=run();self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertTrue(json.loads((root/'job_watch_healthcheck.json').read_text())['DAILY_COMPLETE'])
            workflow=root/'.github/workflows';workflow.mkdir(parents=True);(workflow/'bad.yml').write_text('run: python removed_script.py')
            self.assertTrue(any('removed_script' in e for e in preflight.validate(root)))
            put('job_watch_batches.json',{'batches':{}});self.assertTrue(any('JW1-JW4' in e for e in preflight.validate(root)))
            (root/'job_watch_rules.json').write_text('{invalid');self.assertTrue(any('invalid JSON' in e for e in preflight.validate(root)))


if __name__=='__main__':unittest.main()
