"""Bounded subprocesses, private output paths and redacted errors."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

REPOSITORY = 'giacodmr/job-watch-milano'
OID = re.compile(r'^[a-f0-9]{40}(?:[a-f0-9]{24})?$')
SHA256 = re.compile(r'^[a-f0-9]{64}$')

class SafetyError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)

def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')

def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(',', ':'), allow_nan=False).encode()

def digest(data):
    return hashlib.sha256(data).hexdigest()

def file_digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda: handle.read(1024*1024), b''):
            h.update(block)
    return h.hexdigest()

def run(args, *, cwd=None, code='COMMAND_FAILED', timeout=180, input=None, stdout=subprocess.PIPE, credential_free=False):
    env = {k:v for k,v in os.environ.items() if not k.startswith('GIT_')}
    if credential_free:
        env = {k:v for k,v in env.items() if k in {'PATH','LANG','LC_ALL','TMPDIR','SYSTEMROOT'}}
    env.update(GIT_TERMINAL_PROMPT='0', GIT_OPTIONAL_LOCKS='0', PYTHONDONTWRITEBYTECODE='1')
    try:
        result = subprocess.run([str(a) for a in args], cwd=cwd, env=env, input=input,
                                stdout=stdout, stderr=subprocess.PIPE, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise SafetyError(code) from None
    if result.returncode:
        # Git, age and Python errors can contain URLs, tokens, filenames or user data.
        raise SafetyError(code)
    return result.stdout

def git(root, *args, **kwargs):
    return run(['git', '-c', 'core.hooksPath=/dev/null', '-c', 'init.templateDir=',
                '-C', str(root), *args], **kwargs)

def private_parent(path):
    path = Path(path).expanduser().absolute()
    parent = path.parent.resolve(strict=True)
    if not parent.is_dir() or parent.stat().st_mode & 0o077:
        raise SafetyError('PRIVATE_DIRECTORY_REQUIRED')
    # Forbid artifacts even in ignored directories of ANY working tree or bare repo.
    probe = subprocess.run(['git', '-C', str(parent), 'rev-parse', '--git-dir'],
                           capture_output=True, env={**{k:v for k,v in os.environ.items() if not k.startswith('GIT_')}, 'GIT_OPTIONAL_LOCKS':'0'})
    if probe.returncode == 0 or any(p.name == '.git' for p in (parent, *parent.parents)):
        raise SafetyError('OUTPUT_INSIDE_GIT_FORBIDDEN')
    target = parent / path.name
    if target.exists() or target.is_symlink():
        raise SafetyError('OUTPUT_ALREADY_EXISTS')
    return target

def write_private(path, payload):
    path = private_parent(path)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0)
    fd = os.open(path, flags, 0o600)
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return path

def read_private_json(path, *, max_bytes=16*1024*1024):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077:
        raise SafetyError('PRIVATE_FILE_REQUIRED')
    if path.stat().st_size > max_bytes:
        raise SafetyError('EVIDENCE_TOO_LARGE')
    try:
        return json.loads(path.read_bytes())
    except (OSError, ValueError):
        raise SafetyError('INVALID_EVIDENCE') from None

def source_remote(root):
    value = git(root, 'remote', 'get-url', 'origin').decode().strip()
    if value not in {f'https://github.com/{REPOSITORY}', f'https://github.com/{REPOSITORY}.git',
                     f'git@github.com:{REPOSITORY}.git', f'git@github.com:{REPOSITORY}'}:
        raise SafetyError('UNAUTHORIZED_REPOSITORY')
    return value

def exact_commit(root, value):
    if not OID.fullmatch(value):
        raise SafetyError('FULL_COMMIT_SHA_REQUIRED')
    actual = git(root, 'rev-parse', '--verify', value+'^{commit}').decode().strip()
    if actual != value:
        raise SafetyError('COMMIT_MISMATCH')
    return actual

def temp_private():
    # mkdtemp creates 0700; all cleartext is confined to a temporary directory.
    return tempfile.TemporaryDirectory(prefix='job-watch-safety-')
