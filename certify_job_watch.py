#!/usr/bin/env python3
"""Single deterministic authority for daily/full completion and readable health."""
from pathlib import Path
from pipeline_state import BATCHES, load, stable_dump, now, snapshot, priority_status, search_complete, error
ROOT = Path(__file__).resolve().parent


def certify(root=ROOT):
    token = snapshot(root)
    priority = priority_status(root)
    report = load('pipeline_execution.json',{'stages':{},'errors':[]},root)
    audit = load('job_watch_audit.json',{'batches':{}},root)
    work = load('daily_worklist.json',{'records':[],'lifecycle_updates':[]},root)
    errors = list(report.get('errors',[]))
    # Persisted source results remain authoritative when another stage runs.
    for b in BATCHES:
        try:
            cur = load(f'current_jobs_{b}.json',{},root)
            for company in cur.get('companies',[]):
                for field in ('collection_error','reconciliation_error'):
                    item = company.get(field)
                    if item and item not in errors: errors.append(item)
                for job in company.get('jobs',[]):
                    item = job.get('reconciliation_error')
                    if item and job.get('status') == 'UNKNOWN' and item not in errors: errors.append(item)
        except (ValueError,OSError,TypeError,AttributeError): pass
    remaining, batches, coverage = [], {}, {}
    rules = load('job_watch_rules.json',{},root)
    # Unresolved user roles are maintenance warnings, never an impossible review
    # against a vacancy whose JD/source cannot currently be verified.
    for row in work.get('unreconciled_user_decisions',[]):
        item = error('LOCAL_RECORD_ERROR','reconciliation','ACTIVE_ROLE_UNRESOLVED','Locate official lifecycle; preserve user choice',job_key=row['job_key'])
        if not any(e.get('job_key') == row['job_key'] for e in errors): errors.append(item)
    for b in BATCHES:
        name = b.upper()
        metrics = audit.get('batches',{}).get(name,{})
        checks = metrics.get('checks',{})
        vac = metrics.get('vacancy_analysis_coverage',{})
        cov = metrics.get('company_ats_coverage',{})
        coverage[name] = cov
        scoped = [e for e in errors if e.get('batch') in {name,None} and e['category'] == 'BATCH_ERROR']
        local = [e for e in errors if e.get('batch') == name]
        tasks = []
        if scoped or not checks.get('inventory_reconciliation') or not checks.get('state_reconciliation'):
            tasks.append({'batch':name,'action':'REPAIR_BATCH_STATE','reason':'Rerun failed stage or reconcile official inventory/state','stages':sorted({e['stage'] for e in scoped})})
        if rules.get('run_certification_policy',{}).get('require_current_day'):
            from collection_freshness import workday
            try:
                fresh = workday(token['source_generated_at'][name]) == workday(now())
            except (ValueError,TypeError): fresh = False
            if not fresh: tasks.append({'batch':name,'action':'COLLECT_CURRENT_DAY','reason':'Official source snapshot is not for the current Rome workday (23:00 collection boundary)'})
        semantic = int(vac.get('actionable_delta_pending',0) or 0)
        reporting = max(0,int(vac.get('actionable_reportable',0) or 0)-int(vac.get('actionable_surfaced',0) or 0))
        if semantic: tasks.append({'batch':name,'action':'SEMANTIC_REVIEW','count':semantic,'reason':'Review exact current fingerprints in daily worklist'})
        if reporting: tasks.append({'batch':name,'action':'REPORT_OPPORTUNITIES','count':reporting,'reason':'Show decided opportunities/material updates; persist surfaced fingerprints'})
        if not search_complete(b,root): tasks.append({'batch':name,'action':'AUTONOMOUS_SEARCH','reason':'Search official sources; record actual query/date/source/result in activity'})
        required = {'jw1':'Mastercard','jw2':'Amazon'}.get(b)
        if required and priority[required] in {'FAILED','NOT_RUN'}:
            tasks.append({'batch':name,'action':'RETRY_PRIORITY_COLLECTION','company':required,'reason':'No usable priority inventory; retry official source'})
        if int(cov.get('NOT_CHECKED',0) or 0): tasks.append({'batch':name,'action':'COLLECT_UNATTEMPTED_SOURCES','count':cov['NOT_CHECKED']})
        warnings = bool(local or cov.get('PARTIAL') or cov.get('FAILED') or (required and priority[required] == 'PARTIAL'))
        daily = not tasks
        full = daily and int(vac.get('pending_analysis',0) or 0) == 0 and checks.get('reporting_reconciliation') is True
        batches[name] = {'status':'NEEDS_REVIEW' if tasks else 'COMPLETE_WITH_WARNINGS' if warnings else 'COMPLETE',
            'processable_semantic_pending':vac.get('queue_pending',0),
            'jd_retry_deferred':vac.get('jd_retry_deferred',0), 'jd_unavailable':vac.get('jd_unavailable',0),
            'daily_complete':daily,'full_semantic_complete':full,'gpt_run_certified':daily,
            'actionable_delta_pending':semantic,'reporting_pending':reporting,'historical_backlog_remaining':vac.get('historical_backlog_remaining',0),
            'failed':cov.get('FAILED',0),'not_checked':cov.get('NOT_CHECKED',0),'remaining_work':tasks}
        remaining.extend(tasks)
    global_errors = [e for e in errors if e['category'] == 'GLOBAL_FATAL_ERROR']
    remaining.extend({'action':'REPAIR_GLOBAL_INPUT','reason':e['message'],'file':e.get('file')} for e in global_errors)
    if global_errors:
        for row in batches.values(): row.update(status='BLOCKED_GLOBAL',daily_complete=False,full_semantic_complete=False,gpt_run_certified=False)
    daily = not remaining
    full = daily and all(row['full_semantic_complete'] for row in batches.values())
    warnings = bool(errors or any(v['status']=='COMPLETE_WITH_WARNINGS' for v in batches.values()))
    collection_errors = [e for e in errors if e['stage'] in {'collection','reconciliation','amazon'}]
    status = 'BLOCKED_GLOBAL' if global_errors else 'NEEDS_REVIEW' if remaining else 'COMPLETE_WITH_WARNINGS' if warnings else 'COMPLETE'
    counts = {scope:sum(e['scope']==scope for e in errors) for scope in ('record','source','batch','global')}
    # Health is bound to authoritative sources, not old audit timestamps.
    return {'version':'2.0','generated_at':now(),'run_id':token['run_id'],'snapshot':token,'status':status,
        'collection_status':'COMPLETE_WITH_WARNINGS' if collection_errors else 'COMPLETE',
        'DAILY_COMPLETE':daily,'FULL_SEMANTIC_COMPLETE':full,'priority_checks':priority,'batches':batches,'coverage':coverage,
        'daily_actionable_remaining':sum(v['actionable_delta_pending']+v['reporting_pending'] for v in batches.values()),
        'processable_semantic_pending':sum(v['processable_semantic_pending'] for v in batches.values()),
        'jd_retry_deferred':sum(v['jd_retry_deferred'] for v in batches.values()),
        'jd_unavailable':sum(v['jd_unavailable'] for v in batches.values()),
        'historical_backlog_remaining':sum(v['historical_backlog_remaining'] for v in batches.values()),
        'source_failures':sum(c.get('FAILED',0) for c in coverage.values()),'partial_sources':sum(c.get('PARTIAL',0) for c in coverage.values()),
        'error_counts':counts,'errors':errors,'stage_reports':{**report.get('stages',{}),'certification':{'status':'COMPLETE'}},'remaining_work':remaining,
        'unresolved_user_decisions':[e['job_key'] for e in errors if e['scope']=='record' and e.get('job_key') and e['code'] in {'ROLE_UNRESOLVED','ACTIVE_ROLE_UNRESOLVED'}],
        'blocking_errors':[e['code'] for e in global_errors], 'certification_mode':'SCOPED_FAIL_CLOSED'}


