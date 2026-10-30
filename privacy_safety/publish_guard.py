"""Constrain this PR to reviewed tooling paths; not a general-purpose PII detector."""
from pathlib import Path
import re
from .common import SafetyError, exact_commit, git

ALLOWED = re.compile(r'^(?:privacy_safety/[a-z_]+\.py|tools/privacy_cutover\.py|test_privacy_safety\.py|requirements-privacy-safety\.txt|\.github/workflows/privacy-safety\.yml|\.gitignore|docs/privacy-cutover/[A-Z_]+\.md)$')
SECRET = re.compile(rb'(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}|AGE-SECRET-KEY-1[0-9A-Z]{40,}|-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----)')

def check_publish(root,base):
    exact_commit(root,base)
    names = set(git(root,'diff','--name-only','-z',base).decode().split('\0'))
    names.update(git(root,'ls-files','--others','--exclude-standard','-z').decode().split('\0'));names.discard('')
    for name in names:
        if not ALLOWED.fullmatch(name): raise SafetyError('PUBLISH_SCOPE_VIOLATION')
        path = Path(root)/name
        if path.is_symlink(): raise SafetyError('PUBLISH_SYMLINK_FORBIDDEN')
        if path.exists():
            data = path.read_bytes()
            if b'\x00' in data or SECRET.search(data): raise SafetyError('PUBLISH_SENSITIVE_CONTENT')
    return {'status':'PUBLISH_SCOPE_VERIFIED','files':len(names),'pii_review_still_required':True}
