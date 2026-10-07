"""Rome midnight and DST boundaries for the existing collector recovery guard."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from collection_freshness import workday, recovery_needed
from test_pipeline_resilience import Fixture
import pipeline_state as ps
import job_watch
import certify_job_watch


class CollectionFreshnessTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.f=Fixture(self.root)

    def tearDown(self): self.tmp.cleanup()

    def complete(self, stamp):
        for b in ps.BATCHES:
            cur=self.f.get(f'current_jobs_{b}.json')
            cur['generated_at']=stamp
            self.f.put(f'current_jobs_{b}.json',cur)
        amz=self.f.get('amazon_target_check.json');amz['checked_at']=stamp
        self.f.put('amazon_target_check.json',amz)
        self.f.put('job_watch_run_state.json',ps.snapshot(self.root))

    def test_evening_snapshot_serves_next_morning(self):
        self.complete('2026-10-08T21:05:00Z')  # 23:05 Rome
        self.assertFalse(recovery_needed(self.root,'2026-10-08T21:45:00Z'))
        self.assertFalse(recovery_needed(self.root,'2026-10-08T22:05:00Z'))  # delayed recovery after midnight
        self.assertFalse(recovery_needed(self.root,'2026-10-09T07:00:00Z'))
        self.assertTrue(recovery_needed(self.root,'2026-10-09T21:00:00Z'))
        self.assertEqual(str(workday('2026-10-08T21:05:00Z')),'2026-10-09')

    def test_earlier_same_day_collection_cannot_skip_evening_main(self):
        self.complete('2026-10-08T04:30:00Z')
        self.assertTrue(recovery_needed(self.root,'2026-10-08T21:00:00Z'))

    def test_incomplete_sources_or_mismatched_state_require_recovery(self):
        for field in ('FAILED','NOT_CHECKED','PARTIAL'):
            self.complete('2026-10-08T21:05:00Z')
            cur=self.f.get('current_jobs_jw3.json');cur['summary'][field]=1
            self.f.put('current_jobs_jw3.json',cur)
            self.assertTrue(recovery_needed(self.root,'2026-10-08T21:45:00Z'))
        self.complete('2026-10-08T21:05:00Z')
        state=self.f.get('job_watch_run_state.json');state['source_generated_at']['JW1']='wrong'
        self.f.put('job_watch_run_state.json',state)
        self.assertTrue(recovery_needed(self.root,'2026-10-08T21:45:00Z'))
        self.complete('2026-10-08T21:05:00Z')
        amz=self.f.get('amazon_target_check.json');amz['locations'].pop('Rome')
        self.f.put('amazon_target_check.json',amz)
        self.assertTrue(recovery_needed(self.root,'2026-10-08T21:45:00Z'))

    def test_invalid_timestamp_and_dst(self):
        self.complete('invalid')
        self.assertTrue(recovery_needed(self.root,'2026-10-08T21:45:00Z'))
        for evening,morning,date in [('2026-03-28T22:05:00Z','2026-03-29T07:00:00Z','2026-03-29'),
                                     ('2026-10-24T21:05:00Z','2026-10-25T08:00:00Z','2026-10-25')]:
            self.complete(evening)
            self.assertEqual(str(workday(evening)),date)
            self.assertFalse(recovery_needed(self.root,morning))

    def test_daily_certifies_previous_evening_as_current_workday(self):
        self.complete('2026-10-08T21:05:00Z')
        rules=self.f.get('job_watch_rules.json');rules['run_certification_policy']['require_current_day']=True
        self.f.put('job_watch_rules.json',rules)
        with self.f.modules(),patch.object(certify_job_watch,'now',return_value='2026-10-09T07:00:00Z'):
            job_watch.project_state()
            health=certify_job_watch.certify(self.root)
        self.assertFalse(any(t['action']=='COLLECT_CURRENT_DAY' for t in health['remaining_work']))
        with self.f.modules(),patch.object(certify_job_watch,'now',return_value='2026-10-10T07:00:00Z'):
            health=certify_job_watch.certify(self.root)
        self.assertEqual(sum(t['action']=='COLLECT_CURRENT_DAY' for t in health['remaining_work']),4)
