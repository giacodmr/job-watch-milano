#!/usr/bin/env python3
"""Read an isolated Git archive. Stdout is a private pipe to the local CLI, never a log."""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import socket
import sys
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

BATCHES = ('jw1', 'jw2', 'jw3', 'jw4')
REQUIRED = ['companies_job_watch_v2.json', 'company_candidates.json', 'job_watch_batches.json',
            'job_watch_rules.json', 'amazon_target_check.json', 'daily_worklist.json',
            'job_watch_healthcheck.json', 'job_watch_run_state.json', 'pipeline_execution.json', 'daily_activity.json']
REQUIRED += [f'{stem}_{b}.json' for b in BATCHES for stem in ('ats_mapping', 'current_jobs', 'job_memory')]


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def safe_url(value):
    if not isinstance(value, str):
        return None
    p = urlsplit(value)
    if p.scheme != 'https' or not p.hostname or p.username or p.password:
        return None
    # Keep public requisition parameters, discard tracking and credentials.
    query = [(k, v) for k, v in parse_qsl(p.query) if k in {'id', 'jobId', 'jobid', 'gh_jid', 'requisitionId'}
             and len(v) <= 100 and all(c.isalnum() or c in '-_.' for c in v)]
    return urlunsplit(('https', p.netloc, p.path, urlencode(query), ''))


