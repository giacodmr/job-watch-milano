"""Real Git remotes exercise acknowledgement and non-fast-forward failures."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import job_watch_bridge_runner as runner


class RemoteCheckpointTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.remote = base/'remote.git'
        self.repo = base/'repo'
        self.command(base,'init','--bare',str(self.remote))
        self.command(base,'clone',str(self.remote),str(self.repo))
        self.command(self.repo,'config','user.email','test@example.com')
        self.command(self.repo,'config','user.name','Test')
        self.command(self.repo,'checkout','-b','pilot')
        self.receipt = '.job_watch_bridge/receipts/apply.json'
        target = self.repo/self.receipt
        target.parent.mkdir(parents=True)
        target.write_text(json.dumps({'request_sha256':'same','applied_count':10}))
        self.commit('checkpoint')
        self.checkpoint = self.command(self.repo,'rev-parse','HEAD')
        self.command(self.repo,'push','origin','HEAD:pilot')
        self.ctx = patch.object(runner,'ROOT',self.repo)
        self.ctx.__enter__()

    def tearDown(self):
        self.ctx.__exit__(None,None,None)
        self.tmp.cleanup()

    def command(self, cwd, *args):
        return subprocess.check_output(['git',*args],cwd=cwd,text=True,stderr=subprocess.DEVNULL).strip()

    def commit(self, message):
        self.command(self.repo,'add','.')
        self.command(self.repo,'commit','-m',message)

    def test_acknowledges_receipt_even_after_remote_advances(self):
        (self.repo/'transport.txt').write_text('another request')
        self.commit('remote advances')
        self.command(self.repo,'push','origin','HEAD:pilot')
        head = self.command(self.repo,'rev-parse','HEAD')
        self.command(self.repo,'reset','--hard',self.checkpoint)
        result = runner.acknowledge('pilot',self.checkpoint,self.receipt)
        self.assertEqual(result['remote_commit_sha'],self.checkpoint)
        self.assertEqual(result['remote_head_sha'],head)

    def test_push_response_failure_is_reconciled_from_remote(self):
        # The checkpoint already reached the server; only the client response was lost.
        actual = subprocess.run
        def response_lost(args, **kwargs):
            if args[:2] == ['git','push']:
                return subprocess.CompletedProcess(args,1)
            return actual(args,**kwargs)
        with patch.object(runner.subprocess,'run',side_effect=response_lost):
            result = runner.publish('pilot',self.receipt)
        self.assertEqual(result['remote_commit_sha'],self.checkpoint)

    def test_rejected_push_never_claims_unpublished_decisions_or_force_pushes(self):
        (self.repo/'remote.txt').write_text('remote wins')
        self.commit('winner')
        self.command(self.repo,'push','origin','HEAD:pilot')
        winner = self.command(self.repo,'rev-parse','HEAD')
        self.command(self.repo,'reset','--hard',self.checkpoint)
        (self.repo/'draft.txt').write_text('losing checkpoint')
        self.commit('loser')
        with self.assertRaises(subprocess.CalledProcessError):
            runner.publish('pilot',self.receipt)
        self.assertEqual(self.command(self.repo,'ls-remote','origin','refs/heads/pilot').split()[0],winner)

    def test_remote_modified_receipt_is_rejected(self):
        (self.repo/self.receipt).write_text(json.dumps({'request_sha256':'other','applied_count':20}))
        self.commit('corrupt receipt')
        self.command(self.repo,'push','origin','HEAD:pilot')
        self.command(self.repo,'reset','--hard',self.checkpoint)
        with self.assertRaisesRegex(ValueError,'remote_receipt_mismatch'):
            runner.acknowledge('pilot',self.checkpoint,self.receipt)
