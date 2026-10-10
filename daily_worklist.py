#!/usr/bin/env python3
"""Bounded daily projection. Analysis debt stays in the derived worker queue."""
import json
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from pipeline_state import BATCHES, snapshot, record_error, search_complete, priority_status, now
from harden_job_watch_state import queue_sort_key

ROOT = Path(__file__).resolve().parent

def load(name, default=None):
    p = ROOT/name
    return json.loads(p.read_text()) if p.exists() else default

def action_reason(rec, at=None, rules=None):
    if rec.get('company') == 'ION Group': return None
    user = rec.get('user_decision')
    if user in {'APPLIED','NOT_INTERESTED'}: return None
    if user in {'INTERESTED','TO_REVIEW'}: return user
    if not rec.get('current_open') or rec.get('needs_analysis'): return None
    if not rec.get('reportable') or (not rec.get('priority_company') and (rec.get('fit_score') or 0)<rec.get('threshold',70)): return None
    surface = rec.get('surfacing', {})
    if not surface: return 'NEW_INTERESTING'
    if (surface.get('last_material_signature') and surface['last_material_signature'] != rec.get('material_signature')) or (
        rec.get('material_change') and surface.get('last_surfaced_fingerprint') != rec.get('fingerprint')):
        return 'NEW_INTERESTING'
    try:
        first = datetime.fromisoformat(surface['first_surfaced_at'].replace('Z','+00:00'))
        last = datetime.fromisoformat(surface['last_surfaced_at'].replace('Z','+00:00'))
        current = datetime.fromisoformat((at or now()).replace('Z','+00:00'))
        policy = (rules or {}).get('daily_worklist_policy', {})
        age = (current-first).total_seconds()/86400
        if 0 <= age < policy.get('reminder_days',3) and (rec.get('fit_score') or 0)>=policy.get('reminder_min_fit',80) and last.astimezone(ZoneInfo('Europe/Rome')).date()<current.astimezone(ZoneInfo('Europe/Rome')).date():
            return 'REMINDER'
    except (KeyError,TypeError,ValueError): pass
    return None

def build_worklist(backlog_limit=None, at=None):
    from sync_analysis_state import project_batch
    rules = load('job_watch_rules.json', {})
    token = snapshot(ROOT)
    policy = rules.get('daily_worklist_policy', {})
    limit = backlog_limit if backlog_limit is not None else policy.get('worker_batch_size',20)
    records, candidates, selection_pool, pending = [], [], [], 0
    processable, deferred, unavailable = 0, 0, 0
    fields = ('company','source_id','title','location','target_city','priority_company','canonical_url','apply_url',
              'fingerprint','current_status','threshold','user_decision','user_decision_reason','role_family','first_seen_at',
              'requires_full_jd_review','guardrail_reason')
    for batch in BATCHES:
        try:
            state = project_batch(batch, ROOT, at=at)
        except (ValueError,OSError,KeyError,TypeError) as exc:
            record_error('BATCH_ERROR','worklist','MEMORY_UNAVAILABLE',exc,root=ROOT,batch=batch.upper())
            continue
        pending += state['summary']['pending_analysis']
        processable += len(state['queue'])
        deferred += state['summary']['jd_retry_deferred']
        unavailable += state['summary']['jd_unavailable']
        for key, rec in state['records'].items():
            reason = action_reason(rec, at, rules)
            if rec.get('needs_analysis') and not rec.get('worker_eligible') and not reason:
                continue
            # Rank the official snapshot, including completed decisions. Finishing
            # one selection cannot silently pull the rest of the debt into Daily.
            from sync_analysis_state import hard_exclusion_reason
            if rec.get('current_open') and rec.get('current_status') in {'NEW','UPDATED'} and not hard_exclusion_reason(rec.get('title')):
                selection_pool.append({'job_key':key,'batch':batch.upper(),**rec})
            if not reason and not rec.get('needs_analysis'): continue
            row = {'batch':batch.upper(),'job_key':key,'action':reason or 'NEW_CANDIDATE',
                   'needs_semantic_review':bool(rec.get('needs_analysis')),
                   **{f:rec[f] for f in fields if rec.get(f) is not None}}
            if row.get('apply_url') == row.get('canonical_url'): row.pop('apply_url',None)
            if rec.get('needs_analysis'):
                if rec.get('worker_eligible'):
                    candidates.append(row)
                elif reason:
                    row['technical_status'] = rec['jd_fetch']['status']
                    records.append(row)  # Preserve explicit active choices, even without a JD.
            else:
                row['decision'] = {f:rec[f] for f in ('fit_score','reportable','salary','salary_source','final_experience_status','l68_status') if rec.get(f) is not None}
                if rec.get('rationale'): row['decision']['rationale']=str(rec['rationale'])[:360]
                if not rec.get('current_open'): row['lifecycle']='CLOSED_OR_UNVERIFIED'
                records.append(row)
    candidates.sort(key=lambda r:(queue_sort_key(r),r['batch'],r['job_key']))
    selection_pool.sort(key=lambda r:(queue_sort_key(r),r['batch'],r['job_key']))
    eligible = {(r['batch'],r['job_key']) for r in selection_pool[:max(0,limit)]}
    selected = [r for r in candidates if (r['batch'],r['job_key']) in eligible]
    records.extend(selected)
    ranks={'NEW_INTERESTING':0,'INTERESTED':1,'TO_REVIEW':2,'REMINDER':3,'NEW_CANDIDATE':4}
    records.sort(key=lambda r:(ranks[r['action']],not r.get('priority_company'),r['batch'],r['job_key']))
    tasks=[{'batch':b.upper(),'action':'AUTONOMOUS_SEARCH'} for b in BATCHES if not search_complete(b,ROOT)]
    tasks += [{'action':'RETRY_PRIORITY_COLLECTION','company':c} for c,v in priority_status(ROOT).items() if v in {'FAILED','NOT_RUN'}]
    return {'version':'2.0','snapshot':token,'rules_file':'job_watch_rules.json','instructions_file':'DAILY.md',
        'summary':{'records':len(records),'daily_semantic_pending':len(selected),'backlog_assigned':0,
                   'historical_backlog_remaining':max(0,pending-len(selected)),'full_semantic_pending':pending,
                   'processable_semantic_pending':processable,'jd_retry_deferred':deferred,'jd_unavailable':unavailable},
        'records':records,'lifecycle_updates':[],'tasks':tasks}

def main():
    from pipeline_state import atomic_json
    payload=build_worklist(); atomic_json(ROOT/'daily_worklist.json',payload)
    print('Daily worklist:',payload['summary'])

if __name__=='__main__': main()
