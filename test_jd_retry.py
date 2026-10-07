"""Finite, evidence-bound retries through the real bridge and projections."""
import copy
import json
from unittest.mock import patch
import unittest

import enrich_semantic_jds as enrich
import job_watch_bridge as bridge
import pipeline_state as ps
import semantic_worker as worker
import sync_analysis_state as sync
import daily_worklist as daily
import jd_retry
from job_memory import load_memory
import test_job_watch_bridge as fixtures
from test_daily_pipeline import full_decision


class JDRetryTests(unittest.TestCase):
    setUp = fixtures.BridgeTests.setUp
    tearDown = fixtures.BridgeTests.tearDown
    jobs = fixtures.BridgeTests.jobs
    run_apply = fixtures.BridgeTests.run_apply

    def select(self, day, name, n=1, failing=('0',), persist=True):
        def fetch(rec, mapping):
            if rec['source_id'] in failing:
                raise enrich.FetchError('HTTP 404')
            return 'Real fixture job description '*20, rec['canonical_url'], 'fixture'
        def command(args):
            token = worker.batch_snapshot('jw3',self.root)
            rows = enrich.fetch_candidates('jw3',n,self.root,fetch=True)
            return dict(batch='jw3',snapshot=token,records=rows)
        data = dict(version=bridge.VERSION,action='select',request_id=name,batch='jw3',limit=n,fetch=True)
        path = self.root/(name+'.packet.json')
        import os
        with patch.dict(os.environ,{'GITHUB_RUN_ID':'123','GITHUB_RUN_ATTEMPT':'1'}),patch.object(ps,'now',return_value=day),patch.object(bridge,'_run_json_command',side_effect=command),patch.object(enrich,'fetch_jd',side_effect=fetch) as fetcher:
            result = bridge.select(data,path,persist=persist)
        return data,path,result,fetcher.call_count

    def state(self):
        return load_memory('jw3',self.root)['records'].get('JW3::0',{}).get('jd_fetch')

    def test_four_failures_on_successive_days_then_terminal_even_after_time_passes(self):
        self.jobs(1)
        for attempt,day in enumerate(range(8,12),1):
            stamp=f'2026-10-{day:02}T00:00:00Z'
            data,path,result,calls=self.select(stamp,'day'+str(day))
            self.assertEqual(calls,1)
            state=self.state()
            self.assertEqual(state['attempts'],attempt)
            self.assertEqual(result['technical_retry']['JW3::0'],state)
            self.assertEqual(state['last_failure_at'],stamp)
            self.assertEqual(state['status'],'JD_UNAVAILABLE' if attempt==4 else 'RETRY_PENDING')
            self.assertEqual(state['retry_from'],None if attempt==4 else f'2026-10-{day+1:02}')
            self.assertNotIn('semantic',load_memory('jw3',self.root)['records']['JW3::0'])
            for suffix in ('later1','later2'):
                _,_,empty,calls=self.select(f'2026-10-{day:02}T04:00:00Z',f'day{day}{suffix}')
                self.assertEqual(calls,0)
                self.assertEqual(empty['status'],'EMPTY')
                self.assertEqual(self.state(),state)
        _,_,empty,calls=self.select('2027-05-01T02:00:00Z','months-later')
        self.assertEqual((empty['status'],calls),('EMPTY',0))
        rec=sync.project_batch('jw3',self.root,at='2027-05-01T02:00:00Z')['records']['JW3::0']
        self.assertTrue(rec['needs_analysis'])
        self.assertEqual(rec['analysis_status'],'PENDING')
        self.assertFalse(rec['worker_eligible'])

    def terminal(self):
        self.jobs(1)
        for day in range(8,12): self.select(f'2026-10-{day:02}T00:00:00Z','fail'+str(day))

    def test_new_fingerprint_or_source_resets_terminal_lifecycle(self):
        self.terminal()
        cur=self.f.get('current_jobs_jw3.json')
        cur['companies'][0]['jobs'][0]['fingerprint']='new-fingerprint'
        self.f.put('current_jobs_jw3.json',cur)
        _,_,_,calls=self.select('2026-10-11T01:00:00Z','new-fingerprint')
        self.assertEqual(calls,1)
        self.assertEqual(self.state()['attempts'],1)
        cur['companies'][0]['jobs'][0]['canonical_url']='https://official.example/reopened'
        self.f.put('current_jobs_jw3.json',cur)
        _,_,_,calls=self.select('2026-10-11T02:00:00Z','new-url')
        self.assertEqual(calls,1)
        self.assertEqual(self.state()['attempts'],1)
        self.assertEqual(self.state()['evidence']['source_url'],'https://official.example/reopened')

    def test_alias_does_not_reopen_same_failed_evidence(self):
        self.terminal()
        cur=self.f.get('current_jobs_jw3.json')
        cur['companies'][0]['jobs'][0]['source_id']='alias'
        self.f.put('current_jobs_jw3.json',cur)
        self.assertEqual(sync.project_batch('jw3',self.root)['queue'],[])
        _,_,_,calls=self.select('2026-10-12T00:00:00Z','alias')
        self.assertEqual(calls,0)

    def test_successful_retry_clears_technical_state_without_fabricated_review(self):
        self.jobs(1)
        self.select('2026-10-08T00:00:00Z','first')
        _,path,result,calls=self.select('2026-10-09T00:00:00Z','success',failing=())
        self.assertEqual(calls,1)
        self.assertEqual(result['ready_count'],1)
        self.assertIsNone(self.state())
        self.assertNotIn('semantic',load_memory('jw3',self.root)['records']['JW3::0'])
        self.assertEqual(json.loads(path.read_text())['snapshot'],worker.batch_snapshot('jw3',self.root))

    def test_failed_jd_keeps_user_surfacing_and_old_review_unchanged(self):
        self.jobs(1)
        row=dict(identity=dict(company='JW3',source_id='0',canonical_url='https://official.example/0'),
                 user=dict(decision='INTERESTED',decided_at='2026-10-07T10:00:00Z'),
                 surfacing=dict(first_surfaced_at='2026-10-07T10:00:00Z',last_surfaced_at='2026-10-07T10:00:00Z',surface_count=1),
                 semantic=full_decision('old-fingerprint'))
        self.f.put('job_memory_jw3.json',dict(batch='JW3',records={'JW3::0':row}))
        before=copy.deepcopy(row)
        self.select('2026-10-08T00:00:00Z','failure')
        actual=load_memory('jw3',self.root)['records']['JW3::0']
        self.assertEqual({k:actual[k] for k in before},before)
        work=daily.build_worklist(at='2026-10-08T03:00:00Z')
        self.assertEqual(next(r for r in work['records'] if r['job_key']=='JW3::0')['action'],'INTERESTED')

    def test_partial_8_valid_2_failed_and_next_packet_uses_fresh_state(self):
        self.jobs(12)
        data,path,result,calls=self.select('2026-10-08T00:00:00Z','partial',n=10,failing=('0','1'))
        packet=json.loads(path.read_text())
        self.assertEqual((result['ready_count'],calls),(8,10))
        self.assertEqual(packet['snapshot'],worker.batch_snapshot('jw3',self.root))
        req=dict(version=bridge.VERSION,action='apply',request_id='apply-partial',parent_request_id=data['request_id'],
                 select_run_id=123,batch='jw3',packet_sha256=result['packet_sha256'],
                 patch=dict(batch='jw3',snapshot=packet['snapshot'],semantic_decisions={r['job_key']:full_decision(r['fingerprint']) for r in packet['records'] if 'jd' in r}))
        with patch.object(ps,'now',return_value='2026-10-08T00:10:00Z'):
            applied=self.run_apply(req,path)
        self.assertEqual(applied['applied_count'],8)
        self.assertEqual(len(applied['retry']),2)
        self.assertFalse(any('semantic' in load_memory('jw3',self.root)['records'][f'JW3::{i}'] for i in (0,1)))
        _,second,next_result,calls=self.select('2026-10-08T00:15:00Z','second',n=10,failing=())
        self.assertEqual(calls,2)
        self.assertEqual(next_result['ready_count'],2)
        self.assertNotEqual(json.loads(second.read_text())['snapshot'],packet['snapshot'])
        self.assertTrue(set(next_result['job_keys']).isdisjoint(result['job_keys']))
        replay=self.run_apply(req,self.root/'missing-packet.json')
        self.assertEqual(replay['applied_count'],0)
        self.assertTrue(replay['replayed'])

    def test_artifact_upload_checkpoint_and_replay_count_failure_only_once(self):
        import os
        self.jobs(1)
        data,path,result,_=self.select('2026-10-08T00:00:00Z','upload',persist=False)
        self.assertIsNone(self.state())
        with patch.dict(os.environ,{'GITHUB_RUN_ID':'123','GITHUB_RUN_ATTEMPT':'1'}):
            saved=bridge.finalize_select(data,result,path,123)
            self.assertEqual(self.state()['attempts'],1)
            before=(self.root/'job_memory_jw3.json').read_bytes()
            replay=bridge.finalize_select(data,result,path,124)
        self.assertTrue(replay['replayed'])
        self.assertEqual(saved['snapshot'],worker.batch_snapshot('jw3',self.root))
        self.assertEqual(before,(self.root/'job_memory_jw3.json').read_bytes())
        with patch.object(bridge,'_run_json_command',side_effect=AssertionError('refetch')):
            self.assertTrue(bridge.select(data,self.root/'absent.json')['replayed'])

    def test_all_unavailable_queue_empty_does_not_mean_semantic_complete(self):
        import job_watch,certify_job_watch
        self.terminal()
        with patch.object(ps,'now',return_value='2026-10-12T02:00:00Z'):
            job_watch.project_state()
        work=self.f.get('daily_worklist.json')['summary']
        self.assertEqual(work['processable_semantic_pending'],0)
        self.assertEqual(work['jd_unavailable'],1)
        self.assertEqual(work['full_semantic_pending'],1)
        self.assertFalse(self.f.get('job_watch_healthcheck.json')['FULL_SEMANTIC_COMPLETE'])
        self.assertNotIn('semantic',load_memory('jw3',self.root)['records']['JW3::0'])

    def test_rome_day_boundary_and_dst(self):
        rec=dict(fingerprint='fp',canonical_url='https://official.example')
        state=jd_retry.failed(None,rec,'2026-10-08T22:30:00Z')
        self.assertEqual(state['retry_from'],'2026-10-10')
        self.assertFalse(jd_retry.eligible(state,rec,'2026-10-09T21:59:00Z'))
        self.assertTrue(jd_retry.eligible(state,rec,'2026-10-09T22:00:00Z'))
        for stamp in ('2026-03-28T23:30:00Z','2026-10-24T22:30:00Z'):
            s=jd_retry.failed(None,rec,stamp)
            self.assertEqual(s['attempts'],1)
            jd_retry.validate(s)

    def test_select_crash_after_memory_before_receipt_recovers_one_failure(self):
        import os
        self.jobs(1)
        data,path,result,_=self.select('2026-10-08T00:00:00Z','crash-select',persist=False)
        actual=ps.atomic_json
        def crash(target,value):
            if target==self.root/bridge.receipt_name(data): raise OSError('receipt write interrupted')
            return actual(target,value)
        with patch.dict(os.environ,{'GITHUB_RUN_ID':'123','GITHUB_RUN_ATTEMPT':'1'}):
            with patch.object(ps,'atomic_json',side_effect=crash):
                with self.assertRaises(OSError): bridge.finalize_select(data,result,path,123)
            self.assertEqual(self.state()['attempts'],1)
            self.assertFalse((self.root/bridge.receipt_name(data)).exists())
            path.unlink()
            replay=bridge.finalize_select(data,result,path,124)
        self.assertTrue(replay['replayed'])
        self.assertEqual(replay['artifact_id'],123)
        self.assertEqual(self.state()['attempts'],1)

    def test_successful_alias_retry_clears_matching_history(self):
        self.jobs(1)
        self.select('2026-10-08T00:00:00Z','before-alias')
        cur=self.f.get('current_jobs_jw3.json')
        cur['companies'][0]['jobs'][0]['source_id']='alias'
        self.f.put('current_jobs_jw3.json',cur)
        _,_,result,calls=self.select('2026-10-09T00:00:00Z','alias-success',failing=())
        self.assertEqual((calls,result['ready_count']),(1,1))
        self.assertIsNone(self.state())
        self.assertNotIn('jd_fetch',sync.project_batch('jw3',self.root)['records']['JW3::alias'])

    def test_invalid_technical_metadata_is_rejected(self):
        rec=dict(fingerprint='fp',canonical_url='https://official.example')
        state=jd_retry.failed(None,rec,'2026-10-08T00:00:00Z')
        for key,value in [('attempts',True),('attempts',5),('retry_from','2026-10-08'),('status','ANALYZED')]:
            with self.assertRaises(AssertionError): jd_retry.validate({**state,key:value})
