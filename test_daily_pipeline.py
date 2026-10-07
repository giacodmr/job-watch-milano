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
        self.assertTrue(collector.location_matches('London, United Kingdom','Mastercard'))
        self.assertTrue(collector.location_matches('Luxembourg','Mastercard'))
        self.assertFalse(collector.location_matches('Luxembourg','Ordinary Co'))

    def test_workday_pagination_and_canonical_id(self):
        mapped={'company':'Mastercard','ats':{'inventory_url':'https://test.wd3.myworkdayjobs.com/Careers'}}
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


class RealPipeline(unittest.TestCase):
    def test_persisted_certification_and_preflight_fail_closed(self):
        from test_pipeline_resilience import Fixture
        from job_memory import record_surface
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);fixture=Fixture(root)
            for b in daily_worklist.BATCHES:
                current=fixture.get(f'current_jobs_{b}.json')
                rec={'company':b.upper(),'source_id':'1','title':'Business Analyst','location':'Milan','fingerprint':'abc','status':'NEW','canonical_url':f'https://official.example/{b}/1'}
                current['companies'][0]['jobs']=[rec];current['summary']['target_jobs_open']=1
                fixture.put(f'current_jobs_{b}.json',current)
                mem={'identity':rec,'semantic':full_decision()}
                record_surface(mem,{'fingerprint':'abc','surfaced_at':'2026-10-03T08:00:00Z','surfaced_status':'NEW'},rec)
                fixture.put(f'job_memory_{b}.json',{'batch':b.upper(),'records':{f'{b.upper()}::1':mem}})
            fixture.run();fixture.evidence()
            result=fixture.run();self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertTrue(fixture.get('job_watch_healthcheck.json')['DAILY_COMPLETE'])
            first=(root/'daily_worklist.json').read_bytes();self.assertEqual(fixture.run().returncode,0);self.assertEqual(first,(root/'daily_worklist.json').read_bytes())
            mem=fixture.get('job_memory_jw3.json');mem['records']['JW3::1']['semantic']['fingerprint']='wrong';fixture.put('job_memory_jw3.json',mem)
            self.assertEqual(fixture.run().returncode,0)
            self.assertFalse(fixture.get('job_watch_healthcheck.json')['DAILY_COMPLETE'])
            current=fixture.get('current_jobs_jw3.json');current['companies'][0]['jobs'][0].update(fingerprint='changed',status='UPDATED',title='Strategy Analyst');fixture.put('current_jobs_jw3.json',current)
            mem['records']['JW3::1']['semantic']=full_decision('changed');fixture.put('job_memory_jw3.json',mem)
            self.assertEqual(fixture.run().returncode,0)
            self.assertFalse(fixture.get('job_watch_audit.json')['batches']['JW3']['checks']['actionable_reporting_reconciliation'])
            record_surface(mem['records']['JW3::1'],{'fingerprint':'changed','surfaced_at':'2026-10-03T08:01:00Z','surfaced_status':'UPDATED'},current['companies'][0]['jobs'][0]);fixture.put('job_memory_jw3.json',mem)
            fixture.evidence();self.assertEqual(fixture.run().returncode,0)
            self.assertTrue(fixture.get('job_watch_healthcheck.json')['DAILY_COMPLETE'])
            workflow=root/'.github/workflows';workflow.mkdir(parents=True);(workflow/'bad.yml').write_text('run: python removed_script.py')
            self.assertTrue(any('removed_script' in e for e in preflight.validate(root)))
            fixture.put('job_watch_batches.json',{'batches':{}});self.assertTrue(any('JW1-JW4' in e for e in preflight.validate(root)))
            (root/'job_watch_rules.json').write_text('{invalid');self.assertTrue(any('invalid JSON' in e for e in preflight.validate(root)))

if __name__=='__main__': unittest.main()
