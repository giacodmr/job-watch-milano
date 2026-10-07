"""Batch persistence, artifact binding, failure isolation and replay invariants."""
import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import job_watch_bridge as bridge
import semantic_worker as worker
import enrich_semantic_jds as enrich
from job_memory import load_memory
from test_daily_pipeline import full_decision
from test_pipeline_resilience import Fixture


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.f = Fixture(self.root)
        self.ctx = self.f.modules()
        self.ctx.__enter__()
        self.root_patch = patch.object(bridge, 'ROOT', self.root)
        self.root_patch.__enter__()
        self.requests_patch = patch.object(bridge, 'REQUEST_DIR', self.root / '.job_watch_bridge/requests')
        self.requests_patch.__enter__()
        self.jobs(20)

    def tearDown(self):
        self.requests_patch.__exit__(None,None,None)
        self.root_patch.__exit__(None,None,None)
        self.ctx.__exit__(None,None,None)
        self.tmp.cleanup()

    def jobs(self, n):
        cur = self.f.get('current_jobs_jw3.json')
        cur['companies'][0]['jobs'] = [dict(source_id=str(i),title='Business Analyst',location='Milan',fingerprint='fp'+str(i),status='NEW',canonical_url='https://official.example/'+str(i),first_seen_at='2026-10-03T06:30:00Z') for i in range(n)]
        cur['summary']['target_jobs_open'] = n
        self.f.put('current_jobs_jw3.json', cur)

    def packet_request(self, n=20):
        records = enrich.fetch_candidates('jw3',n,self.root)
        for row in records:
            row['jd'] = {'text':'Complete public JD', 'source_url':row['canonical_url']}
        packet = dict(version=bridge.VERSION,request_id='select',select_run_id=123,batch='jw3',snapshot=worker.batch_snapshot('jw3',self.root),records=records)
        path = self.root/'packet.json'
        path.write_text(json.dumps(packet))
        decisions = {r['job_key']:full_decision(r['fingerprint']) for r in records}
        request = dict(version=bridge.VERSION,action='apply',request_id='apply',parent_request_id='select',select_run_id=123,batch='jw3',packet_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),patch=dict(batch='jw3',snapshot=packet['snapshot'],semantic_decisions=decisions))
        return packet,path,request

    def run_apply(self, request, packet):
        return bridge.apply(request,self.root/'patch.json',self.root/'receipt.json',packet)

    def test_select_accepts_10_20_rejects_21_and_bool(self):
        req = dict(limit=10,fetch=True)
        bridge.validate_select_request(req)
        bridge.validate_select_request({**req,'limit':20})
        for limit in (21,True,0):
            with self.assertRaisesRegex(ValueError,'select_limit_invalid'):
                bridge.validate_select_request({**req,'limit':limit})

    def test_atomic_batch_10_and_20_and_no_surfacing(self):
        for n in (10,20):
            with self.subTest(n=n):
                self.f.put('job_memory_jw3.json',{'batch':'JW3','records':{}})
                (self.root/'.job_watch_bridge/receipts/apply.json').unlink(missing_ok=True)
                _,path,req = self.packet_request(n)
                other = {b:(self.root/f'job_memory_{b}.json').read_bytes() for b in ('jw1','jw2','jw4')}
                result = self.run_apply(req,path)
                self.assertEqual(result['applied_count'],n)
                self.assertEqual(result['status'],'COMPLETE')
                rows = load_memory('jw3',self.root)['records']
                self.assertEqual(len(rows),n)
                self.assertTrue(all('surfacing' not in r and 'user' not in r for r in rows.values()))
                self.assertEqual(other,{b:(self.root/f'job_memory_{b}.json').read_bytes() for b in other})

    def test_one_invalid_review_saves_other_19_and_keeps_retry(self):
        _,path,req = self.packet_request()
        key = next(iter(req['patch']['semantic_decisions']))
        del req['patch']['semantic_decisions'][key]['salary']
        result = self.run_apply(req,path)
        self.assertEqual(result['applied_count'],19)
        self.assertIn(key,result['retry'])
        self.assertEqual(result['status'],'PARTIAL')
        self.assertNotIn(key,load_memory('jw3',self.root)['records'])
        receipt = json.loads((self.root/bridge.receipt_name(req)).read_text())
        self.assertEqual(receipt['request_sha256'],bridge.digest(req))
        self.assertEqual(set(receipt['applied_keys'])|set(receipt['retry']),set(req['patch']['semantic_decisions']))

    def test_full_worker_rejects_invalid_batch_without_partial_writes(self):
        _,_,req = self.packet_request()
        decisions = req['patch']['semantic_decisions']
        decisions[next(reversed(decisions))]['fingerprint'] = 'bad'
        before = (self.root/'job_memory_jw3.json').read_bytes()
        with self.assertRaises(ValueError):
            worker.apply_packet('jw3',req['patch'],self.root)
        self.assertEqual(before,(self.root/'job_memory_jw3.json').read_bytes())

    def test_replay_after_user_change_and_expired_artifact_writes_nothing(self):
        _,path,req = self.packet_request()
        self.run_apply(req,path)
        self.f.put_users({'records':{'JW3::0':{'decision':'NOT_INTERESTED','decided_at':'2026-10-07T10:00:00Z'}}})
        path.unlink()
        before = (self.root/'job_memory_jw3.json').read_bytes()
        result = self.run_apply(req,path)
        self.assertTrue(result['replayed'])
        self.assertEqual(result['applied_count'],0)
        self.assertEqual(before,(self.root/'job_memory_jw3.json').read_bytes())
        changed = copy.deepcopy(req)
        changed['patch']['semantic_decisions']['JW3::0']['fit_score'] = 12
        with self.assertRaisesRegex(ValueError,'request_id_reused'):
            self.run_apply(changed,path)

    def test_stale_snapshot_rejects_entire_batch_without_receipt(self):
        _,path,req = self.packet_request()
        self.f.put('job_watch_rules.json',{'changed':True})
        before = (self.root/'job_memory_jw3.json').read_bytes()
        with self.assertRaisesRegex(ValueError,'stale_worker_snapshot'):
            self.run_apply(req,path)
        self.assertEqual(before,(self.root/'job_memory_jw3.json').read_bytes())
        self.assertFalse((self.root/bridge.receipt_name(req)).exists())

    def test_packet_hash_binding_and_membership(self):
        _,path,req = self.packet_request()
        bad = copy.deepcopy(req)
        bad['packet_sha256'] = 'a'*64
        with self.assertRaisesRegex(ValueError,'packet_hash_mismatch'):
            self.run_apply(bad,path)
        bad = copy.deepcopy(req)
        bad['parent_request_id'] = 'another'
        with self.assertRaisesRegex(ValueError,'packet_binding_mismatch'):
            self.run_apply(bad,path)
        bad = copy.deepcopy(req)
        bad['patch']['semantic_decisions'] = {'JW3::not-selected':full_decision()}
        with self.assertRaisesRegex(ValueError,'outside_selected_packet'):
            self.run_apply(bad,path)

    def test_failed_jd_does_not_block_other_selected_records(self):
        packet,_,req = self.packet_request()
        packet['records'][0].pop('jd')
        packet['records'][0]['jd_error'] = 'HTTP 503'
        data = dict(version=bridge.VERSION,request_id='select',action='select',batch='jw3',limit=20,fetch=True)
        path = self.root/'selected.json'
        with patch.object(bridge,'_run_json_command',return_value=packet),patch.dict(os.environ,{'GITHUB_RUN_ID':'123'}):
            result = bridge.select(data,path)
        self.assertEqual(result['ready_count'],19)
        self.assertEqual(len(json.loads(path.read_text())['records']),20)
        req['packet_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
        req['patch']['semantic_decisions'].pop(packet['records'][0]['job_key'])
        result = self.run_apply(req,path)
        self.assertEqual(result['applied_count'],19)
        self.assertEqual(len(result['retry']),1)

    def test_empty_selection_is_success(self):
        with patch.object(bridge,'_run_json_command',return_value={'records':[]}):
            result = bridge.select(dict(limit=10,fetch=True,batch='jw3',request_id='empty'),self.root/'empty.json')
        self.assertEqual(result['status'],'EMPTY')

    def test_jd_larger_than_40000_is_not_truncated_and_exclusions_work(self):
        text = 'Complete JD '+('x'*45000)
        with patch.object(enrich,'fetch_jd',return_value=(text,'https://official.example','mock')):
            records = enrich.fetch_candidates('jw3',2,self.root,fetch=True,exclude_keys=['JW3::0'])
        self.assertEqual(len(records),2)
        self.assertNotIn('JW3::0',[r['job_key'] for r in records])
        self.assertTrue(all(r['jd']['text']==text for r in records))

    def test_partial_replay_and_corrected_remaining_review(self):
        _,path,req = self.packet_request()
        key = next(iter(req['patch']['semantic_decisions']))
        req['patch']['semantic_decisions'][key]['fingerprint'] = 'bad'
        self.run_apply(req,path)
        before = (self.root/'job_memory_jw3.json').read_bytes()
        self.assertEqual(self.run_apply(req,path)['applied_count'],0)
        self.assertEqual(before,(self.root/'job_memory_jw3.json').read_bytes())
        _,path,retry = self.packet_request(1)
        retry['request_id'] = 'retry'
        result = self.run_apply(retry,path)
        self.assertEqual(result['applied_count'],1)
        self.assertEqual(len(load_memory('jw3',self.root)['records']),20)

    def test_crash_recovery_keeps_memory_and_receipt_together(self):
        import pipeline_state as ps
        _,path,req = self.packet_request()
        original = ps.recover_transaction
        calls = 0
        def crash(root):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError('simulated crash after durable journal')
            return original(root)
        with patch.object(ps,'recover_transaction',side_effect=crash):
            with self.assertRaises(OSError):
                self.run_apply(req,path)
        ps.recover_transaction(self.root)
        self.assertEqual(len(load_memory('jw3',self.root)['records']),20)
        self.assertTrue((self.root/bridge.receipt_name(req)).exists())
        self.assertEqual(self.run_apply(req,path)['applied_count'],0)

    def test_full_jd_in_request_and_id_injection_are_rejected(self):
        _,_,req = self.packet_request()
        req['patch']['semantic_decisions']['JW3::0']['jd'] = 'Never persist me'
        with self.assertRaises(AssertionError):
            bridge.validate_apply_request(req)
        for value in ('../../x','id\noutput=bad','id; rm -rf x'):
            with self.assertRaises(ValueError):
                bridge.safe_id(value)

    def test_worker_error_never_leaks_captured_jd(self):
        import subprocess
        response = subprocess.CompletedProcess([],1,'SECRET JD','SECRET JD')
        with patch.object(bridge.subprocess,'run',return_value=response):
            with self.assertRaisesRegex(RuntimeError,'exit=1') as error:
                bridge._run_json_command(['python'])
        self.assertNotIn('SECRET',str(error.exception))

    def test_download_checks_run_origin_artifact_hash_and_expiry(self):
        import io, zipfile
        _,path,req = self.packet_request()
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer,'w') as z:
            z.writestr('job-watch-packet.json',path.read_bytes())
        class Response:
            status_code = 200
            def __init__(self, data=None, content=None): self.data=data; self.content=content
            def json(self): return self.data
        run = dict(head_branch='pilot',event='push',conclusion='success',path='.github/workflows/chatgpt_job_watch_bridge.yml',head_sha='c'*40)
        artifact = dict(name='job-watch-packet-'+('c'*40),expired=False,id=9)
        parent = dict(action='select',batch='jw3',request_id='select')
        import subprocess
        proc = subprocess.CompletedProcess([],0,json.dumps(parent),'')
        env = dict(GITHUB_REPOSITORY='owner/repo',GITHUB_REF_NAME='pilot',GH_TOKEN='token')
        def responses(r=run, a=artifact):
            return [Response(r),Response({'artifacts':[a]}),Response(content=buffer.getvalue())]
        with patch.dict(os.environ,env),patch.object(bridge.subprocess,'run',return_value=proc):
            with patch('requests.get',side_effect=responses()):
                bridge.download_packet(req,self.root/'download.json')
            self.assertEqual((self.root/'download.json').read_bytes(),path.read_bytes())
            with patch('requests.get',side_effect=responses({**run,'head_branch':'other'})):
                with self.assertRaisesRegex(ValueError,'select_run_not_verified'):
                    bridge.download_packet(req,self.root/'bad.json')
            with patch('requests.get',side_effect=responses(a={**artifact,'expired':True})):
                with self.assertRaisesRegex(ValueError,'missing_or_expired'):
                    bridge.download_packet(req,self.root/'bad.json')
            with patch('requests.get',side_effect=responses()):
                with self.assertRaisesRegex(ValueError,'packet_hash_mismatch'):
                    bridge.download_packet({**req,'packet_sha256':'a'*64},self.root/'bad.json')
        self.assertFalse((self.root/'bad.json').exists())


if __name__ == '__main__':
    unittest.main()
