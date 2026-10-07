"""Finite technical JD retries. No semantic judgments or user choices live here."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

ROME = ZoneInfo('Europe/Rome')
MAX_ATTEMPTS = 4


def local_day(stamp):
    value = datetime.fromisoformat(stamp.replace('Z', '+00:00'))
    if value.tzinfo is None:
        raise ValueError('JD retry timestamp requires timezone')
    return value.astimezone(ROME).date()


def evidence(rec):
    return {'fingerprint':rec.get('fingerprint'),
            'source_url':rec.get('canonical_url') or rec.get('apply_url') or ''}


def validate(state):
    assert isinstance(state, dict) and set(state) == {'evidence','attempts','last_failure_at','retry_from','status'}, 'Invalid JD retry schema'
    ev = state['evidence']
    assert isinstance(ev, dict) and set(ev) == {'fingerprint','source_url'} and isinstance(ev['fingerprint'], str) and ev['fingerprint'], 'Invalid JD retry evidence'
    assert isinstance(ev['source_url'], str), 'Invalid JD retry source'
    n = state['attempts']
    assert type(n) is int and 1 <= n <= MAX_ATTEMPTS, 'Invalid JD fetch count'
    day = local_day(state['last_failure_at'])
    assert state['status'] == ('JD_UNAVAILABLE' if n == MAX_ATTEMPTS else 'RETRY_PENDING'), 'Invalid JD retry status'
    assert state['retry_from'] == (None if n == MAX_ATTEMPTS else (day+timedelta(days=1)).isoformat()), 'Invalid JD retry day'


def matching(state, rec):
    return bool(state and state.get('evidence') == evidence(rec))


def eligible(state, rec, at):
    if not matching(state, rec):
        return True
    validate(state)
    return state['status'] != 'JD_UNAVAILABLE' and local_day(at).isoformat() >= state['retry_from']


def failed(state, rec, at):
    if matching(state, rec):
        if not eligible(state, rec, at):
            raise ValueError('JD fetch is not eligible for retry')
        n = state['attempts'] + 1
    else:
        n = 1
    result = {'evidence':evidence(rec), 'attempts':n, 'last_failure_at':at,
              'retry_from':None if n == MAX_ATTEMPTS else (local_day(at)+timedelta(days=1)).isoformat(),
              'status':'JD_UNAVAILABLE' if n == MAX_ATTEMPTS else 'RETRY_PENDING'}
    validate(result)
    return result


def prepare_memory(batch, records, at, root):
    """Predict the exact post-SELECT memory, committed with its canonical receipt."""
    from job_memory import load_memory, IDENTITY_FIELDS, validate_memory, pack_memory
    from sync_analysis_state import project_batch
    memory = load_memory(batch, root)
    projection = project_batch(batch, root, at=at)['records']
    changed = False
    for selected in records:
        key = selected['job_key']
        rec = projection.get(key, {})
        if not rec.get('worker_eligible') or evidence(selected) != evidence(rec):
            raise ValueError('JD fetch selection is no longer eligible')
        prior = rec.get('jd_fetch')
        if selected.get('jd_error') or not (selected.get('jd') or {}).get('text'):
            row = memory['records'].setdefault(key, {'identity':{f:rec[f] for f in IDENTITY_FIELDS if rec.get(f) is not None}})
            row['jd_fetch'] = failed(prior, rec, at)
            changed = True
        else:
            # Clear matching aliases too: an old alias must not resurrect a failure.
            for other_key, row in memory['records'].items():
                if other_key == key or (other_key.split('::')[0] == key.split('::')[0] and matching(row.get('jd_fetch'),rec)):
                    changed |= row.pop('jd_fetch', None) is not None
    if not changed:
        return {}
    validate_memory(memory, batch)
    return {f'job_memory_{batch}.json':pack_memory(memory)}
