#!/usr/bin/env python3
"""Validate derived invariants without discarding unrelated source checkpoints."""
from pathlib import Path
from pipeline_state import BATCHES, load, snapshot, record_error
ROOT = Path(__file__).resolve().parent


def validate_batch(batch,root=None):
    root = root or ROOT
    from audit_job_watch import extracted_open_keys, canonical_key
    cur = load(f'current_jobs_{batch}.json',root=root)
    from sync_analysis_state import project_batch
    from job_memory import load_memory, validate_memory, assert_no_jd
    from location_policy import allowed
    assert_no_jd(cur)
    memory = load_memory(batch, root)
    owners = {c:b.lower() for b,g in load('job_watch_batches.json', {'batches':{}}, root)['batches'].items() for c in g['companies']}
    validate_memory(memory, batch, owners)
    state = project_batch(batch, root)
    records = state['records']
    base = extracted_open_keys(cur)
    assert cur.get('summary',{}).get('target_jobs_open') == len(base), 'Inventory summary/count mismatch'
    assert sum(bool(r.get('current_open')) for r in records.values()) == len(base), 'Current inventory/memory projection mismatch'
    expected = {k for k,r in records.items() if r.get('current_open') and r.get('needs_analysis') and r.get('worker_eligible')}
    rows = state['queue']; actual = {r['job_key'] for r in rows}
    assert actual == expected and len(actual) == len(rows), 'Derived semantic queue mismatch/duplicates'
    assert all(r.get('fingerprint') and r['fingerprint'] == records[r['job_key']].get('fingerprint') for r in rows), 'Queue fingerprint mismatch'
    for c in cur['companies']:
        for j in c.get('jobs', []):
            assert j.get('status') != 'CLOSED', 'Closed vacancy remains in hot inventory'
            assert allowed(c['company'], j.get('location'), root) or (j.get('status')=='UNKNOWN' and not j.get('location') and memory['records'].get(f"{c['company']}::{j['source_id']}",{}).get('user',{}).get('decision') in {'INTERESTED','TO_REVIEW'}), 'Out of scope vacancy in hot inventory'
            assert j.get('first_seen_at'), 'Missing first seen'


def main(strict=False):
    failures = []
    for b in BATCHES:
        try: validate_batch(b)
        except (Exception,AssertionError) as exc:
            failures.append(str(exc))
            record_error('BATCH_ERROR','validation','STATE_INVARIANT_FAILED',exc,root=ROOT,batch=b.upper())
    try:
        from daily_worklist import build_worklist
        work = load('daily_worklist.json',root=ROOT)
        assert work['snapshot'] == snapshot(ROOT), 'Stale worklist snapshot: reload'
        assert work == build_worklist(), 'Worklist/cache projection mismatch: regenerate'
    except Exception as exc:
        failures.append(str(exc))
        record_error('BATCH_ERROR','validation','WORKLIST_STALE',exc,root=ROOT)
    print('Scoped derived-state validation finished; inspect final health for recovery actions.')
    if strict and failures: raise SystemExit("INTEGRITY ERROR: "+"; ".join(failures))
    return 0


if __name__ == '__main__':
    import sys
    main(strict='--strict' in sys.argv)
