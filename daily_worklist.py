#!/usr/bin/env python3
"""Small, deterministic projection of actionable state; never a decision store."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BATCHES = ('jw1', 'jw2', 'jw3', 'jw4')


def load(name, default=None):
    p = ROOT / name
    return json.loads(p.read_text()) if p.exists() else default


def action_reason(rec):
    if not rec.get('current_open') or rec.get('company') in {'ION Group'}:
        return None
    user = rec.get('user_decision')
    if user == 'NOT_INTERESTED':
        return None
    if user == 'APPLIED':
        return 'APPLIED_UPDATE' if rec.get('applied_material_update') else None
    if user in {'TO_REVIEW', 'INTERESTED'}:
        return user
    if rec.get('needs_analysis'):
        if rec.get('priority_company'):
            return 'PRIORITY_PENDING'
        if rec.get('delta_pending') or rec.get('current_status') in {'NEW', 'UPDATED'} or rec.get('user_decision_stale'):
            return 'DELTA_PENDING'
    if rec.get('reportable') and (rec.get('priority_company') or (rec.get('fit_score') or 0) >= (rec.get('threshold') or 0)):
        if not rec.get('surfaced_at') or rec.get('delta_pending'):
            return 'REPORT'
    return None


def build_worklist(backlog_limit=None):
    manifest = load('job_watch_run_state.json', {})
    rules = load('job_watch_rules.json', {})
    rules_sha = hashlib.sha256((ROOT / 'job_watch_rules.json').read_bytes()).hexdigest()
    token = {'run_id': manifest.get('run_id'), 'source_generated_at': manifest.get('source_generated_at'),
             'priority_snapshot_at': manifest.get('priority_snapshot_at'), 'rules_sha256': rules_sha}
    previous = load('daily_worklist.json', {})
    limit = backlog_limit if backlog_limit is not None else rules.get('daily_worklist_policy', {}).get('backlog_limit', 20)
    records, historical, lifecycle, pending = [], [], [], 0
    known_keys = set()
    fields = ('company', 'source_id', 'title', 'location', 'target_city', 'priority_company', 'canonical_url',
              'apply_url', 'fingerprint', 'current_status', 'threshold', 'user_decision', 'user_decision_reason',
              'user_decision_stale', 'role_family', 'job_category')
    for batch in BATCHES:
        state = load(f'analysis_results_{batch}.json', {'records': {}})
        known_keys.update(state['records'])
        cache = load(f'semantic_jd_cache_{batch}.json', {'records': {}}).get('records', {})
        surfaced = load(f'surfaced_jobs_{batch}.json', {'records': {}}).get('records', {})
        pending += sum(bool(r.get('current_open') and r.get('needs_analysis')) for r in state['records'].values())
        for key, rec in state['records'].items():
            if rec.get('company') == 'ION Group':
                continue
            if not rec.get('current_open'):
                history = surfaced.get(key, {})
                reported = history.get('fingerprint') == rec.get('fingerprint') and history.get('surfaced_status') == rec.get('current_status')
                if rec.get('user_decision') in {'TO_REVIEW', 'INTERESTED', 'APPLIED'} and rec.get('current_status') in {'CLOSED', 'UNKNOWN'} and not reported:
                    lifecycle.append({'batch': batch.upper(), 'job_key': key, 'action': 'LIFECYCLE_UPDATE', **{f: rec.get(f) for f in fields if rec.get(f) is not None}})
                continue
            reason = action_reason(rec)
            if not reason and not rec.get('needs_analysis'):
                continue
            row = {'batch': batch.upper(), 'job_key': key, 'action': reason or 'HISTORICAL_BACKLOG',
                   'needs_semantic_review': bool(rec.get('needs_analysis')),
                   **{f: rec.get(f) for f in fields if rec.get(f) is not None}}
            if rec.get('needs_analysis'):
                jd = cache.get(key, {})
                if jd.get('status') == 'OK' and jd.get('fingerprint') == rec.get('fingerprint') and len(jd.get('text') or '') >= 120:
                    row['jd'] = {f: jd[f] for f in ('text', 'source_url', 'method', 'fetched_at') if f in jd}
                else:
                    row['jd_status'] = 'MISSING' if not jd or jd.get('fingerprint') != rec.get('fingerprint') else jd.get('status')
                    if row['jd_status'] == 'FAILED':
                        row['jd_error'] = jd.get('error')
            else:
                row['decision'] = {f: rec[f] for f in ('fit_score', 'reportable', 'rationale', 'salary', 'salary_source',
                      'mandatory_years_experience', 'preferred_years_experience', 'final_experience_status', 'l68_status') if f in rec}
            if reason:
                records.append(row)
            else:
                historical.append((rec.get('first_seen_at') or '', row))
    historical.sort(key=lambda x: (x[0], x[1]['job_key']))
    if previous.get('snapshot') == token and backlog_limit is None:
        assigned = previous.get('backlog_assignment', [])
    else:
        assigned = [r['job_key'] for _, r in historical[:limit]]
    selected = [r for _, r in historical if r['job_key'] in assigned]
    records.extend(selected)
    records.sort(key=lambda r: (r['action'] == 'HISTORICAL_BACKLOG', not r.get('needs_semantic_review'),
                             not r.get('priority_company'), r['batch'], r['job_key']))
    return {'version': '1.0', 'snapshot': token, 'rules_file': 'job_watch_rules.json',
            'instructions_file': 'DAILY.md', 'backlog_assignment': assigned,
            'summary': {'records': len(records), 'daily_semantic_pending': sum(r['needs_semantic_review'] for r in records if r['action'] != 'HISTORICAL_BACKLOG'),
                        'backlog_assigned': len(selected), 'historical_backlog_remaining': len(historical),
                        'full_semantic_pending': pending},
            'records': records, 'lifecycle_updates': lifecycle,
            'unreconciled_user_decisions': [{'job_key': k, **v} for k, v in load('user_job_decisions.json', {'records': {}})['records'].items()
                if k not in known_keys and v.get('decision') in {'TO_REVIEW', 'INTERESTED', 'APPLIED'} and not k.startswith('ION Group::')]}



def main():
    payload = build_worklist()
    text = json.dumps(payload, ensure_ascii=False, indent=2) + '\n'
    path = ROOT / 'daily_worklist.json'
    if not path.exists() or path.read_text() != text:
        path.write_text(text)
    print('Daily worklist:', payload['summary'])


if __name__ == '__main__':
    main()
