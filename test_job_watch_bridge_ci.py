import subprocess
import unittest
from unittest.mock import patch
import job_watch_bridge_ci as gate


class ValidationReuseTests(unittest.TestCase):
    event = {'pull_request':{'head':{'sha':'new'}},'sender':{'login':'user'}}

    def test_request_only_requires_matching_successful_ancestor(self):
        def git(*args):
            if args[0] == 'diff-tree': return '.job_watch_bridge/requests/select.json'
            if args[0] == 'merge-base': return ''
            raise AssertionError(args)
        api = lambda _: {'workflow_runs':[{'head_sha':'old','conclusion':'success'}]}
        with patch.object(gate,'git',side_effect=git),patch.object(gate,'fingerprint',return_value='same'):
            self.assertTrue(gate.reusable(self.event,api))
        with patch.object(gate,'git',side_effect=git),patch.object(gate,'fingerprint',side_effect=lambda ref: 'new-code' if ref in {'new','HEAD'} else 'old-code'):
            self.assertFalse(gate.reusable(self.event,api))
        with patch.object(gate,'git',side_effect=git),patch.object(gate,'fingerprint',return_value='same'):
            self.assertFalse(gate.reusable(self.event,lambda _: {'workflow_runs':[]}))
        with patch.object(gate,'git',side_effect=git),patch.object(gate,'fingerprint',side_effect=['head-code','different-merge-code']):
            self.assertFalse(gate.reusable(self.event,api))

    def test_code_and_business_rules_changes_always_require_full_validation(self):
        for path in ['job_watch_bridge.py','job_watch_rules.json','.github/workflows/validate.yml']:
            with self.subTest(path=path),patch.object(gate,'git',return_value=path):
                self.assertFalse(gate.reusable(self.event,lambda _: self.fail('API not needed')))

    def test_checkpoint_requires_actual_successful_apply_validation_step(self):
        event = {**self.event,'sender':{'login':'github-actions[bot]'}}
        def git(*args):
            if args[0] == 'diff-tree': return 'job_memory_jw3.json\n.job_watch_bridge/receipts/apply.json'
            if args[0] == 'rev-parse': return 'parent'
            raise AssertionError(args)
        def api(path):
            if '/jobs' in path:
                return {'jobs':[{'steps':[{'name':'Validate batch once before publication','conclusion':'success'}]}]}
            return {'workflow_runs':[{'id':1,'head_sha':'parent','event':'push'}]}
        with patch.object(gate,'git',side_effect=git),patch.object(gate,'fingerprint',return_value='same'):
            self.assertTrue(gate.reusable(event,api))
        with patch.object(gate,'git',side_effect=git),patch.object(gate,'fingerprint',return_value='same'):
            self.assertFalse(gate.reusable(event,lambda path: {'jobs':[]} if '/jobs' in path else api(path)))
        with patch.object(gate,'git',side_effect=git):
            self.assertFalse(gate.reusable(self.event,api))

    def test_non_ancestor_validation_cannot_be_reused(self):
        def git(*args):
            if args[0] == 'diff-tree': return '.job_watch_bridge/requests/select.json'
            raise subprocess.CalledProcessError(1,args)
        with patch.object(gate,'git',side_effect=git),patch.object(gate,'fingerprint',return_value='same'):
            self.assertFalse(gate.reusable(self.event,lambda _: {'workflow_runs':[{'head_sha':'other','conclusion':'success'}]}))
