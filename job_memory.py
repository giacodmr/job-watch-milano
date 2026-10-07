"""Durable decisions and surfacing, partitioned by batch; no derived state or JD."""
from pathlib import Path
import hashlib
import json
from pipeline_state import load, BATCHES, now

ROOT = Path(__file__).resolve().parent
USER_STATES = {'TO_REVIEW', 'INTERESTED', 'APPLIED', 'NOT_INTERESTED'}
JD_FIELDS = {'text', 'description', 'description_short', 'job_description', 'body', 'basic_qualifications', 'preferred_qualifications', 'jd'}
IDENTITY_FIELDS = ('company', 'source_id', 'title', 'location', 'canonical_url', 'apply_url', 'first_seen_at', 'last_seen_at', 'role_family', 'fingerprint')

def load_memory(batch, root=None):
    if batch not in BATCHES: raise ValueError('Unknown batch')
    result = load(f'job_memory_{batch}.json', None, root or ROOT)
    if not isinstance(result, dict) or not isinstance(result.get('records'), dict):
        raise ValueError(f'Missing/invalid job memory: {batch}')
    return result

def assert_no_jd(obj):
    if isinstance(obj, dict):
        assert not JD_FIELDS.intersection(obj), 'Full JD field in persistent memory'
        for value in obj.values(): assert_no_jd(value)
    elif isinstance(obj, list):
        for value in obj: assert_no_jd(value)


def validate_memory(memory, batch, owners=None):
    assert memory.get('batch', '').lower() == batch, 'Memory batch ownership mismatch'
    assert_no_jd(memory)
    for key, row in memory['records'].items():
        assert isinstance(key, str) and isinstance(row, dict), 'Malformed memory record'
        if owners: assert owners.get(key.split('::')[0], batch) == batch, 'Wrong company owner'
        if row.get('user'):
            assert row['user']['decision'] in USER_STATES and row['user'].get('decided_at'), 'Invalid user decision'
        surface = row.get('surfacing')
        if surface:
            assert surface.get('first_surfaced_at') and surface.get('last_surfaced_at'), 'Missing surfacing time'
            assert isinstance(surface.get('surface_count'), int) and surface['surface_count'] >= 1, 'Invalid surface count'

def material_signature(rec):
    # Metadata noise (dates, URL tracking, API fingerprints) does not resurface a
    # reviewed role. Explicit semantic material_change can still trigger reporting.
    data = {f: str(rec.get(f) or '').strip().casefold() for f in ('title', 'location', 'role_family')}
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:20]

def older_timestamp(incoming, existing):
    from datetime import datetime, timezone
    def parse(value):
        stamp=datetime.fromisoformat(str(value).replace('Z','+00:00'))
        return stamp.replace(tzinfo=timezone.utc) if stamp.tzinfo is None else stamp
    if not existing: return False
    return parse(incoming)<parse(existing)


def record_surface(record, update, rec):
    old = record.get('surfacing', {})
    stamp = update['surfaced_at']
    if older_timestamp(stamp, old.get('last_surfaced_at')): raise ValueError('Older surfacing event cannot overwrite current history')
    if old.get('last_surfaced_at') == stamp and old.get('last_surfaced_fingerprint') == update['fingerprint'] and old.get('surfaced_status') == update['surfaced_status']:
        return
    record['surfacing'] = {**old, 'first_surfaced_at': old.get('first_surfaced_at') or stamp,
        'last_surfaced_at': stamp, 'surface_count': old.get('surface_count', 0) + 1,
        'last_surfaced_fingerprint': update['fingerprint'], 'surfaced_status': update['surfaced_status'],
        'last_material_signature': material_signature(rec)}

def archive_rows(rows, root=None):
    """Append compact deterministic lines; caller holds the writer lock.

    No archive read. Only an official transition to CLOSED calls this function,
    and the same transaction removes that row from current state.
    """
    root = root or ROOT
    if not rows: return {}
    grouped = {}
    for key, row in rows:
        stamp = row.get('last_seen_at') or row.get('first_seen_at') or now()
        month = str(stamp)[:7].replace('-', '_')
        item = {'job_key': key, **{f: row[f] for f in IDENTITY_FIELDS if row.get(f) is not None}}
        grouped.setdefault(f'archive/vacancies_{month}.jsonl', []).append(item)
    return grouped

def identity_url(identity):
    from urllib.parse import urlsplit
    url = str(identity.get('canonical_url') or identity.get('apply_url') or '')
    parsed = urlsplit(url)
    # Amazon has used UUID and numeric requisition keys for the same public job.
    import re
    match = re.search(r'/jobs/(\d+)(?:/|$)', parsed.path)
    if (identity.get('company') == 'Amazon' or 'amazon.jobs' in parsed.netloc) and match:
        return 'Amazon::'+match.group(1)
    return (parsed.netloc+parsed.path).rstrip('/').casefold() if url else None

def resolve_identities(current, memory):
    """Resolve historic key aliases without deleting any durable evidence.

    Explicit user choices are identity-scoped, so a historical public-URL alias
    must not make a rejection disappear after a collector ID normalization.
    """
    byurl = {}
    for key, row in memory.items():
        url=identity_url(row.get('identity',{}))
        if url: byurl.setdefault(url,[]).append((key,row))
    from collections import Counter
    current_urls=Counter(identity_url({**j,'company':j.get('_company_name') or j.get('company')}) for j in current.values())
    effective, aliases = {}, set()
    for key, job in current.items():
        url=identity_url({**job,'company':job.get('_company_name') or job.get('company')})
        matches=[(k,r) for k,r in byurl.get(url,[]) if k.split('::')[0]==key.split('::')[0]] if current_urls[url]==1 else []
        own=memory.get(key,{})
        merged=dict(own)
        if matches:
            aliases.update(k for k,_ in matches if k!=key)
            choices=[r for _,r in matches]+[own]
            for section,stamp in (('user','decided_at'),('surfacing','last_surfaced_at'),('semantic','analyzed_at')):
                options=[r[section] for r in choices if r.get(section)]
                if section=='semantic':
                    valid=[r for r in options if r.get('fingerprint')==job.get('fingerprint')]
                    options=valid or options
                if options:merged[section]=max(options,key=lambda r:r.get(stamp) or '')
        effective[key]=merged
    return effective, aliases
