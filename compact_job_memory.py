#!/usr/bin/env python3
"""Explicit historical evidence reduction; dry-run unless --apply is supplied.

Open/UNKNOWN identities, public-URL aliases and active user choices stay whole.
Shortened evidence never qualifies as a fresh review of a reopened vacancy.
"""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from job_memory import load_memory, pack_memory, unpack_memory, memory_json, identity_url, validate_memory
from pipeline_state import BATCHES, load, writer_lock, transaction

ROOT = Path(__file__).resolve().parent
HISTORICAL_FIELDS = (
    'experience_required', 'mandatory_vs_preferred_requirements',
    'decision_scope_and_ownership', 'seniority_evidence',
    'direct_reports_or_team_lead_scope', 'budget_or_p_and_l_ownership',
    'domain_experience_required', 'education_or_certifications_required',
)

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()

def shorten(value, limit=200):
    if isinstance(value, str):
        return value if len(value) <= limit else value[:limit-1].rstrip()+'…'
    if isinstance(value, list):
        items = [shorten(v, 140) for v in value[:3]]
        if len(value) > 3: items.append(f'… ({len(value)-3} ulteriori requisiti omessi)')
        return items
    if isinstance(value, dict): return {k:shorten(v, 140) for k,v in value.items()}
    return value

def compact_decision(decision):
    if not isinstance(decision, dict) or 'historical_evidence' in decision:
        return deepcopy(decision)
    if not any(f in decision for f in HISTORICAL_FIELDS): return deepcopy(decision)
    result = {k:deepcopy(v) for k,v in decision.items() if k not in HISTORICAL_FIELDS}
    evidence = {'version':1, 'source_sha256':digest(decision)}
    for name, value in (
        ('experience', decision.get('experience_required') or decision.get('seniority_evidence')),
        ('requirements', decision.get('mandatory_vs_preferred_requirements')),
        ('scope', decision.get('decision_scope_and_ownership') or decision.get('direct_reports_or_team_lead_scope')),
    ):
        if value is not None: evidence[name] = shorten(value)
    result['historical_evidence'] = evidence
    # Do not trade detailed evidence for a larger receipt.
    size = lambda obj: len(json.dumps(obj, ensure_ascii=False, separators=(',', ':')).encode())
    return result if size(decision)-size(result) >= 128 else deepcopy(decision)

def compact_batch(batch, memory, current):
    records = memory['records']
    keys, urls = set(), set()
    for company in current['companies']:
        for job in company.get('jobs', []):
            keys.add(f"{company['company']}::{job['source_id']}")
            url = identity_url({**job, 'company':company['company']})
            if url: urls.add((company['company'], url))
    result = deepcopy(memory)
    counts = {'semantic_total':0, 'protected':0, 'newly_shortened':0, 'already_shortened':0}
    for key, row in records.items():
        decision = row.get('semantic')
        if not decision: continue
        counts['semantic_total'] += 1
        if 'historical_evidence' in decision:
            counts['already_shortened'] += 1
            continue
        identity = row.get('identity', {})
        protected = (key in keys or (key.split('::')[0], identity_url(identity)) in urls
                     or row.get('user', {}).get('decision') in {'INTERESTED', 'TO_REVIEW'})
        if protected:
            counts['protected'] += 1
            continue
        compacted = compact_decision(decision)
        if compacted != decision:
            result['records'][key]['semantic'] = compacted
            counts['newly_shortened'] += 1
        # Non-evidence values, user state, identity and actual surfacing never change.
        for field, value in decision.items():
            if field not in HISTORICAL_FIELDS:
                assert compacted[field] == value, f'Conclusion changed: {key}:{field}'
        assert {k:v for k,v in result['records'][key].items() if k != 'semantic'} == {k:v for k,v in row.items() if k != 'semantic'}
    validate_memory(result, batch)
    assert set(result['records']) == set(records)
    return result, counts

def compact(root=ROOT, apply=False):
    from sync_analysis_state import project_batch
    with writer_lock(root):
        before = {b:load_memory(b, root) for b in BATCHES}
        projections = {b:project_batch(b, root) for b in BATCHES}
        writes, report = {}, {'version':'1.0', 'policy':'historical-only; active identities and user choices preserved; reopen requires full JD', 'batches':{}}
        for b in BATCHES:
            name = f'job_memory_{b}.json'
            memory, counts = compact_batch(b, before[b], load(f'current_jobs_{b}.json', root=root))
            packed = pack_memory(memory)
            assert unpack_memory(packed) == memory
            # Compare actual queue/reporting projections using the candidate
            # decoded store before any write, including alias resolution.
            assert project_batch(b, root, memory_override=memory) == projections[b], f'Live projection changed in {b}'
            old_bytes, new_bytes = (root/name).stat().st_size, len(memory_json(packed).encode())
            report['batches'][b] = {**counts, 'bytes_before':old_bytes, 'bytes_after':new_bytes,
                'bytes_with_compact_layout_only':len(memory_json(before[b]).encode()),
                'bytes_after_shortening_before_pool':len(memory_json(memory).encode()),
                'source_sha256':hashlib.sha256((root/name).read_bytes()).hexdigest(),
                'decoded_before_sha256':digest(before[b]), 'decoded_after_sha256':digest(memory),
                'live_projection_sha256':digest(projections[b]), 'live_projection_unchanged':True}
            if (root/name).read_text() != memory_json(packed): writes[name] = packed
        report['bytes_before'] = sum(row['bytes_before'] for row in report['batches'].values())
        report['bytes_after'] = sum(row['bytes_after'] for row in report['batches'].values())
        report['saved_bytes'] = report['bytes_before']-report['bytes_after']
        if apply and writes:
            transaction({**writes, 'semantic_compaction_report.json':report}, root=root)
        return report

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='Commit verified reductions atomically; default is dry-run')
    args = parser.parse_args()
    print(json.dumps(compact(apply=args.apply), ensure_ascii=False, indent=2))