def summary(h):
    lines = ['JOB WATCH RUN', 'Run: '+h['run_id'], 'State: '+h['status'], 'Collection: '+h['collection_status']]
    lines += [b+': '+r['status'] for b,r in h['batches'].items()]
    lines += [c+': '+v for c,v in h['priority_checks'].items()]
    lines += ['',f"Daily actionable remaining: {h['daily_actionable_remaining']}",f"Historical backlog: {h['historical_backlog_remaining']}"]
    lines += [f"Processable semantic pending: {h.get('processable_semantic_pending',0)}",
              f"JD retry deferred: {h.get('jd_retry_deferred',0)}", f"JD unavailable: {h.get('jd_unavailable',0)}"]
    lines += [f"Source failures: {h['source_failures']}",f"Partial sources: {h['partial_sources']}"]
    lines += [f"{scope} errors: {count}" for scope,count in h['error_counts'].items()]
    lines += [f"DAILY_COMPLETE: {str(h['DAILY_COMPLETE']).lower()}",f"FULL_SEMANTIC_COMPLETE: {str(h['FULL_SEMANTIC_COMPLETE']).lower()}"]
    lines += ['Remaining: '+str(t) for t in h['remaining_work']]
    return '\n'.join(lines)+'\n'


def main():
    health = certify(ROOT)
    stable_dump('job_watch_healthcheck.json',health,ROOT)
    text = summary(health)
    path = ROOT/'job_watch_summary.txt'
    if not path.exists() or path.read_text() != text: path.write_text(text)
    print(text)
    return 0


if __name__ == '__main__': main()
