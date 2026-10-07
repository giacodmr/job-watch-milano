"""Shared persistence, snapshot identity and scoped execution errors.

Only source stores/evidence are inputs. run_state is a deterministic projection;
health certification lives exclusively in certify_job_watch.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import errno
import fcntl
import hashlib
import json
import os
import tempfile

ROOT = Path(__file__).resolve().parent
BATCHES = ('jw1', 'jw2', 'jw3', 'jw4')
STATES = {'PENDING', 'COLLECTED', 'NEEDS_REVIEW', 'COMPLETE', 'COMPLETE_WITH_WARNINGS', 'BLOCKED_GLOBAL'}
PRIORITY_STATES = {'VERIFIED', 'PARTIAL', 'FAILED', 'NOT_RUN'}
COVERAGE_STATES = {'VERIFIED', 'PARTIAL', 'FAILED', 'NOT_CHECKED'}
ERROR_SCOPES = {'LOCAL_RECORD_ERROR': 'record', 'SOURCE_ERROR': 'source', 'BATCH_ERROR': 'batch', 'GLOBAL_FATAL_ERROR': 'global'}


def now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def load(name, default=None, root=None):
    path = (root or ROOT) / name
    return json.loads(path.read_text()) if path.exists() else default


def atomic_json(path, value):
    path = Path(path)
    text = json.dumps(value, ensure_ascii=False, indent=2) + '\n'
    if path.exists() and path.read_text() == text:
        return
    fd, tmp = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as f:
            f.write(text); f.flush(); os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)


def stable_dump(name, value, root=None):
    root = root or ROOT
    old = load(name, {}, root)
    if {k:v for k,v in old.items() if k not in {'generated_at','synced_at'}} == {k:v for k,v in value.items() if k not in {'generated_at','synced_at'}}:
        return
    atomic_json(root / name, value)


@contextmanager
def writer_lock(root=None):
    root = root or ROOT
    with (root / '.job_watch.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        recover_transaction(root)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def recover_transaction(root):
    journal = root / '.job_watch.transaction.json'
    if not journal.exists(): return
    tx = json.loads(journal.read_text())
    # A durable journal means a validated commit was started. Complete it.
    for name, item in tx.get('appends', {}).items():
        path = root/name
        path.parent.mkdir(exist_ok=True)
        with path.open('a+b') as stream:
            stream.truncate(item['offset'])
            stream.seek(0, 2)
            stream.write(item['text'].encode())
            stream.flush(); os.fsync(stream.fileno())
    for name, payload in tx['writes'].items(): atomic_json(root / name, payload)
    for name in tx.get('remove', []): (root / name).unlink(missing_ok=True)
    journal.unlink()


def transaction(writes, remove=(), root=None, expected_snapshot=None, appends=None):
    root = root or ROOT
    if expected_snapshot is not None and snapshot(root) != expected_snapshot:
        raise StaleSnapshot('Official inventory/rules changed; reload worklist and review changed fingerprints')
    entries = {name: {'offset':(root/name).stat().st_size if (root/name).exists() else 0,
        'text': ''.join(json.dumps(row,ensure_ascii=False,sort_keys=True,separators=(',', ':'))+'\n' for row in rows)}
        for name, rows in (appends or {}).items()}
    atomic_json(root / '.job_watch.transaction.json', {'writes': writes, 'remove': list(remove), 'appends':entries})
    recover_transaction(root)


class StaleSnapshot(Exception): pass


def error(category, stage, code, message='', **fields):
    return {'category': category, 'scope': ERROR_SCOPES[category], 'stage': stage, 'code': code,
            'message': str(message)[:1000], **fields}


def record_error(category, stage, code, message='', root=None, **fields):
    root = root or ROOT
    item = error(category, stage, code, message, **fields)
    report = load('pipeline_execution.json', {'version':'1.0', 'stages':{}, 'errors':[]}, root)
    if item not in report['errors']: report['errors'].append(item)
    stable_dump('pipeline_execution.json', report, root)
    return item


def attempt(stage, fn, batch=None, company=None, root=None):
    root = root or ROOT
    before = len(load('pipeline_execution.json', {'errors':[]}, root)['errors'])
    try:
        result = fn()
        status = 'COMPLETE'
    except (Exception, SystemExit) as exc:
        global_io = isinstance(exc, OSError) and exc.errno in {errno.ENOSPC, errno.EROFS, errno.EIO}
        category = 'GLOBAL_FATAL_ERROR' if global_io else 'SOURCE_ERROR' if company else 'BATCH_ERROR'
        record_error(category, stage, 'STAGE_FAILED', exc, root=root, **({'batch':batch.upper()} if batch else {}), **({'company':company} if company else {}))
        status, result = ('BLOCKED_GLOBAL' if global_io else 'COMPLETE_WITH_WARNINGS'), None
    report = load('pipeline_execution.json', {'version':'1.0','stages':{},'errors':[]}, root)
    if len(report['errors']) > before and status == 'COMPLETE': status = 'COMPLETE_WITH_WARNINGS'
    report['stages'][stage + (':' + batch.upper() if batch else '')] = {'status':status}
    stable_dump('pipeline_execution.json', report, root)
    return result


def source_identity(root=None):
    root = root or ROOT
    names = [f'current_jobs_{b}.json' for b in BATCHES] + ['amazon_target_check.json', 'job_watch_rules.json', 'job_watch_batches.json', 'companies_job_watch_v2.json']
    hashes = {name: hashlib.sha256((root/name).read_bytes()).hexdigest() if (root/name).exists() else None for name in names}
    return hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest(), hashes


def snapshot(root=None):
    root = root or ROOT
    identity, hashes = source_identity(root)
    def stamp(name, field):
        try: return (load(name, {}, root) or {}).get(field)
        except (ValueError, OSError): return None
    return {'run_id': identity[:24], 'source_generated_at':{b.upper():stamp(f'current_jobs_{b}.json','generated_at') for b in BATCHES},
            'priority_snapshot_at':{'Amazon':stamp('amazon_target_check.json','checked_at')}, 'rules_sha256':hashes['job_watch_rules.json'], 'source_sha256':hashes}


def priority_status(root=None):
    root = root or ROOT
    try: amazon = load('amazon_target_check.json', {}, root) or {}
    except (ValueError, OSError): amazon = {}
    report = load('pipeline_execution.json',{'errors':[]},root)
    amazon_failed = any(e.get('stage') == 'amazon' and e.get('code') == 'STAGE_FAILED' for e in report['errors'])
    statuses = [(amazon.get('locations',{}).get(city) or {}).get('coverage','NOT_CHECKED') for city in ('Milan','Rome','Luxembourg','London')]
    def combine(values):
        if not values or all(v in {'NOT_CHECKED','NOT_RUN',None} for v in values): return 'NOT_RUN'
        if all(v == 'VERIFIED' for v in values): return 'VERIFIED'
        if all(v in {'FAILED','NOT_CHECKED','NOT_RUN',None} for v in values): return 'FAILED'
        return 'PARTIAL'
    try: current = load('current_jobs_jw1.json', {}, root) or {}
    except (ValueError, OSError): current = {}
    mc = [c.get('coverage','NOT_CHECKED') for c in current.get('companies',[]) if c.get('company') == 'Mastercard']
    return {'Amazon':'FAILED' if amazon_failed else combine(statuses), 'Mastercard':combine(mc)}


def refresh_run_state(root=None):
    root = root or ROOT
    token = snapshot(root)
    old = load('job_watch_run_state.json', {}, root) or {}
    activity = load('daily_activity.json', {'version':'1.0','batches':{}}, root)
    if old and old.get('version') != '2.0' and 'legacy_run_state' not in activity:
        # Explicit idempotent migration: archive claims, carry only actual evidence
        # bound to the identical source snapshot, never carry completion booleans.
        activity['legacy_run_state'] = old
        source_match = old.get('source_generated_at') == token['source_generated_at'] and old.get('priority_snapshot_at') == token['priority_snapshot_at']
        if source_match:
            for b, row in old.get('batches',{}).items():
                evidence = row.get('autonomous_search_evidence') or []
                if evidence and row.get('autonomous_delta_count',0) == row.get('autonomous_validated_count',0):
                    activity['batches'][b] = {'snapshot':token, 'searches':evidence, 'discoveries':[]}
        atomic_json(root/'daily_activity.json', activity)
    state = {'version':'2.0', **token, 'priority_checks':priority_status(root), 'batches':{b.upper():{} for b in BATCHES}}
    stable_dump('job_watch_run_state.json', state, root)
    return state


def search_complete(batch, root=None):
    root = root or ROOT
    row = (load('daily_activity.json', {'batches':{}}, root).get('batches') or {}).get(batch.upper(),{})
    if row.get('snapshot') != snapshot(root) or not row.get('searches'): return False
    # Every discovery must resolve to a first-party snapshot record, not a count.
    try:
        current = load(f'current_jobs_{batch.lower()}.json', {}, root)
        keys = {f"{c['company']}::{j['source_id']}" for c in current.get('companies',[]) for j in c.get('jobs',[]) if j.get('source_id') is not None}
        return all(k in keys for k in row.get('discoveries',[]))
    except (ValueError, KeyError, TypeError): return False
