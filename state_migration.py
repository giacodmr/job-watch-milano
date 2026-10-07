"""Explicit, verified schema upgrade, also used by permanent migration fixtures.

No fallback readers are used at runtime. Run once under writer_lock before
switching an older checkout to the memory model.
"""
from copy import deepcopy
import hashlib
import json
from pipeline_state import BATCHES, load, transaction, writer_lock
from job_memory import IDENTITY_FIELDS, validate_memory, archive_rows, material_signature, pack_memory
from location_policy import allowed, geographies
from state_maintenance import recount

LEGACY = [f'{stem}_{b}.json' for stem in ('semantic_decisions','surfaced_jobs','semantic_queue','analysis_results','semantic_jd_cache') for b in BATCHES]+['user_job_decisions.json']

def migrate(root):
    with writer_lock(root):
        if not any((root/n).exists() for n in LEGACY): return load('state_migration_report.json', {}, root)
        assert all((root/n).exists() for n in LEGACY), 'Incomplete legacy state; restore missing inputs before migration'
        assert not any((root/f'job_memory_{b}.json').exists() for b in BATCHES), 'New memory exists: refuse overwrite'
        before = {n:load(n, root=root) for n in LEGACY}
        owners = {c:b.lower() for b, group in load('job_watch_batches.json', root=root)['batches'].items() for c in group['companies']}
        writes, archive, report = {}, [], {'version':'1.0','batches':{},'unresolved_user_decisions':{},'unresolved_records':{},'source_sha256':{n:hashlib.sha256((root/n).read_bytes()).hexdigest() for n in LEGACY}}
        users = before['user_job_decisions.json']['records']
        for b in BATCHES:
            state = before[f'analysis_results_{b}.json']['records']
            semantic = before[f'semantic_decisions_{b}.json']['records']
            surfaced = before[f'surfaced_jobs_{b}.json']['records']
            current = load(f'current_jobs_{b}.json', root=root)
            records = {}
            metrics = {'semantic':len(semantic),'surfaced':len(surfaced),'user':0,'current_before':0,'current_after':0,'first_seen_preserved':0,'closed_archived':0,'geography_excluded':0,'London_before':0,'London_after':0,'Luxembourg_before':0,'Luxembourg_after':0}
            identities = {k:{f:r[f] for f in IDENTITY_FIELDS if r.get(f) is not None} for k,r in state.items() if isinstance(r,dict)}
            # Preserve historic first-seen dates even for analysis-only rows.
            for key, row in state.items():
                if not isinstance(row,dict):
                    report['unresolved_records'][key] = row; continue
                if key not in semantic and str(row.get('analysis_method','')).startswith('chatgpt_semantic'):
                    from sync_analysis_state import SEMANTIC_FIELDS
                    semantic[key] = {f:row[f] for f in (*SEMANTIC_FIELDS,'fingerprint','analysis_method','analysis_status') if f in row}
                if key not in surfaced and row.get('surfaced_at'):
                    surfaced[key] = {'surfaced_at':row['surfaced_at'], 'surfaced_status':row.get('surfaced_status') or row.get('current_status'), 'fingerprint':row.get('surfaced_fingerprint')}
            for c in current['companies']:
                kept = []
                for j in c.get('jobs', []):
                    key = f"{c['company']}::{j['source_id']}"
                    metrics['current_before'] += 1
                    first = state.get(key, {}).get('first_seen_at') or j.get('first_seen_at')
                    if first:
                        j['first_seen_at'] = first; metrics['first_seen_preserved'] += 1
                    else: j['first_seen_at'] = current.get('generated_at')
                    j.setdefault('last_seen_at', state.get(key, {}).get('last_seen_at') or current.get('generated_at'))
                    identities[key] = {f:j[f] for f in IDENTITY_FIELDS if j.get(f) is not None}
                    identities[key]['company'] = c['company']
                    in_scope = allowed(c['company'], j.get('location'), root)
                    cities = geographies(j.get('location'))
                    for city in ('London','Luxembourg'):
                        if city in cities and j.get('status') in {'NEW','UPDATED','STILL_OPEN'}:
                            metrics[city+'_before']+=1
                            if in_scope: metrics[city+'_after']+=1
                    if j.get('status') == 'CLOSED':
                        archive.append((key, {**j,'company':c['company']})); metrics['closed_archived']+=1
                    elif in_scope:
                        kept.append(j); metrics['current_after']+=1
                    else: metrics['geography_excluded']+=1
                c['jobs']=kept
            for key in sorted(set(semantic)|set(surfaced)|{k for k in users if owners.get(k.split('::')[0])==b}):
                owner = owners.get(key.split('::')[0])
                assert owner in {b, None}, f'Cross-batch legacy key {key}'
                record = {'identity':identities.get(key, {'company':key.split('::')[0], 'source_id':key.split('::',1)[1]})}
                if key in semantic: record['semantic']=deepcopy(semantic[key])
                if key in surfaced:
                    old = deepcopy(surfaced[key])
                    stamp = old.get('surfaced_at') or old.get('last_surfaced_at')
                    assert stamp, f'Missing historic surface timestamp: {key}'
                    record['surfacing'] = {**old, 'first_surfaced_at':old.get('first_surfaced_at') or stamp,
                        'last_surfaced_at':old.get('last_surfaced_at') or stamp, 'surface_count':old.get('surface_count',1),
                        'last_surfaced_fingerprint':old.get('fingerprint') or state.get(key,{}).get('surfaced_fingerprint'),
                        'last_material_signature':material_signature(record['identity'])}
                if key in users and owner==b:
                    record['user']=deepcopy(users[key]); metrics['user']+=1
                records[key]=record
            # Analysis-only historical rows still contribute compact analytics.
            known = {k for k,j in archive}
            for key, row in state.items():
                if isinstance(row,dict) and key not in known and not row.get('current_open') and row.get('current_status')=='CLOSED':
                    archive.append((key, row)); metrics['closed_archived']+=1
            memory={'version':'1.0','batch':b.upper(),'records':records}
            validate_memory(memory,b,owners)
            for k,v in semantic.items(): assert records[k]['semantic']==v, f'Semantic loss {k}'
            for k,v in surfaced.items():
                for f,x in v.items(): assert records[k]['surfacing'].get(f)==x, f'Surface loss {k}:{f}'
            for k,v in users.items():
                if owners.get(k.split('::')[0])==b: assert records[k]['user']==v, f'User loss {k}'
            # Every known first_seen survives in current, memory, or compact archive.
            remaining={f"{c['company']}::{j['source_id']}":j for c in current['companies'] for j in c['jobs']}
            archived=dict(archive)
            for k,v in state.items():
                if isinstance(v,dict) and v.get('first_seen_at'):
                    if k not in remaining and k not in records and k not in archived:
                        archive.append((k,v)); archived[k]=v
                    destinations=[remaining.get(k,{}),records.get(k,{}).get('identity',{}),archived.get(k,{})]
                    assert any(r.get('first_seen_at')==v['first_seen_at'] for r in destinations), f'First seen loss {k}'
            metrics['semantic_migrated']=sum('semantic' in r for r in records.values())
            metrics['surfaced_migrated']=sum('surfacing' in r for r in records.values())
            recount(current)
            current['geography_excluded_count']=metrics['geography_excluded']
            writes[f'current_jobs_{b}.json']=current
            writes[f'job_memory_{b}.json']=pack_memory(memory)
            report['batches'][b]=metrics
        report['unresolved_user_decisions']={k:v for k,v in users.items() if k.split('::')[0] not in owners}
        assert sum(r['user'] for r in report['batches'].values())+len(report['unresolved_user_decisions'])==len(users)
        report['user_total']=len(users)
        report['legacy_bytes']=sum((root/n).stat().st_size for n in LEGACY)
        report['daily_bytes_before']=(root/'daily_worklist.json').stat().st_size
        report['hot_bytes_before']=report['legacy_bytes']+report['daily_bytes_before']+sum((root/f'current_jobs_{b}.json').stat().st_size for b in BATCHES)+(root/'amazon_target_check.json').stat().st_size
        report['jd_text_bytes_removed']=sum(len(r.get('text','').encode()) for b in BATCHES for r in before[f'semantic_jd_cache_{b}.json']['records'].values())
        writes['state_migration_report.json']=report
        transaction(writes, remove=LEGACY, root=root, appends=archive_rows(archive,root))
        return report
