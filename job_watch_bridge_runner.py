"""Git checkpoint acknowledgement; a remote descendant is also a valid ACK."""
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parent


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT, text=True).strip()


def acknowledge(branch, commit, receipt_path):
    """Also handles a successful push whose response was lost by the runner."""
    local = json.loads((ROOT / receipt_path).read_text())
    git('fetch', 'origin', 'refs/heads/' + branch)
    remote = git('rev-parse', 'FETCH_HEAD')
    subprocess.run(['git', 'merge-base', '--is-ancestor', commit, remote], cwd=ROOT, check=True)
    stored = json.loads(git('show', remote + ':' + receipt_path))
    if stored != local:
        raise ValueError('remote_receipt_mismatch')
    return {'remote_commit_sha':commit, 'remote_head_sha':remote}


def publish(branch, receipt_path):
    commit = git('rev-parse', 'HEAD')
    # Do not trust the push exit status alone (the server may already have accepted it).
    subprocess.run(['git', 'push', 'origin', 'HEAD:' + branch], cwd=ROOT, check=False)
    return acknowledge(branch, commit, receipt_path)
