#!/usr/bin/env python3
"""Explicit collector/sync entry point; shared by Actions and local verification."""
import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BATCHES = ('jw1', 'jw2', 'jw3', 'jw4')
REGISTRIES = [f'{stem}_{b}.json' for stem in ('semantic_decisions','surfaced_jobs') for b in BATCHES]
DERIVED = [f'{stem}_{b}.json' for stem in ('analysis_results','semantic_queue') for b in BATCHES] + ['daily_worklist.json','job_watch_audit.json','job_watch_healthcheck.json','user_job_decisions.json']
CACHES = [f'semantic_jd_cache_{b}.json' for b in BATCHES]


def run(script):
    subprocess.run([sys.executable, str(ROOT / script)], cwd=ROOT, check=True)


def apply_updates():
    """Merge a small snapshot-bound patch without exposing whole registries to ChatGPT."""
    path = ROOT / 'daily_updates.json'
    if not path.exists():
        return False
    from daily_worklist import build_worklist
    from harden_job_watch_state import semantic_decision_valid
    from rejection_reasons import REJECTION_REASONS, infer_rejection_reason, reason_is_vague
    def load(name):
        return json.loads((ROOT / name).read_text())
    patch = load(path.name)
    work = build_worklist()
    if patch.get('version') != '1.0' or patch.get('snapshot') != work['snapshot']:
        raise SystemExit('DAILY UPDATE ERROR: stale/incompatible patch; refresh the worklist snapshot')
    manifest = load('job_watch_run_state.json')
    if manifest.get('source_generated_at') != {b.upper(): load(f'current_jobs_{b}.json').get('generated_at') for b in BATCHES} or manifest.get('priority_snapshot_at', {}).get('Amazon') != load('amazon_target_check.json').get('checked_at'):
        raise SystemExit('DAILY UPDATE ERROR: manifest does not match current official snapshots')
    allowed = {(r['batch'].lower(), r['job_key']): r for r in work['records'] + work['lifecycle_updates']}
    changes = {}
    for section, stem in [('semantic_decisions','semantic_decisions'),('surfaced_jobs','surfaced_jobs')]:
        for batch, updates in patch.get(section, {}).items():
            if batch not in BATCHES or not isinstance(updates, dict):
                raise SystemExit('DAILY UPDATE ERROR: invalid batch/records')
            name = f'{stem}_{batch}.json'
            store = load(name)
            analysis = load(f'analysis_results_{batch}.json')['records']
            for key, row in updates.items():
                rec = analysis.get(key, {})
                if (batch, key) not in allowed or not isinstance(row, dict) or row.get('fingerprint') != rec.get('fingerprint'):
                    raise SystemExit(f'DAILY UPDATE ERROR: unexpected/stale {key}')
                if section == 'semantic_decisions':
                    if not rec.get('current_open'):
                        raise SystemExit(f'DAILY UPDATE ERROR: semantic patch on closed/unknown {key}')
                    valid, reason = semantic_decision_valid(row, rec)
                    if not valid:
                        raise SystemExit(f'DAILY UPDATE ERROR: {key}: {reason}')
                elif not row.get('surfaced_at') or not row.get('surfaced_status'):
                    raise SystemExit(f'DAILY UPDATE ERROR: incomplete surfaced history {key}')
                store['records'][key] = row
            changes[name] = store
    users = load('user_job_decisions.json')
    known = {k: r for b in BATCHES for k, r in load(f'analysis_results_{b}.json')['records'].items()}
    for key, row in patch.get('user_decisions', {}).items():
        if not isinstance(row, dict) or row.get('decision') not in {'TO_REVIEW','INTERESTED','APPLIED','NOT_INTERESTED'} or not row.get('decided_at'):
            raise SystemExit(f'DAILY UPDATE ERROR: invalid user decision {key}')
        if row['decision'] == 'NOT_INTERESTED':
            category = row.get('rejection_reason') or infer_rejection_reason(row.get('reason'))
            if category not in REJECTION_REASONS or reason_is_vague(row.get('reason')):
                raise SystemExit(f'DAILY UPDATE ERROR: ask user for rejection reason for {key}')
            row['rejection_reason'] = category
        if key not in known or not row.get('fingerprint') or row['fingerprint'] != known[key].get('fingerprint'):
            raise SystemExit(f'DAILY UPDATE ERROR: missing user fingerprint {key}')
        users['records'][key] = row
    if patch.get('user_decisions'):
        changes['user_job_decisions.json'] = users
    if 'manifest' in patch:
        updated = patch['manifest']
        if not isinstance(updated, dict) or any(updated.get(k) != manifest.get(k) for k in ('run_id','source_generated_at','priority_snapshot_at')):
            raise SystemExit('DAILY UPDATE ERROR: manifest snapshot/identity changed')
        changes['job_watch_run_state.json'] = updated
    # Validation of all patches finishes before touching any existing registry.
    for name, value in changes.items():
        (ROOT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    path.unlink()
    print('Merged snapshot-bound daily updates:', ', '.join(changes))
    return True


def stage(name):
    run('preflight_job_watch.py')
    run('validate_job_watch_inputs.py')
    if name == 'sync':
        if apply_updates():
            run('validate_job_watch_inputs.py')
    if name == 'collect':
        run('collector.py')
        run('reconcile_workday_target_paths.py')
        run('amazon_target_check.py')
        run('initialize_daily_run_state.py')
    elif name == 'amazon':
        run('amazon_target_check.py')
        # New priority snapshot invalidates the former semantic certification explicitly.
        run('initialize_daily_run_state.py')
    run('sync_analysis_state.py')
    if name in {'collect','amazon','enrich'}:
        run('enrich_semantic_jds.py')
    run('daily_worklist.py')
    run('audit_job_watch.py')
    run('certify_job_watch.py')
    run('validate_job_watch_state.py')
    run('validate_certified_run.py')


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT, text=True).strip()


