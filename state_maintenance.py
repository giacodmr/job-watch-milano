"""Official lifecycle transitions. Caller holds the pipeline writer lock."""
from copy import deepcopy
from pipeline_state import load, transaction
from job_memory import load_memory, archive_rows, IDENTITY_FIELDS, pack_memory
from location_policy import allowed

def recount(current):
    summary = current.setdefault('summary', {})
    jobs = [j for c in current.get('companies', []) for j in c.get('jobs', [])]
    for status in ('NEW','UPDATED','STILL_OPEN','CLOSED','UNKNOWN'):
        summary[status] = sum(j.get('status') == status for j in jobs)
    summary['target_jobs_open'] = sum(summary[s] for s in ('NEW','UPDATED','STILL_OPEN'))
    for c in current.get('companies', []):
        c['target_jobs_count'] = sum(j.get('status') in {'NEW','UPDATED','STILL_OPEN'} for j in c.get('jobs', []))

def maintain_batch(batch, root):
    from sync_analysis_state import add_standard_jobs, overlay_amazon_priority
    name = f'current_jobs_{batch}.json'
    current = load(name, None, root)
    memory = load_memory(batch, root)
    before_current, before_memory = deepcopy(current), deepcopy(memory)
    if batch == 'jw2':
        all_jobs, open_jobs, urls = add_standard_jobs(current, root)
        overlay_amazon_priority(batch, all_jobs, open_jobs, urls)
        amazon = next((c for c in current['companies'] if c['company'] == 'Amazon'), None)
        if amazon is not None:
            byid = {str(j['source_id']): j for j in amazon.get('jobs', [])}
            for key, j in all_jobs.items():
                if j.get('_company_name') != 'Amazon': continue
                clean = {k:v for k,v in j.items() if not k.startswith('_')}
                clean['priority_company'] = bool(j.get('_priority_company') or clean.get('priority_company'))
                if j.get('_priority_jd_stale'): clean['priority_jd_stale'] = True
                clean['company'] = 'Amazon'
                clean['first_seen_at'] = byid.get(str(j['source_id']), {}).get('first_seen_at') or memory['records'].get(key, {}).get('identity', {}).get('first_seen_at') or clean.get('first_seen_at') or current.get('generated_at')
                byid[str(j['source_id'])] = clean
            amazon['jobs'] = list(byid.values())
    closed, excluded = [], 0
    for company in current['companies']:
        keep = []
        for j in company.get('jobs', []):
            key = f"{company['company']}::{j['source_id']}"
            j.setdefault('first_seen_at', memory['records'].get(key, {}).get('identity', {}).get('first_seen_at') or current.get('generated_at'))
            j.setdefault('last_seen_at', current.get('generated_at'))
            if key in memory['records']:
                memory['records'][key]['identity'] = {f:j[f] for f in IDENTITY_FIELDS if j.get(f) is not None}
                memory['records'][key]['identity']['company'] = company['company']
            if j.get('status') == 'CLOSED':
                closed.append((key, {**j, 'company':company['company']}))
            elif allowed(company['company'], j.get('location'), root) or (j.get('status')=='UNKNOWN' and not j.get('location') and memory['records'].get(key,{}).get('user',{}).get('decision') in {'INTERESTED','TO_REVIEW'}):
                keep.append(j)
            else:
                excluded += 1
        company['jobs'] = keep
    if excluded:
        current['geography_excluded_count'] = current.get('geography_excluded_count', 0)+excluded
    recount(current)
    writes = {}
    if current != before_current: writes[name] = current
    if memory != before_memory: writes[f'job_memory_{batch}.json'] = pack_memory(memory)
    if writes or closed: transaction(writes, root=root, appends=archive_rows(closed, root))
