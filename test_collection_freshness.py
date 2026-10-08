"""Rome workday, Collector recovery and Worker readiness regressions."""
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

    def checkpoint(self):
        self.f.put('job_watch_run_state.json', {'version': '2.0', **ps.snapshot(self.root)})

    def complete(self, stamp):
        for batch in ps.BATCHES:
            current = self.f.get(f'current_jobs_{batch}.json')
            current['generated_at'] = stamp
            summary = current.setdefault('summary', {})
            for field in ('FAILED', 'NOT_CHECKED', 'PARTIAL'):
                summary[field] = 0
            self.f.put(f'current_jobs_{batch}.json', current)
        amazon = self.f.get('amazon_target_check.json')
        amazon['checked_at'] = stamp
        for city in ('Milan', 'Rome', 'London', 'Luxembourg'):
            amazon.setdefault('locations', {}).setdefault(city, {})['coverage'] = 'VERIFIED'
        self.f.put('amazon_target_check.json', amazon)
        self.checkpoint()

    def set_batch_coverage_count(self, field, value=1):
        current = self.f.get('current_jobs_jw3.json')
        current['summary'][field] = value
        self.f.put('current_jobs_jw3.json', current)
        self.checkpoint()

    def test_evening_snapshot_serves_next_morning(self):
        self.complete('2026-10-08T21:05:00Z')  # 23:05 Rome
        for at in ('2026-10-08T21:45:00Z', '2026-10-08T22:05:00Z', '2026-10-09T07:00:00Z'):
            self.assertTrue(worker_snapshot_ready(self.root, at))
            self.assertFalse(recovery_needed(self.root, at))
        self.assertFalse(worker_snapshot_ready(self.root, '2026-10-09T21:00:00Z'))
        self.assertTrue(recovery_needed(self.root, '2026-10-09T21:00:00Z'))
        self.assertEqual(str(workday('2026-10-08T21:05:00Z')), '2026-10-09')

    def test_earlier_same_day_collection_cannot_skip_evening_main(self):
        self.complete('2026-10-08T04:30:00Z')
        self.assertFalse(worker_snapshot_ready(self.root, '2026-10-08T21:00:00Z'))
        self.assertTrue(recovery_needed(self.root, '2026-10-08T21:00:00Z'))

    def test_partial_is_non_blocking(self):
        self.complete('2026-10-08T21:05:00Z')
        self.set_batch_coverage_count('PARTIAL')
        self.assertTrue(worker_snapshot_ready(self.root, '2026-10-08T21:45:00Z'))
        self.assertFalse(recovery_needed(self.root, '2026-10-08T21:45:00Z'))

    def test_failed_and_not_checked_retry_collector_without_deadlocking_worker(self):
        for field in ('FAILED', 'NOT_CHECKED'):
            with self.subTest(field=field):
                self.complete('2026-10-08T21:05:00Z')
                self.set_batch_coverage_count(field)
                self.assertTrue(worker_snapshot_ready(self.root, '2026-10-08T21:45:00Z'))
                self.assertTrue(recovery_needed(self.root, '2026-10-08T21:45:00Z'))

    def test_incomplete_amazon_retries_collector_without_deadlocking_worker(self):
        self.complete('2026-10-08T21:05:00Z')
        amazon = self.f.get('amazon_target_check.json')
        amazon['locations']['Rome']['coverage'] = 'PARTIAL'
        self.f.put('amazon_target_check.json', amazon)
        self.checkpoint()
        self.assertTrue(worker_snapshot_ready(self.root, '2026-10-08T21:45:00Z'))
        self.assertTrue(recovery_needed(self.root, '2026-10-08T21:45:00Z'))

    def test_hash_mismatch_blocks_worker_even_when_timestamps_are_unchanged(self):
        self.complete('2026-10-08T21:05:00Z')
        current = self.f.get('current_jobs_jw2.json')
        current['summary']['target_jobs_open'] += 1
        self.f.put('current_jobs_jw2.json', current)  # intentionally do not refresh run_state
        self.assertFalse(worker_snapshot_ready(self.root, '2026-10-08T21:45:00Z'))
        self.assertTrue(recovery_needed(self.root, '2026-10-08T21:45:00Z'))

    def test_mismatched_state_blocks_worker(self):
        self.complete('2026-10-08T21:05:00Z')
        state = self.f.get('job_watch_run_state.json')
        state['source_generated_at']['JW1'] = 'wrong'
        self.f.put('job_watch_run_state.json', state)
        self.assertFalse(worker_snapshot_ready(self.root, '2026-10-08T21:45:00Z'))
        self.assertTrue(recovery_needed(self.root, '2026-10-08T21:45:00Z'))

    def test_collector_checkpoints_final_maintained_inventory_for_recovery(self):
        self.complete('2026-10-08T21:05:00Z')
        current = self.f.get('current_jobs_jw3.json')
        # Real maintenance adds lifecycle fields and recounts this fresh row.
        current['companies'][0]['jobs'] = [{
            'source_id': 'fresh', 'title': 'Business Analyst', 'location': 'Milan',
            'fingerprint': 'fresh-fingerprint', 'status': 'NEW',
            'canonical_url': 'https://official.example/fresh',
        }]
        self.f.put('current_jobs_jw3.json', current)
        self.checkpoint()
        with self.f.modules(), patch('collector.collect_batch'), patch('reconcile_workday_target_paths.reconcile_batch'), patch('amazon_target_check.main'):
            with ps.writer_lock(self.root):
                self.assertTrue(job_watch.stage('collect'))
            maintained = self.f.get('current_jobs_jw3.json')
            self.assertIn('first_seen_at', maintained['companies'][0]['jobs'][0])
            self.assertTrue(worker_snapshot_ready(self.root, '2026-10-08T21:45:00Z'))
            self.assertFalse(recovery_needed(self.root, '2026-10-08T21:45:00Z'))
            for key in ('run_id', 'source_sha256'):
                self.assertEqual(self.f.get('job_watch_run_state.json')[key], ps.snapshot(self.root)[key])
            snapshots = {p.name: p.read_bytes() for p in self.root.glob('current_jobs_jw*.json')}
            with ps.writer_lock(self.root):
                self.assertTrue(job_watch.stage('sync'))
            self.assertEqual(snapshots, {p.name: p.read_bytes() for p in self.root.glob('current_jobs_jw*.json')})
            self.assertFalse(recovery_needed(self.root, '2026-10-08T21:47:00Z'))

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
        self.checkpoint()
        with self.f.modules(), patch.object(certify_job_watch, 'now', return_value='2026-10-09T07:00:00Z'):
            job_watch.project_state()
            health = certify_job_watch.certify(self.root)
        self.assertFalse(any(t['action'] == 'COLLECT_CURRENT_DAY' for t in health['remaining_work']))
        with self.f.modules(), patch.object(certify_job_watch, 'now', return_value='2026-10-10T07:00:00Z'):
            health = certify_job_watch.certify(self.root)
        self.assertEqual(sum(t['action'] == 'COLLECT_CURRENT_DAY' for t in health['remaining_work']), 4)
