"""Pinned, deterministic engine continuity evidence; no checkout writes or network."""
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile

from .common import REPOSITORY, SafetyError, canonical, digest, exact_commit, git, run, temp_private


def capture(root, commit, *, at=None):
    exact_commit(root,commit)
    if at is None:
        at = datetime.fromisoformat(git(root,'show','-s','--format=%cI',commit).decode().strip()).astimezone(timezone.utc).isoformat(timespec='seconds').replace('+00:00','Z')
    else:
        if datetime.fromisoformat(at.replace('Z','+00:00')).tzinfo is None:
            raise SafetyError('UTC_EVALUATION_TIME_REQUIRED')
    with temp_private() as tmp:
        target = Path(tmp)/'source';target.mkdir(mode=0o700)
        data = git(root,'archive','--format=tar',commit,code='ARCHIVE_READ_FAILED')
        with tarfile.open(fileobj=io.BytesIO(data)) as archive:
            if any(not (member.isfile() or member.isdir()) for member in archive.getmembers()):
                raise SafetyError('UNSAFE_ARCHIVE_MEMBER')
            archive.extractall(target,filter='data')
        probe = Path(__file__).with_name('engine_probe.py')
        # Only the committed engine code executes, never a dirty working tree.
        # Child stdout/stderr are captured and never forwarded to public logs.
        output = run([sys.executable,probe,target,at],code='ENGINE_CONTINUITY_FAILED',timeout=120,cwd=target,credential_free=True)
        try:
            result = json.loads(output)
            if not isinstance(result,dict) or set(result) != {'snapshot','batches','daily','worker_snapshot_ready'}:
                raise ValueError('shape')
        except (ValueError,TypeError): raise SafetyError('ENGINE_CONTINUITY_FAILED') from None
    return {'version':1,'repository':REPOSITORY,'commit_sha':commit,'evaluation_at':at,
            'tree_sha':git(root,'rev-parse',commit+'^{tree}').decode().strip(), 'engine':result}


def compare(before,after):
    required = {'version','repository','commit_sha','evaluation_at','tree_sha','engine'}
    if not isinstance(before,dict) or not isinstance(after,dict) or set(before)!=required or set(after)!=required:
        raise SafetyError('INVALID_CONTINUITY_EVIDENCE')
    for field in ('version','repository','commit_sha','evaluation_at'):
        if before[field] != after[field]: raise SafetyError('CONTINUITY_CHECKPOINT_MISMATCH')
    if canonical(before) != canonical(after): raise SafetyError('CONTINUITY_CHANGED')
    return {'status':'CONTINUITY_MATCH','commit_sha':before['commit_sha'],
            'evidence_sha256':digest(canonical(before))}
