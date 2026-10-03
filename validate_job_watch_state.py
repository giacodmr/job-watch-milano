#!/usr/bin/env python3
"""Validate derived invariants without discarding unrelated source checkpoints."""
from pathlib import Path
from pipeline_state import BATCHES, load, snapshot, record_error
ROOT = Path(__file__).resolve().parent


def validate_batch(batch,root=None):
    root = root or ROOT
    from audit_job_watch import extracted_open_keys, canonical_key
    cur = load(f'current_jobs_{batch}.json',root=root)
    state = load(f'analysis_results_{batch}.json',root=root)
    queue = load(f'semantic_queue_{batch}.json',root=root)
    records = state['records']
    base = extracted_open_keys(cur)
    assert cur.get('summary',{}).get('target_jobs_open') == len(base), 'Inventory summary/count mismatch'
    extra = set()
    if batch == 'jw2':
        for job in load('amazon_target_check.json',{'target_jobs':[]},root).get('target_jobs',[]):
            if job.get('status') in {'NEW','STILL_OPEN','UPDATED'}:
                url = canonical_key(job.get('apply_url'))
                key = f'url::{url}' if url else f"id::Amazon::{job.get('job_id')}"
                if key not in base: extra.add(key)
    assert sum(bool(r.get('current_open')) for r in records.values()) == len(base)+len(extra), 'Current inventory/analysis mismatch'
    expected = {k for k,r in records.items() if r.get('current_open') and r.get('needs_analysis')}
    rows = queue['records']; actual = {r['job_key'] for r in rows}
    assert actual == expected and len(actual) == len(rows), 'Semantic queue mismatch/duplicates'
    assert queue['pending_count'] == len(rows), 'Semantic queue count mismatch'
    assert all(r.get('fingerprint') and r['fingerprint'] == records[r['job_key']].get('fingerprint') for r in rows), 'Queue fingerprint mismatch'


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