def extract(root, commit, observed_at):
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(root))
    def deny_network(*args, **kwargs):
        raise RuntimeError('NETWORK_DISABLED')
    socket.socket = deny_network
    socket.create_connection = deny_network
    import pipeline_state as pipeline
    import job_memory as memory_api
    import sync_analysis_state as projection_api
    import daily_worklist
    import location_policy
    for module in (pipeline, memory_api, projection_api, daily_worklist, location_policy):
        module.ROOT = root

    names = sorted(REQUIRED + [str(p.relative_to(root)) for p in root.glob('archive/vacancies_????_??.jsonl')]
                   + [str(p.relative_to(root)) for p in root.glob('.job_watch_bridge/receipts/*.json')])
    files = []
    for name in names:
        data = (root/name).read_bytes()
        files.append({'path': name, 'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)})
    hashes = {f['path']: f['sha256'] for f in files}
    def load(name):
        return json.loads((root/name).read_text())
    def provenance(name):
        return {'sourcePath': name, 'sourceSha256': hashes[name]}
    token = pipeline.snapshot(root)
    health, run = load('job_watch_healthcheck.json'), load('job_watch_run_state.json')
    if health.get('snapshot') != token or any(run.get(k) != v for k, v in token.items()):
        raise ValueError('INCOHERENT_OPERATIONAL_SNAPSHOT')

    companies = load('companies_job_watch_v2.json')['companies']
    candidates = load('company_candidates.json')['records']
    owners = {c: b.lower() for b, group in load('job_watch_batches.json')['batches'].items() for c in group['companies']}
    company_ids, rows, jobs, memories, source_ids = {}, [], {}, {}, {}
    def ensure_company(name, config=None, origin_path=None):
        if name in company_ids:
            return company_ids[name]
        config = config or {}
        active = config.get('id') is not None
        cid = 'company:' + str(config['id']) if active else 'candidate:' + digest(name)
        company_ids[name] = cid
        path = 'companies_job_watch_v2.json' if active else 'company_candidates.json' if name in candidates else origin_path
        if path is None:
            raise ValueError('MISSING_COMPANY_PROVENANCE')
        rows.append({'kind': 'company', 'id': cid, 'name': name,
                     'configId': str(config['id']) if active else None,
                     'tier': str(config['tier']) if config.get('tier') is not None else None,
                     'priority': str(config['monitoring_priority']) if config.get('monitoring_priority') is not None else None,
                     'careerUrl': safe_url(config.get('career_url')),
                     'membership': 'ACTIVE' if active else 'CANDIDATE' if name in candidates else 'HISTORICAL',
                     **provenance(path)})
        return cid
    for company in companies:
        ensure_company(company['company'], company)
    for name, candidate in sorted(candidates.items()):
        ensure_company(name, candidate)

    # Archive is authoritative evidence of an earlier CLOSED transition, not of an opening now.
    for name in names:
        if not name.startswith('archive/'):
            continue
        for line in (root/name).read_text().splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            key = rec['job_key']
            if key not in jobs or str(rec.get('last_seen_at') or '') > str(jobs[key]['identity'].get('last_seen_at') or ''):
                jobs[key] = {'identity': rec, 'batch': owners.get(rec['company']), 'lifecycle': 'CLOSED', 'path': name}

    projections, aliases, memory_rows = {}, {}, {}
    for batch in BATCHES:
        m = memory_api.load_memory(batch, root)
        # Validation uses existing ownership semantics; old excluded employers may remain in memory.
        memory_api.validate_memory(m, batch, owners)
        memories[batch] = m['records']
        memory_rows.update(m['records'])
        for key, mem in m['records'].items():
            if key not in jobs:
                jobs[key] = {'identity': mem.get('identity', {}), 'batch': batch,
                             'lifecycle': 'UNKNOWN', 'path': f'job_memory_{batch}.json'}
            elif jobs[key]['batch'] is None:
                jobs[key]['batch'] = batch
        current = load(f'current_jobs_{batch}.json')
        mapping = {c['company']: c for c in load(f'ats_mapping_{batch}.json')['companies']}
        for company in current['companies']:
            name = company['company']
            cid = ensure_company(name, origin_path=f'current_jobs_{batch}.json')
            ats = (mapping.get(name) or {}).get('ats') or {}
            family = ats.get('family') or company.get('ats_family') or 'unknown'
            # Provider/board identity excludes tracking URLs and batch routing.
            board = str(ats.get('tenant') or safe_url(ats.get('inventory_url')) or safe_url(company.get('source_url')) or name)
            source_key = family + ':' + board
            sid = 'source:' + digest(cid + '\0' + source_key)
            source_ids[name] = sid
            rows.append({'kind': 'source', 'id': sid, 'companyId': cid, 'sourceKey': source_key,
                         'family': family, 'inventoryUrl': safe_url(ats.get('inventory_url') or company.get('source_url')),
                         'coverage': company.get('coverage'), 'generatedAt': current.get('generated_at'),
                         'coveragePath': f'current_jobs_{batch}.json', 'coverageSha256': hashes[f'current_jobs_{batch}.json'],
                         **provenance(f'ats_mapping_{batch}.json')})
            for job in company.get('jobs', []):
                key = name + '::' + str(job['source_id'])
                jobs[key] = {'identity': {**job, 'company': name}, 'batch': batch,
                             'lifecycle': job.get('status', 'UNKNOWN'), 'path': f'current_jobs_{batch}.json'}
        # Use existing codec/identity resolution and projection; do not port business rules to JS.
        current_all, _, _ = projection_api.add_standard_jobs(current, root)
        _, approved = memory_api.resolve_identities(current_all, m['records'])
        urls = defaultdict(list)
        for key, rec in current_all.items():
            urls[memory_api.identity_url({**rec, 'company': rec.get('_company_name')})].append(key)
        for alias in approved:
            url = memory_api.identity_url(m['records'][alias].get('identity', {}))
            targets = urls[url]
            if len(targets) != 1 or targets[0].split('::')[0] != alias.split('::')[0]:
                raise ValueError('AMBIGUOUS_PYTHON_ALIAS')
            aliases[alias] = targets[0]
        projections.update(projection_api.project_batch(batch, root, at=observed_at)['records'])

    grouped_aliases = defaultdict(list)
    for alias, target in aliases.items():
        grouped_aliases[target].append(alias)
    job_rows = []
    for key, item in sorted(jobs.items()):
        if key in aliases:
            continue
        identity = item['identity']
        name, source_id = key.split('::', 1)
        cid = ensure_company(name, origin_path=item['path'])
        p = projections.get(key) or {}
        title, location = identity.get('title'), identity.get('location')
        job_rows.append({'kind': 'job', 'jobKey': key, 'aliases': sorted(grouped_aliases[key]),
                         'companyId': cid, 'sourceId': source_ids.get(name), 'upstreamSourceId': source_id,
                         'batch': item['batch'], 'title': title, 'location': location,
                         'canonicalUrl': safe_url(identity.get('canonical_url') or identity.get('apply_url')),
                         'applyUrl': safe_url(identity.get('apply_url')), 'fingerprint': identity.get('fingerprint'),
                         'lifecycle': item['lifecycle'], 'firstSeenAt': identity.get('first_seen_at'), 'lastSeenAt': identity.get('last_seen_at'),
                         'analysisStatus': p.get('analysis_status'), 'analysisMethod': p.get('analysis_method'),
                         'needsAnalysis': p.get('needs_analysis') if p else None, 'workerEligible': p.get('worker_eligible'),
                         'hardExclusionReason': p.get('hard_exclusion_reason'),
                         'fitScore': p.get('fit_score'), 'reportable': p.get('reportable'),
                         'effectiveDecision': p.get('user_decision') if 'user_decision' in p else (memory_rows.get(key, {}).get('user') or {}).get('decision'),
                         'technicalStatus': (p.get('jd_fetch') or {}).get('status'),
                         'sortKey': (name + '\0' + str(title or '')).casefold(), **provenance(item['path'])})
    rows.extend(job_rows)
    for batch, memory in memories.items():
        for key, record in sorted(memory.items()):
            for section in ('semantic', 'user'):
                value = record.get(section)
                if not value:
                    continue
                memory_api.assert_no_jd(value)
                # Raw decoded result is a hash preimage in the private process pipe only.
                # The Node preparer hashes it using RFC 8785 and removes it before any output/storage.
                common = {'jobKey': aliases.get(key, key), 'hashInput': value, **provenance(f'job_memory_{batch}.json')}
                if section == 'semantic':
                    rows.append({'kind': 'semantic', **common, 'fingerprint': value['fingerprint'],
                                 'method': value['analysis_method'], 'decision': value.get('decision'),
                                 'fitScore': value.get('fit_score'), 'reportable': value.get('reportable'),
                                 'evidenceState': 'HISTORICAL_SHORTENED' if 'historical_evidence' in value else 'FULL',
                                 'analyzedAt': value['analyzed_at']})
                else:
                    rows.append({'kind': 'user', **common, 'decision': value['decision'],
                                 'fingerprint': value.get('fingerprint'), 'rejectionReason': value.get('rejection_reason'),
                                 'decidedAt': value['decided_at']})
    rows.append({'kind': 'pipeline', 'runId': health.get('run_id'), 'healthStatus': health.get('status'),
                 'collectionStatus': health.get('collection_status'), 'dailyComplete': health.get('DAILY_COMPLETE'),
                 'fullSemanticComplete': health.get('FULL_SEMANTIC_COMPLETE'), 'generatedAt': health.get('generated_at'),
                 **provenance('job_watch_healthcheck.json')})
    for file in files:
        if hashlib.sha256((root/file['path']).read_bytes()).hexdigest() != file['sha256']:
            raise ValueError('PROJECTION_MUTATED_SOURCE')
    return {'commitSha': commit, 'observedAt': observed_at, 'files': files, 'rows': rows}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--commit', required=True)
    parser.add_argument('--observed-at', required=True)
    args = parser.parse_args()
    try:
        result = extract(args.root.resolve(), args.commit, args.observed_at)
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    except Exception:
        print('EXPORT_INVALID_SOURCE: inspect snapshot coherence and supported schemas locally', file=sys.stderr)
        raise SystemExit(1) from None
