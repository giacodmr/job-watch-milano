"""Guardrails for shortened history, lossless text pooling and real writers."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from compact_job_memory import compact, compact_batch, compact_decision, HISTORICAL_FIELDS, digest
from harden_job_watch_state import semantic_decision_valid
from job_memory import load_memory, pack_memory, unpack_memory, memory_json
import pipeline_state as ps
import sync_analysis_state as sync
import semantic_worker as worker
import job_watch
from test_daily_pipeline import full_decision
from test_pipeline_resilience import Fixture

def verbose_decision():
    result = full_decision()
    text = 'Official requirement with mandatory experience and ownership reviewed. '*12
    for field in HISTORICAL_FIELDS: result[field] = text
    result['mandatory_vs_preferred_requirements'] = {
        'mandatory':[text, '5 years relevant experience', 'Stakeholder management', 'English required'],
        'preferred':['7 years preferred', text],
    }
    result.update(l68_status='PREFERRED', l68_evidence='Preference only; eligibility not mandatory.',
                  ordinary_twin_found=False, fixed_base_max_eur=60000, fixed_base_documented=True,
                  fixed_base_source_url='https://official.example/salary')
    return result

class EvidenceCodecTests(unittest.TestCase):
    def memory(self):
        return {'version':'1.0', 'batch':'JW3', 'records':{
            'JW3::1':{'semantic':verbose_decision()}, 'JW3::2':{'semantic':verbose_decision()}},
            'applied_update_ids':['receipt']}

    def test_lossless_deterministic_roundtrip_and_gc(self):
        memory = self.memory(); original = deepcopy(memory)
        packed = pack_memory(memory)
        self.assertTrue(packed['semantic_evidence'])
        self.assertEqual(unpack_memory(packed), memory)
        self.assertEqual(memory, original)
        self.assertEqual(pack_memory(unpack_memory(packed)), packed)
        self.assertEqual(json.loads(memory_json(packed)), packed)
        self.assertLess(len(memory_json(packed)), len(json.dumps(memory, indent=2)))
        memory['records'] = {}
        self.assertEqual(pack_memory(memory)['semantic_evidence'], {})

    def test_corruption_missing_refs_unknown_encoding_and_unused_pool_fail_closed(self):
        original = pack_memory(self.memory())
        key = next(iter(original['semantic_evidence']))
        for mutation in ('text', 'missing', 'unused', 'encoding', 'malformed'):
            stored = deepcopy(original)
            if mutation == 'text': stored['semantic_evidence'][key] += 'wrong'
            if mutation == 'missing': del stored['semantic_evidence'][key]
            if mutation == 'unused': stored['records'] = {}
            if mutation == 'encoding': stored['evidence_encoding'] = 'unknown'
            if mutation == 'malformed': stored['records']['JW3::1']['semantic']['rationale'] = {'$e':key, 'extra':True}
            with self.subTest(mutation=mutation), self.assertRaises(ValueError): unpack_memory(stored)

    def test_external_decisions_cannot_supply_evidence_refs_or_historical_receipts(self):
        decision = full_decision(); decision['seniority_evidence'] = {'$e':'anything'}
        self.assertEqual(semantic_decision_valid(decision, {'fingerprint':'abc'})[1], 'semantic_evidence_unresolved')
        self.assertEqual(semantic_decision_valid(compact_decision(verbose_decision()), {'fingerprint':'abc'})[1], 'historical_evidence_requires_full_review')

    def test_hash_collision_and_jd_fields_rejected(self):
        memory = self.memory()
        other = 'A different repeated long evidence string. '*15
        for row in memory['records'].values(): row['semantic']['rationale'] = other
        with patch('job_memory.evidence_key', return_value='collision'), self.assertRaises(ValueError): pack_memory(memory)
        memory['records']['JW3::1']['semantic']['description'] = 'full JD'
        with self.assertRaises(AssertionError): pack_memory(memory)


class HistoricalCompactionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        self.fixture = Fixture(self.root)
        self.context = self.fixture.modules(); self.context.__enter__()
    def tearDown(self):
        self.context.__exit__(None, None, None); self.tmp.cleanup()
    def store(self, key='JW3::1', **sections):
        memory = load_memory('jw3', self.root)
        memory['records'][key] = {'identity':{'company':'JW3', 'source_id':key.split('::')[1],
            'title':'Business Analyst', 'location':'Milan', 'canonical_url':'https://official.example/1'},
            'semantic':verbose_decision(), **sections}
        self.fixture.put('job_memory_jw3.json', memory)
        return memory
    def open(self, sid='1', status='NEW'):
        current = self.fixture.get('current_jobs_jw3.json')
        current['companies'][0]['jobs'] = [{'source_id':sid, 'title':'Business Analyst', 'location':'Milan',
            'canonical_url':'https://official.example/1', 'fingerprint':'abc', 'status':status}]
        current['summary']['target_jobs_open'] = int(status != 'UNKNOWN')
        self.fixture.put('current_jobs_jw3.json', current)
        return current

    def test_summary_preserves_conclusions_numbers_eligibility_salary_and_provenance(self):
        original = verbose_decision(); shortened = compact_decision(original)
        self.assertNotEqual(original, shortened)
        for field, value in original.items():
            if field not in HISTORICAL_FIELDS: self.assertEqual(shortened[field], value)
        self.assertEqual(shortened['historical_evidence']['source_sha256'], digest(original))
        self.assertIn('omessi', shortened['historical_evidence']['requirements']['mandatory'][-1])
        self.assertEqual(compact_decision(shortened), shortened)

    def test_current_unknown_aliases_and_active_choices_keep_all_evidence(self):
        for sid, status, user in [('1','NEW',{}), ('new-id','NEW',{}), ('1','UNKNOWN',{}),
                                  ('absent','NEW',{'decision':'INTERESTED','decided_at':'2026-10-01'}),
                                  ('absent','NEW',{'decision':'TO_REVIEW','decided_at':'2026-10-01'})]:
            memory = self.store(user=user) if user else self.store()
            current = self.open(sid, status)
            if user: current['companies'][0]['jobs'][0]['canonical_url'] = 'https://official.example/unrelated'
            with self.subTest(sid=sid, status=status, user=user):
                self.assertEqual(compact_batch('jw3', memory, current)[0], memory)

    def test_dry_run_transaction_projection_equivalence_and_second_apply_noop(self):
        user = {'decision':'NOT_INTERESTED', 'decided_at':'2026-10-01', 'reason':'Troppo senior'}
        surface = {'first_surfaced_at':'2026-10-01', 'last_surfaced_at':'2026-10-01', 'surface_count':1}
        before = self.store(user=user, surfacing=surface)
        files = {p.name:p.read_bytes() for p in self.root.glob('*.json')}
        dry = compact(self.root)
        self.assertEqual(dry['batches']['jw3']['newly_shortened'], 1)
        self.assertEqual(files, {p.name:p.read_bytes() for p in self.root.glob('*.json')})
        compact(self.root, apply=True)
        after = load_memory('jw3', self.root)['records']['JW3::1']
        for field in ('identity','user','surfacing'): self.assertEqual(after[field], before['records']['JW3::1'][field])
        files = {p.name:p.read_bytes() for p in self.root.glob('*.json')}
        compact(self.root, apply=True)
        self.assertEqual(files, {p.name:p.read_bytes() for p in self.root.glob('*.json')})

    def test_reopen_same_fingerprint_or_alias_requires_full_review(self):
        self.store(); compact(self.root, apply=True)
        for sid in ('1', 'new-id'):
            self.open(sid)
            rec = sync.project_batch('jw3', self.root)['records'][f'JW3::{sid}']
            self.assertTrue(rec['needs_analysis']); self.assertTrue(rec['requires_full_jd_review'])
            self.assertEqual(sync.project_batch('jw3', self.root)['queue'][0]['guardrail_reason'], 'historical_evidence_shortened')
            decision = full_decision(); decision['analysis_method'] = 'chatgpt_semantic_title_metadata'
            self.assertEqual(semantic_decision_valid(decision, rec)[1], 'full_jd_required')
            self.assertTrue(semantic_decision_valid(full_decision(), rec)[0])
        packet = {'batch':'jw3', 'snapshot':worker.batch_snapshot('jw3', self.root),
                  'semantic_decisions':{'JW3::new-id':full_decision()}}
        worker.apply_packet('jw3', packet, self.root)
        self.assertFalse(sync.project_batch('jw3', self.root)['records']['JW3::new-id']['needs_analysis'])
        self.assertEqual(worker.apply_packet('jw3', packet, self.root), 0)

    def test_applied_and_not_interested_stay_suppressed_after_reopen(self):
        for state in ('APPLIED', 'NOT_INTERESTED'):
            self.store(user={'decision':state, 'decided_at':'2026-10-01'})
            current = self.fixture.get('current_jobs_jw3.json'); current['companies'][0]['jobs'] = []
            self.fixture.put('current_jobs_jw3.json', current); compact(self.root, apply=True)
            self.open()
            rec = sync.project_batch('jw3', self.root)['records']['JW3::1']
            self.assertFalse(rec['needs_analysis']); self.assertFalse(rec['reportable'])

    def test_daily_writer_preserves_packed_history_and_rejects_unresolved_refs(self):
        self.store(); compact(self.root, apply=True); self.open()
        import daily_worklist
        decision = full_decision(); decision['rationale'] = {'$e':'forged'}
        patch_data = {'version':'1.0', 'snapshot':daily_worklist.build_worklist()['snapshot'],
                      'semantic_decisions':{'jw3':{'JW3::1':decision}}}
        self.fixture.put('daily_updates.json', patch_data); job_watch.apply_updates()
        self.assertIn('historical_evidence', load_memory('jw3', self.root)['records']['JW3::1']['semantic'])
        patch_data['semantic_decisions']['jw3']['JW3::1'] = full_decision()
        self.fixture.put('daily_updates.json', patch_data); job_watch.apply_updates()
        self.assertNotIn('historical_evidence', load_memory('jw3', self.root)['records']['JW3::1']['semantic'])
        raw = self.fixture.get('job_memory_jw3.json')
        self.assertIn('evidence_encoding', raw)

    def test_transaction_recovery_preserves_compact_encoding(self):
        memory = self.store(); packed = pack_memory(memory)
        self.fixture.put('.job_watch.transaction.json', {'writes':{'job_memory_jw3.json':packed}})
        ps.recover_transaction(self.root)
        self.assertEqual(load_memory('jw3', self.root), memory)
        self.assertFalse((self.root/'.job_watch.transaction.json').exists())

if __name__ == '__main__': unittest.main()
