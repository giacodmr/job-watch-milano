"""Rome workday, recovery and Worker-readiness guards."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from collection_freshness import workday, recovery_needed, worker_snapshot_ready
from test_pipeline_resilience import Fixture
import pipeline_state as ps
import job_watch
import certify_job_watch


class CollectionFreshnessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.f = Fixture(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def complete(self, stamp):
        """Build a fresh coherent fixture with no inherited coverage failures."""
        for b in ps.BATCHES:
            cur = self.f.get(f'current_jobs_{b}.json')
            cur['generated_at'] = stamp
            summary = cur.setdefault('summary', {})
            for field in ('FAILED', 'NOT_CHECKED', 'PARTIAL'):
                summary[field] = 0
            self.f.put(f'current_jobs_{b}.json', cur)
        amz = self.f.get('amazon_target_check.json')
        amz['checked_at'] = stamp
        for city in ('Milan', 'Rome', 'London', 'Luxembourg'):
            amz.setdefault('locations', {}).setdefault(city, {})['coverage'] = 'VERIFIED'
        self.f.put('amazon_target_check.json', amz)
        self.f.put('job_watch_run_state.json', ps.snapshot(self.root))

    def test_evening_snapshot_serves_next_morning(self):
        self.complete('2026-10-08T21:05:00Z')  # 23:05 Rome
        self.assertTrue(worker_snapshot_ready(self.root, '2026-10-08T21:45:00Z'))
        self.assertFalse(recovery_needed(self.root, '2026-10-08T21:45:00Z'))
        self.assertFalse(recovery_needed(self.root, '2026-10-08T22:05:00Z'))  # after midnight Rome
        self.assertTrue(worker_snapshot_ready(self.root, '2026-10-09T07:00:00Z'))
        self.assertFalse(recovery_needed(self.root, '2026-10-09T07:00:00Z'))
        self.assertFalse(worker_snapshot_ready(self.root, '2026-10-09T21:00:00Z'))
        self.assertTrue(recovery_needed(self.root, '2026-10-09T21:00:00Z'))
        self.assertEqual(str(workday('2026-10-08T21:05:00Z')), '2026-10-09')

    def test_earlier_same_day_collection_cannot_skip_evening_main(self):
        self.complete('2026-10-08T04:30:00Z')
        self.assertFalse(worker_snapshot_ready(self.root, '2026-10-08T21:00:00Z'))
        self.assertTrue(recovery_needed(self.root, '2026-10-08T21:00:00Z'))

    def test_partial_is_non_blocking_for_worker_and_collector_fallback(self):
        self.complete('2026-10-08T21:05:00Z')
        cur = self.f.get('current_jobs_jw3.json')
        cur['summary']['PARTIAL'] = 1
        self.f.put('current_jobs_jw3.json', cur)
        self.assertTrue(worker_snapshot_ready(self.root, '2026-10-08T21:45:00Z'))
        self.assertFalse(recovery_needed(self.root, '2026-10-08T21:45:00Z'))

    def test_failed_and_not_checked_request_collector_retry_but_do_not_block_worker(self):
        for field in ('FAILED', 'NOT_CHECKED'):
            with self.subTest(field=field):
                self.complete('2026-10-08T21:05:00Z')
                cur = self.f.get('current_jobs_jw3.json')
                cur['summary'][field] = 1
                self.f.put('current_jobs_jw3.json', cur)
                self.assertTrue(worker_snapshot_ready(self.root, '2026-10-08T21:45:00Z'))
                self.assertTrue(recovery_needed(self.root, '2026-10-08T21:45:00Z'))

    def test_incomplete_amazon_requests_recovery_but_does_not_deadlock_worker(self):
        self.complete('2026-10-08T21:05:00Z')
        amz = self.f.get('amazon_target_check.json')
        amz['locations']['Rome']['coverage'] = 'PARTIAL'
        self.f.put('amazon_target_check.json', amz)
        self.assertTrue(worker_snapshot_ready(self.root, '2026-10-08T21:45:00Z'))
        self.assertTrue(recovery_needed(self.root, '2026-10-08T21:45:00Z'))

    def test_mismatched_state_or_priority_timestamp_blocks_worker(self):
        self.complete('2026-10-08T21:05:00Z')
        state = self.f.get('job_watch_run_state.json')
        state['source_generated_at']['JW1'] = 'wrong'
        self.f.put('job_watch_run_state.json', state)
        self.assertFalse(worker_snapshot_ready(self.root, '2026-10-08T21:45:00Z'))
        self.assertTrue(recovery_needed(self.root, '2026-10-08T21:45:00Z'))

        self.complete('2026-10-08T21:05:00Z')
        state = self.f.get('job_watch_run_state.json')
        state['priority_snapshot_at']['Amazon'] = 'wrong'
        self.f.put('job_watch_run_state.json', state)
        self.assertFalse(worker_snapshot_ready(self.root, '2026-10-08T21:45:00Z'))
        self.assertTrue(recovery_needed(self.root, '2026-10-08T21:45:00Z'))

    def test_invalid_timestamp_and_dst(self):
        self.complete('invalid')
        self.assertFalse(worker_snapshot_ready(self.root, '2026-10-08T21:45:00Z'))
        self.assertTrue(recovery_needed(self.root, '2026-10-08T21:45:00Z'))
        for evening, morning, date in [
            ('2026-03-28T22:05:00Z', '2026-03-29T07:00:00Z', '2026-03-29'),
            ('2026-10-24T21:05:00Z', '2026-10-25T08:00:00Z', '2026-10-25'),
        ]:
            self.complete(evening)
            self.assertEqual(str(workday(evening)), date)
            self.assertTrue(worker_snapshot_ready(self.root, morning))
            self.assertFalse(recovery_needed(self.root, morning))

    def test_daily_certifies_previous_evening_as_current_workday(self):
        self.complete('2026-10-08T21:05:00Z')
        rules = self.f.get('job_watch_rules.json')
        rules['run_certification_policy']['require_current_day'] = True
        self.f.put('job_watch_rules.json', rules)
        with self.f.modules(), patch.object(certify_job_watch, 'now', return_value='2026-10-09T07:00:00Z'):
            job_watch.project_state()
            health = certify_job_watch.certify(self.root)
        self.assertFalse(any(t['action'] == 'COLLECT_CURRENT_DAY' for t in health['remaining_work']))
        with self.f.modules(), patch.object(certify_job_watch, 'now', return_value='2026-10-10T07:00:00Z'):
            health = certify_job_watch.certify(self.root)
        self.assertEqual(sum(t['action'] == 'COLLECT_CURRENT_DAY' for t in health['remaining_work']), 4)
