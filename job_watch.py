#!/usr/bin/env python3
"""Explicit collector/sync entry point; shared by Actions and local verification."""
import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BATCHES = ('jw1', 'jw2', 'jw3', 'jw4')
REGISTRIES = [f'job_memory_{b}.json' for b in BATCHES]
DERIVED = ['daily_worklist.json','job_watch_audit.json','job_watch_healthcheck.json','job_watch_summary.txt','pipeline_execution.json','daily_activity.json','rejected_daily_updates.json']
WORKER_DERIVED = ['daily_worklist.json','job_watch_audit.json','job_watch_healthcheck.json','job_watch_summary.txt']


def project_state():
    """Refresh read models without consuming Daily commands or maintaining sources."""
    invoke('daily_worklist', 'main')
    for batch in BATCHES:
        invoke('audit_job_watch', 'write_batch_metrics', batch)
    invoke('certify_job_watch', 'main')
    return True


def run(script):
    subprocess.run([sys.executable, str(ROOT / script)], cwd=ROOT, check=True)


def apply_updates(locked=False):
    from pipeline_state import writer_lock, StaleSnapshot
    if not locked:
        with writer_lock(ROOT):
            return apply_updates(locked=True)
    from pipeline_state import transaction, snapshot, record_error, refresh_run_state
    from daily_worklist import build_worklist
    from harden_job_watch_state import semantic_decision_valid
    from sync_analysis_state import project_batch
    from job_memory import load_memory, record_surface, IDENTITY_FIELDS, validate_memory, assert_no_jd, older_timestamp, pack_memory
    from rejection_reasons import REJECTION_REASONS, infer_rejection_reason, reason_is_vague
    path = ROOT / 'daily_updates.json'
    if not path.exists(): return False
    def load(name): return json.loads((ROOT/name).read_text())
    patch = load(path.name)
    import hashlib
    patch_id = hashlib.sha256(json.dumps(patch,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    activity = load('daily_activity.json') if (ROOT/'daily_activity.json').exists() else {'version':'1.0','batches':{}}
    if patch_id in activity.get('applied_update_ids',[]):
        transaction({},['daily_updates.json'],root=ROOT)
        print('Already applied patch: preserved newer registry/evidence updates')
        return True
    work = build_worklist()
    if patch.get('version') != '1.0' or patch.get('snapshot') != work['snapshot']:
        raise SystemExit('STALE_REVIEW: reload daily_worklist; patch retained, no registry writes')
    expected = work['snapshot']
    allowed = {(r['batch'].lower(),r['job_key']):r for r in work['records']+work['lifecycle_updates']}
    projections = {b:project_batch(b,ROOT)['records'] for b in BATCHES}
    stores = {b:load_memory(b,ROOT) for b in BATCHES}
    dirty = set()
    changes, rejected = {}, {'version':'1.0','snapshot':expected}
    def reject(section, batch, key, row, exc):
        rejected.setdefault(section,{}).setdefault(batch,{})[key] = row
        record_error('LOCAL_RECORD_ERROR','semantic_patch','INVALID_REVIEW',exc,root=ROOT,batch=batch.upper(),job_key=key)
    for section in ('semantic_decisions','surfaced_jobs'):
        for batch, updates in patch.get(section,{}).items():
            if batch not in BATCHES or not isinstance(updates,dict):
                raise SystemExit('PATCH_SCHEMA: invalid batch/records; patch retained')
            store = stores[batch]
            analysis = projections[batch]
            for key, row in updates.items():
                try:
                    rec = analysis.get(key,{})
                    if not isinstance(row,dict) or row.get('fingerprint') != rec.get('fingerprint') or not rec:
                        raise ValueError('Unexpected record or changed fingerprint: refresh and review')
                    assert_no_jd(row)
                    if section == 'semantic_decisions':
                        if rec.get('user_decision') in {'APPLIED','NOT_INTERESTED'}: raise ValueError('Explicit user choice suppresses ordinary review')
                        if not rec.get('current_open'): raise ValueError('Vacancy is no longer verified open')
                        if older_timestamp(row.get('analyzed_at'), store['records'].get(key,{}).get('semantic',{}).get('analyzed_at')): raise ValueError('Older semantic decision cannot overwrite a newer review')
                        valid, reason = semantic_decision_valid(row,rec)
                        if not valid: raise ValueError(reason)
                    elif (batch,key) not in allowed or not row.get('surfaced_at') or not row.get('surfaced_status'):
                        raise ValueError('Incomplete surfaced history')
                    record = store['records'].setdefault(key, {})
                    record['identity'] = {f:rec[f] for f in IDENTITY_FIELDS if rec.get(f) is not None}
                    if section == 'semantic_decisions': record['semantic'] = row
                    else: record_surface(record, row, rec)
                    dirty.add(batch)
                except (ValueError,TypeError,KeyError,AssertionError) as exc:
                    reject(section,batch,key,row,exc)
    known = {k:(b,r) for b in BATCHES for k,r in projections[b].items()}
    for b,store in stores.items():
        for k,r in store['records'].items(): known.setdefault(k, (b,r.get('identity',{})))
    for key, row in patch.get('user_decisions',{}).items():
        try:
            if not isinstance(row,dict) or row.get('decision') not in {'TO_REVIEW','INTERESTED','APPLIED','NOT_INTERESTED'} or not row.get('decided_at'):
                raise ValueError('Invalid explicit user decision')
            row = dict(row)
            assert_no_jd(row)
            if row['decision'] == 'NOT_INTERESTED':
                category = row.get('rejection_reason') or infer_rejection_reason(row.get('reason'))
                if category not in REJECTION_REASONS or reason_is_vague(row.get('reason')):
                    raise ValueError('Ask user for rejection reason')
                inferred = infer_rejection_reason(row.get('reason'))
                if inferred and inferred != category: raise ValueError('Category conflicts with explicit reason')
                row['rejection_reason'] = category
            if key not in known or not row.get('fingerprint') or row['fingerprint'] != known[key][1].get('fingerprint'):
                raise ValueError('Changed/missing user fingerprint')
            batch,rec = known[key]
            prior = stores[batch]['records'].get(key,{}).get('user',{})
            previous_at = rec.get('user_decided_at') or prior.get('decided_at')
            if older_timestamp(row['decided_at'], previous_at): raise ValueError('Older explicit choice cannot overwrite a newer choice')
            stores[batch]['records'].setdefault(key, {'identity':{f:rec[f] for f in IDENTITY_FIELDS if rec.get(f) is not None}})['user'] = row
            dirty.add(batch)
        except (ValueError,TypeError,KeyError,AssertionError) as exc:
            rejected.setdefault('user_decisions',{})[key] = row
            record_error('LOCAL_RECORD_ERROR','semantic_patch','INVALID_USER_UPDATE',exc,root=ROOT,job_key=key)
    owners={c:b.lower() for b,g in load('job_watch_batches.json')['batches'].items() for c in g['companies']}
    for batch in dirty:
        validate_memory(stores[batch], batch, owners)
        changes[f'job_memory_{batch}.json'] = pack_memory(stores[batch])
    if 'manifest' in patch:
        raise SystemExit('PATCH_SCHEMA: completion flags retired; submit actual search evidence in activity')
    if 'activity' in patch:
        for batch,row in patch['activity'].items():
            if batch not in {b.upper() for b in BATCHES} or not isinstance(row,dict) or not isinstance(row.get('searches'),list) or not row['searches']:
                raise SystemExit('PATCH_SCHEMA: actual per-batch search evidence required')
            if any(not isinstance(e,dict) or not all(e.get(f) for f in ('query','checked_at','source_url','result')) for e in row['searches']):
                raise SystemExit('PATCH_SCHEMA: search query/date/source/result required')
            activity['batches'][batch] = {**row,'snapshot':expected}
        changes['daily_activity.json'] = activity
    activity.setdefault('applied_update_ids',[]).append(patch_id)
    changes['daily_activity.json'] = activity
    remove = ['daily_updates.json']
    if len(rejected) > 2:
        changes['rejected_daily_updates.json'] = rejected
    try:
        transaction(changes,remove,root=ROOT,expected_snapshot=expected)
    except StaleSnapshot as exc:
        raise SystemExit(str(exc)) from exc
    print('Merged valid snapshot-bound updates:', ', '.join(changes))
    return True


def invoke(module, function, *args):
    import importlib
    return getattr(importlib.import_module(module),function)(*args)


def stage(name):
    from pipeline_state import atomic_json, attempt, record_error, refresh_run_state, load
    # Strict static integrity runs in CI. Runtime trust checks isolate batch input
    # failures and never depend on a stale derived artifact or optional script.
    global_names = ('job_watch_rules.json','job_watch_batches.json','companies_job_watch_v2.json','company_candidates.json')
    for filename in global_names:
        try:
            data = load(filename,root=ROOT)
            if not isinstance(data,dict): raise ValueError('Required global object missing')
            if filename == 'job_watch_batches.json' and set(data.get('batches',{})) != {b.upper() for b in BATCHES}: raise ValueError('Global batch schema must define JW1-JW4')
            if filename == 'companies_job_watch_v2.json' and not isinstance(data.get('companies'),list): raise ValueError('Global company universe invalid')
            if filename == 'company_candidates.json' and not isinstance(data.get('records'),dict): raise ValueError('Global candidate staging invalid')
            if filename == 'job_watch_rules.json' and not data.get('run_certification_policy',{}).get('enabled'): raise ValueError('Missing certification policy')
        except (ValueError,OSError) as exc:
            atomic_json(ROOT/'pipeline_execution.json',{'version':'1.0','stages':{},'errors':[]})
            record_error('GLOBAL_FATAL_ERROR','inputs','INVALID_GLOBAL_INPUT',exc,root=ROOT,file=filename)
            certify_fallback()
            return False
    if name == 'collect':
        atomic_json(ROOT/'pipeline_execution.json',{'version':'1.0','status':'PENDING','stages':{},'errors':[]})
    else:
        # Scoped execution failures persist until that stage actually succeeds.
        report = load('pipeline_execution.json',{'version':'1.0','stages':{},'errors':[]},ROOT)
        keep = {'collection','reconciliation'} | ({'amazon'} if name != 'amazon' else set())
        report['errors'] = [e for e in report['errors'] if e.get('stage') in keep]
        report['stages'] = {k:v for k,v in report['stages'].items() if k.split(':')[0] in {'collection','reconciliation','amazon'}}
        atomic_json(ROOT/'pipeline_execution.json',report)
    if name == 'collect':
        for b in BATCHES: attempt('collection',lambda b=b:invoke("collector","collect_batch",b),batch=b,root=ROOT)
        for b in BATCHES: attempt('reconciliation',lambda b=b:invoke("reconcile_workday_target_paths","reconcile_batch",b),batch=b,root=ROOT)
    if name in {'collect','amazon'}:
        attempt('amazon',lambda:invoke("amazon_target_check","main"),company='Amazon',root=ROOT)
    report = load('pipeline_execution.json',{'stages':{},'errors':[]},ROOT)
    report['status'] = 'COLLECTED'
    atomic_json(ROOT/'pipeline_execution.json',report)
    attempt('snapshot',lambda:refresh_run_state(ROOT),root=ROOT)
    if name == 'sync': attempt('semantic_patch',lambda:apply_updates(locked=True),root=ROOT)
    for b in BATCHES: attempt('semantic_sync',lambda b=b:invoke("sync_analysis_state","sync_batch",b),batch=b,root=ROOT)
    attempt('worklist',lambda:invoke('daily_worklist','main'),root=ROOT)
    for b in BATCHES: attempt('metrics',lambda b=b:invoke('audit_job_watch','write_batch_metrics',b),batch=b,root=ROOT)
    # Validation failures invalidate certification, not valid collection checkpoints.
    attempt('validation',lambda:invoke('validate_job_watch_state','main'),root=ROOT)
    if attempt('certification',lambda:invoke('certify_job_watch','main'),root=ROOT) is None:
        record_error('GLOBAL_FATAL_ERROR','certification','CERTIFIER_UNAVAILABLE','Repair missing or broken certification entrypoint',root=ROOT,file='certify_job_watch.py')
        certify_fallback()
    return not any(e['category'] == 'GLOBAL_FATAL_ERROR' for e in load('pipeline_execution.json',{'errors':[]},ROOT)['errors'])


def certify_fallback():
    from pipeline_state import atomic_json, load, now
    report = load('pipeline_execution.json',{'errors':[]},ROOT)
    tasks = [{'action':'REPAIR_GLOBAL_INPUT' if e.get('stage')=='inputs' else 'REPAIR_CERTIFICATION_STAGE','file':e.get('file'),'reason':e['message']} for e in report['errors'] if e['category']=='GLOBAL_FATAL_ERROR']
    health = {'version':'2.0','generated_at':now(),'run_id':None,'status':'BLOCKED_GLOBAL','collection_status':'BLOCKED_GLOBAL',
              'DAILY_COMPLETE':False,'FULL_SEMANTIC_COMPLETE':False,'priority_checks':{'Amazon':'NOT_RUN','Mastercard':'NOT_RUN'},
              'batches':{b.upper():{'status':'BLOCKED_GLOBAL','daily_complete':False,'full_semantic_complete':False,'gpt_run_certified':False} for b in BATCHES},
              'coverage':{},'daily_actionable_remaining':None,'historical_backlog_remaining':None,'source_failures':None,'partial_sources':None,
              'errors':report['errors'],'error_counts':{scope:sum(e['scope']==scope for e in report['errors']) for scope in ('record','source','batch','global')},'remaining_work':tasks}
    atomic_json(ROOT/'job_watch_healthcheck.json',health)
    text = 'JOB WATCH RUN: BLOCKED_GLOBAL\nDAILY_COMPLETE: false\nFULL_SEMANTIC_COMPLETE: false\n'+'\n'.join(str(t) for t in tasks)+'\n'
    (ROOT/'job_watch_summary.txt').write_text(text)
    print(text)


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT, text=True).strip()


def regenerate(name):
    # Parent holds the writer lock; a fresh interpreter loads the fetched code.
    subprocess.run([sys.executable,'-c','import sys, job_watch; job_watch.stage(sys.argv[1])',name],cwd=ROOT,check=True)


def reset_generated_checkout():
    # Actions started clean. Stage newly generated archive files so reset also
    # removes a new monthly file before recomputing against the fetched state.
    # Otherwise an untracked archive from the losing attempt would be appended
    # a second time during regeneration.
    archives=[str(p.relative_to(ROOT)) for p in (ROOT/'archive').glob('*.jsonl')]
    if archives: git('add','--',*archives)
    git('reset','--hard','origin/main')


def publish(name):
    files = list(DERIVED) + REGISTRIES + ['job_watch_run_state.json'] + [f'current_jobs_{b}.json' for b in BATCHES] + list(str(p.relative_to(ROOT)) for p in (ROOT/'archive').glob('*.jsonl'))
    files = [f for f in files if (ROOT/f).exists() or git('ls-files',f)]
    if git('ls-files','daily_updates.json'):
        files += ['daily_updates.json']
    if name in {'collect','amazon'}:
        files += ['amazon_target_check.json','job_watch_run_state.json']
    if name == 'collect':
        files += [f'current_jobs_{b}.json' for b in BATCHES]
    # Keep the uncommitted input patch across retries, then revalidate against latest sources.
    pending_path = ROOT/'.pending_daily_updates.json' if (ROOT/'.pending_daily_updates.json').exists() else ROOT/'daily_updates.json'
    pending = pending_path.read_bytes() if pending_path.exists() else None
    # No rebases of generated data: recompute from the latest inputs on a race.
    for attempt in range(3):
        git('fetch', 'origin', 'main')
        if git('rev-parse','HEAD') != git('rev-parse','origin/main'):
            reset_generated_checkout()
            if pending is not None: (ROOT/'daily_updates.json').write_bytes(pending)
            regenerate(name)
        files = [f for f in files if (ROOT/f).exists() or git('ls-files',f)]
        files += [str(p.relative_to(ROOT)) for p in (ROOT/'archive').glob('*.jsonl') if str(p.relative_to(ROOT)) not in files]
        git('add', '--', *files)
        if not git('diff','--cached','--name-only'):
            print('No generated changes to publish.')
            return
        git('commit','-m',f'Update Job Watch {name} state')
        result = subprocess.run(['git','push','origin','HEAD:main'], cwd=ROOT)
        if result.returncode == 0:
            return
        git('fetch','origin','main')
        reset_generated_checkout()
        if pending is not None: (ROOT/'daily_updates.json').write_bytes(pending)
        regenerate(name)
    raise SystemExit('State publication failed after three retries.')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=('sync','collect','amazon','migrate','project'))
    parser.add_argument('--publish', action='store_true', help='Actions-only generated state publication')
    args = parser.parse_args()
    if args.stage == 'project' and args.publish:
        parser.error('project is read-model only; publication belongs to the bridge')
    if args.stage == 'migrate':
        from state_migration import migrate
        migrate(ROOT)
        return
    if args.publish:
        import os
        if os.environ.get('GITHUB_ACTIONS') != 'true' or os.environ.get('GITHUB_REF') != 'refs/heads/main':
            raise SystemExit('--publish is restricted to GitHub Actions on main')
        if git('status','--porcelain'):
            raise SystemExit('--publish requires a clean checkout before running')
    from pipeline_state import writer_lock
    with writer_lock(ROOT):
        patch_bytes = (ROOT/'daily_updates.json').read_bytes() if (ROOT/'daily_updates.json').exists() else None
        if args.publish:
            git('fetch','origin','main')
            git('reset','--hard','origin/main')
            if patch_bytes is not None: (ROOT/'daily_updates.json').write_bytes(patch_bytes)
        ok = project_state() if args.stage == 'project' else stage(args.stage)
        if args.publish:
            # Recovery must preserve the consumed command too, not only derived outputs.
            if patch_bytes is not None:
                (ROOT/'.pending_daily_updates.json').write_bytes(patch_bytes)
            git('config','user.name','github-actions[bot]')
            git('config','user.email','41898282+github-actions[bot]@users.noreply.github.com')
            publish(args.stage)
            (ROOT/'.pending_daily_updates.json').unlink(missing_ok=True)
        if not ok: raise SystemExit(1)


if __name__ == '__main__':
    main()
