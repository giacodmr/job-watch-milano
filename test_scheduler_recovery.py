"""Exercise the actual Actions guard with a queued, stale event checkout."""
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import textwrap
import unittest

from test_pipeline_resilience import Fixture
import pipeline_state as ps

WORKFLOW = Path(__file__).parent / '.github/workflows/collect_jobs.yml'


class QueuedScheduleTests(unittest.TestCase):
    def test_queued_retries_read_published_main_and_do_not_touch_snapshots(self):
        workflow = WORKFLOW.read_text()
        freshness = workflow.split('  freshness:', 1)[1].split('\n  collect:', 1)[0]
        ref = re.search(r'^          ref: (.+)$', freshness, re.M)
        script = textwrap.dedent(freshness.split("python - <<'PY'\n", 1)[1].rsplit('          PY', 1)[0])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'repo'
            root.mkdir()
            fixture = Fixture(root)
            def git(*args):
                return subprocess.check_output(['git', *args], cwd=root, stderr=subprocess.DEVNULL, text=True).strip()
            git('init', '-b', 'main')
            git('config', 'user.name', 'Scheduler test')
            git('config', 'user.email', 'scheduler@example.test')
            git('add', '.')
            git('commit', '-m', 'Stale event checkout')
            event_sha = git('rev-parse', 'HEAD')
            stamp = ps.now()
            for batch in ps.BATCHES:
                current = fixture.get(f'current_jobs_{batch}.json')
                current['generated_at'] = stamp
                fixture.put(f'current_jobs_{batch}.json', current)
            amazon = fixture.get('amazon_target_check.json')
            amazon['checked_at'] = stamp
            fixture.put('amazon_target_check.json', amazon)
            fixture.put('job_watch_run_state.json', {'version': '2.0', **ps.snapshot(root)})
            git('add', '.')
            git('commit', '-m', 'Previous writer completes collection')
            published_sha = git('rev-parse', 'HEAD')
            def guard(event='schedule'):
                git('checkout', '--detach', event_sha)
                # Model checkout's configured ref; absent ref pins the event SHA.
                if ref:
                    git('checkout', ref.group(1))
                output, summary = Path(tmp) / 'output', Path(tmp) / 'summary'
                output.write_text('')
                summary.write_text('')
                env = {**os.environ, 'PYTHONDONTWRITEBYTECODE': '1', 'EVENT_NAME': event, 'EVENT_SHA': event_sha,
                       'SCHEDULE': '17 23 * * *', 'GITHUB_OUTPUT': str(output),
                       'GITHUB_STEP_SUMMARY': str(summary)}
                subprocess.run([sys.executable, '-c', script], cwd=root, env=env, check=True, capture_output=True)
                self.assertEqual(git('status', '--porcelain'), '')
                return output.read_text(), summary.read_text()
            for _ in range(2):
                output, summary = guard()
                self.assertIn('should_run=false', output)
                self.assertIn('State SHA: ' + published_sha, summary)
                self.assertIn('Event SHA: ' + event_sha, summary)
            self.assertIn('should_run=false', guard('push')[0])
            self.assertIn('should_run=true', guard('workflow_dispatch')[0])
            current = fixture.get('current_jobs_jw3.json')
            current['summary']['FAILED'] = 1
            fixture.put('current_jobs_jw3.json', current)
            fixture.put('job_watch_run_state.json', {'version': '2.0', **ps.snapshot(root)})
            git('add', '.')
            git('commit', '-m', 'Incomplete collection needs recovery')
            self.assertIn('should_run=true', guard()[0])
            self.assertIn('should_run=true', guard('push')[0])