def publish(name):
    files = list(DERIVED) + REGISTRIES + ['job_watch_run_state.json']
    if git('ls-files','daily_updates.json'):
        files += ['daily_updates.json']
    if name in {'collect','amazon','enrich'}:
        files += CACHES
    if name in {'collect','amazon'}:
        files += ['amazon_target_check.json','job_watch_run_state.json']
    if name == 'collect':
        files += [f'current_jobs_{b}.json' for b in BATCHES]
    # No rebases of generated data: recompute from the latest inputs on a race.
    for attempt in range(3):
        git('fetch', 'origin', 'main')
        if git('rev-parse','HEAD') != git('rev-parse','origin/main'):
            git('reset','--hard','origin/main')
            stage(name)
        git('add', '--', *files)
        if not git('diff','--cached','--name-only'):
            print('No generated changes to publish.')
            return
        git('commit','-m',f'Update Job Watch {name} state')
        result = subprocess.run(['git','push','origin','HEAD:main'], cwd=ROOT)
        if result.returncode == 0:
            return
        git('fetch','origin','main')
        git('reset','--hard','origin/main')
        stage(name)
    raise SystemExit('State publication failed after three retries.')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=('sync','collect','amazon','enrich'))
    parser.add_argument('--publish', action='store_true', help='Actions-only generated state publication')
    args = parser.parse_args()
    if args.publish:
        import os
        if os.environ.get('GITHUB_ACTIONS') != 'true' or os.environ.get('GITHUB_REF') != 'refs/heads/main':
            raise SystemExit('--publish is restricted to GitHub Actions on main')
        if git('status','--porcelain'):
            raise SystemExit('--publish requires a clean checkout before running')
    stage(args.stage)
    if args.publish:
        git('config','user.name','github-actions[bot]')
        git('config','user.email','41898282+github-actions[bot]@users.noreply.github.com')
        publish(args.stage)


if __name__ == '__main__':
    main()
