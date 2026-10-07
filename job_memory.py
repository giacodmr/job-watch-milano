"""Durable decisions and surfacing, partitioned by batch; no derived state or JD."""
from pathlib import Path
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pipeline_state import load, BATCHES, now

ROOT = Path(__file__).resolve().parent
USER_STATES = {'TO_REVIEW', 'INTERESTED', 'APPLIED', 'NOT_INTERESTED'}
JD_FIELDS = {'text', 'description', 'description_short', 'job_description', 'body', 'basic_qualifications', 'preferred_qualifications', 'jd'}
IDENTITY_FIELDS = ('company', 'source_id', 'title', 'location', 'canonical_url', 'apply_url', 'first_seen_at', 'last_seen_at', 'role_family', 'fingerprint')
EVIDENCE_ENCODING = 'sha256-text-v1'
EVIDENCE_REF = '$e'

def evidence_key(text):
    return hashlib.sha256(text.encode()).hexdigest()[:20]

def assert_no_evidence_refs(obj):
    if isinstance(obj, dict):
        if EVIDENCE_REF in obj: raise ValueError('Unresolved semantic evidence reference')
        for value in obj.values(): assert_no_evidence_refs(value)
    elif isinstance(obj, list):
        for value in obj: assert_no_evidence_refs(value)

def unpack_memory(stored):
    """Resolve only verified, batch-local text references; never invent defaults."""
    result = deepcopy(stored)
    encoding = result.pop('evidence_encoding', None)
    pool = result.pop('semantic_evidence', None)
    if encoding is None:
        if pool is not None: raise ValueError('Evidence pool without encoding')
        assert_no_evidence_refs(result)
        return result
    if encoding != EVIDENCE_ENCODING or not isinstance(pool, dict):
        raise ValueError('Invalid semantic evidence encoding')
    for key, value in pool.items():
        if not isinstance(value, str) or evidence_key(value) != key:
            raise ValueError('Corrupt semantic evidence text/hash')
    used = set()
    def expand(obj):
        if isinstance(obj, dict):
            if EVIDENCE_REF in obj:
                key = obj[EVIDENCE_REF]
                if len(obj) != 1 or not isinstance(key, str) or key not in pool:
                    raise ValueError('Missing or malformed semantic evidence reference')
                used.add(key)
                return pool[key]
            return {k:expand(v) for k,v in obj.items()}
        if isinstance(obj, list): return [expand(v) for v in obj]
        return obj
    for row in result['records'].values():
        if 'semantic' in row: row['semantic'] = expand(row['semantic'])
    if used != set(pool): raise ValueError('Unused semantic evidence in pool')
    assert_no_evidence_refs(result)
    assert_no_jd(result)
    return result

def pack_memory(memory):
    """Deduplicate repeated semantic text; preserve all decoded JSON values."""
    assert_no_jd(memory)
    assert_no_evidence_refs(memory)
    if 'evidence_encoding' in memory or 'semantic_evidence' in memory:
        raise ValueError('Pack requires decoded memory')
    counts = Counter()
    def count(obj):
        if isinstance(obj, str) and len(obj.encode()) >= 80: counts[obj] += 1
        elif isinstance(obj, dict):
            for value in obj.values(): count(value)
        elif isinstance(obj, list):
            for value in obj: count(value)
    for row in memory['records'].values(): count(row.get('semantic', {}))
    pool, refs = {}, {}
    for value, n in sorted(counts.items()):
        key = evidence_key(value)
        size = len(json.dumps(value, ensure_ascii=False).encode())
        ref_size = len(json.dumps({EVIDENCE_REF:key}, separators=(',', ':')).encode())
        if n*(size-ref_size) <= size+len(key)+40: continue
        if key in pool and pool[key] != value: raise ValueError('Semantic evidence hash collision')
        pool[key] = value; refs[value] = {EVIDENCE_REF:key}
    def compress(obj):
        if isinstance(obj, str): return refs.get(obj, obj)
        if isinstance(obj, dict): return {k:compress(v) for k,v in obj.items()}
        if isinstance(obj, list): return [compress(v) for v in obj]
        return obj
    result = deepcopy(memory)
    for row in result['records'].values():
        if 'semantic' in row: row['semantic'] = compress(row['semantic'])
    result.update(evidence_encoding=EVIDENCE_ENCODING, semantic_evidence=dict(sorted(pool.items())))
    if unpack_memory(result) != memory: raise ValueError('Semantic evidence roundtrip failed')
    return result

def memory_json(memory):
    """One record/text per line keeps diffs useful without deeply indented copies."""
    dump = lambda obj: json.dumps(obj, ensure_ascii=False, separators=(',', ':'))
    lines = ['{']
    for key, value in memory.items():
        if key in {'records', 'semantic_evidence'}:
            entries = ',\n'.join('    '+dump(k)+':'+dump(v) for k,v in value.items())
            lines.append('  '+dump(key)+':{'+ ('\n'+entries+'\n  ' if entries else '') + '},')
        else: lines.append('  '+dump(key)+':'+dump(value)+',')
    lines[-1] = lines[-1].removesuffix(',')
    return '\n'.join(lines)+'\n}\n'

def load_memory(batch, root=None):
    if batch not in BATCHES: raise ValueError('Unknown batch')
    result = load(f'job_memory_{batch}.json', None, root or ROOT)
    if not isinstance(result, dict) or not isinstance(result.get('records'), dict):
        raise ValueError(f'Missing/invalid job memory: {batch}')
    return unpack_memory(result)

def assert_no_jd(obj):
    if isinstance(obj, dict):
        assert not JD_FIELDS.intersection(obj), 'Full JD field in persistent memory'
        for value in obj.values(): assert_no_jd(value)
    elif isinstance(obj, list):
        for value in obj: assert_no_jd(value)


def validate_memory(memory, batch, owners=None):
    assert_no_evidence_refs(memory)
    assert memory.get('batch', '').lower() == batch, 'Memory batch ownership mismatch'
    assert_no_jd(memory)
    for key, row in memory['records'].items():
        assert isinstance(key, str) and isinstance(row, dict), 'Malformed memory record'
        if owners: assert owners.get(key.split('::')[0], batch) == batch, 'Wrong company owner'
        if row.get('user'):
            assert row['user']['decision'] in USER_STATES and row['user'].get('decided_at'), 'Invalid user decision'
        if 'jd_fetch' in row:
            from jd_retry import validate
            validate(row['jd_fetch'])
        semantic = row.get('semantic', {})
        if isinstance(semantic, dict) and 'historical_evidence' in semantic:
            evidence = semantic['historical_evidence']
            assert isinstance(evidence, dict) and evidence.get('version') == 1, 'Invalid historical evidence schema'
            original = evidence.get('source_sha256')
            assert isinstance(original, str) and len(original) == 64 and all(c in '0123456789abcdef' for c in original), 'Missing historical evidence provenance'
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
                if options:
                    merged[section]=max(options,key=lambda r:(r.get(stamp) or '',
                        section == 'semantic' and 'historical_evidence' not in r,
                        r == own.get(section)))
        effective[key]=merged
        from jd_retry import matching
        candidates = [r['jd_fetch'] for _,r in matches if matching(r.get('jd_fetch'),job)]
        if matching(own.get('jd_fetch'),job): candidates.append(own['jd_fetch'])
        merged.pop('jd_fetch', None)
        if candidates:
            merged['jd_fetch'] = max(candidates, key=lambda r:(r['last_failure_at'],r['attempts']))
    return effective, aliases
